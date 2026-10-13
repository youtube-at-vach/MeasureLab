//! Device ownership, timeouts and bounded control service. The same manager
//! services both destinations; only one execution side can generate at a time.
use super::*;

const CALLBACK_TIMEOUT: Duration = Duration::from_secs(2);
const STOP_TIMEOUT: Duration = Duration::from_millis(500);

fn stream_failure(
    failed: bool,
    since_callback: Duration,
    since_stop: Option<Duration>,
    stopped: bool,
) -> Option<generator::Error> {
    if failed {
        Some(generator::Error::OutputStream)
    } else if since_callback > CALLBACK_TIMEOUT
        || since_stop.is_some_and(|elapsed| elapsed > STOP_TIMEOUT && !stopped)
    {
        Some(generator::Error::CallbackStalled)
    } else {
        None
    }
}

fn rebuild(
    status: Status,
    rate: u32,
    channels: usize,
    settings: Settings,
    stop: &Arc<AtomicU64>,
) -> Result<(control::Controller, control::Execution), generator::Error> {
    let mut engine = Engine::with_clock(
        rate,
        channels,
        settings,
        status.next_sample,
        status.output_generation,
    )?;
    engine.configure(
        settings,
        status
            .revision
            .checked_add(1)
            .ok_or(generator::Error::CounterExhausted)?,
    )?;
    Ok(control::from_engine_with_stop(engine, stop.clone()))
}

pub(super) fn run(
    requests: mpsc::Receiver<Request>,
    mut feedback: Producer<Update>,
    stop: Arc<AtomicU64>,
    events: mpsc::SyncSender<Event>,
    history: history::Handle,
) {
    let engine = Engine::new(48000, 2, Settings::default(), 0).unwrap();
    let (mut controller, execution) = control::from_engine_with_stop(engine, stop.clone());
    let mut execution = Some(execution);
    let mut status = execution.as_ref().unwrap().status();
    let mut target = Target::Internal;
    let mut stream: Option<(cpal::Stream, Arc<device::Metrics>)> = None;
    let mut device_metrics: Option<Arc<device::Metrics>> = None;
    let mut observed_lost_reports = 0;
    let mut observed_notifications = 0;
    let mut capture: Option<(Producer<Frame>, Arc<Metrics>)> = None;
    let mut clock = Instant::now();
    let mut fraction = 0.0;
    let mut error = None;
    let mut acknowledged_request = 0;
    let mut pending_request = 0;
    let mut pending_revision = None;
    let mut acknowledged_stop = 0;
    let mut seen_stop = 0;
    let mut stop_started = None;
    let mut shutdown = false;
    let mut activity = None;
    let mut callbacks = 0;
    let mut last_callback = Instant::now();
    loop {
        let epoch = stop.load(Ordering::Acquire);
        if epoch != seen_stop {
            seen_stop = epoch;
            pending_revision = None;
            stop_started = Some(Instant::now());
        }
        for _ in 0..16 {
            let Ok(request) = requests.try_recv() else {
                break;
            };
            if matches!(request.command, Command::Shutdown) {
                shutdown = true;
                break;
            }
            if matches!(request.command, Command::Refresh) {
                let _ = events.try_send(match device::enumerate() {
                    Ok(devices) => Event::Devices(devices),
                    Err(e) => Event::Error(e),
                });
                continue;
            }
            let epoch = stop.load(Ordering::Acquire);
            if request.stop_epoch != epoch && !matches!(request.command, Command::Attach(..)) {
                acknowledged_request = acknowledged_request.max(request.id);
                continue;
            }
            let is_control = !matches!(request.command, Command::Attach(..));
            if is_control {
                pending_request = request.id;
            }
            let result = match request.command {
                Command::Select(new_target, rate, settings) => {
                    if !matches!(status.state, State::Stopped | State::Error(_))
                        || pending_revision.is_some_and(|rev| rev > status.revision)
                        || capture
                            .as_ref()
                            .is_some_and(|(_, m)| m.active.load(Ordering::Acquire))
                    {
                        Err(generator::Error::AlreadyActive)
                    } else {
                        rebuild(status, rate, new_target.channels(), settings, &stop).map(
                            |(c, e)| {
                                stream.take();
                                // Audit notifications after backend listeners
                                // have been released, before resetting counters.
                                if let Some(m) = &device_metrics {
                                    let count = m.notifications.load(Ordering::Acquire);
                                    history.losses(0, count.saturating_sub(observed_notifications));
                                }
                                device_metrics = None;
                                observed_notifications = 0;
                                observed_lost_reports = 0;
                                controller = c;
                                execution = Some(e);
                                status = execution.as_ref().unwrap().status();
                                target = new_target;
                                pending_revision = None;
                                clock = Instant::now();
                                fraction = 0.0;
                            },
                        )
                    }
                }
                Command::Configure(settings) => controller
                    .submit(settings, false, false, request.stop_epoch)
                    .map(|rev| pending_revision = Some(rev)),
                Command::Align => controller
                    .submit(status.settings, false, true, request.stop_epoch)
                    .map(|rev| pending_revision = Some(rev)),
                Command::Start(settings) => {
                    if let State::Error(e) = status.state {
                        Err(e)
                    } else {
                        controller
                            .submit(settings, true, false, request.stop_epoch)
                            .and_then(|rev| {
                                pending_revision = Some(rev);
                                if let Target::Audio {
                                    device_id,
                                    channels,
                                    pcm,
                                    ..
                                } = &target
                                    && stream.is_none()
                                {
                                    let config = device::Config {
                                        rate: status.nominal_sample_rate,
                                        channels: *channels,
                                        pcm: *pcm,
                                    };
                                    match device::open(device_id, config, execution.take().unwrap())
                                    {
                                        Ok(opened) => {
                                            device_metrics = Some(opened.1.clone());
                                            observed_notifications = 0;
                                            stream = Some(opened);
                                            callbacks = 0;
                                            last_callback = Instant::now();
                                        }
                                        Err(message) => {
                                            let _ = events.try_send(Event::Error(message));
                                            // Opening consumes execution even on failure. Never
                                            // replay its Start into a replacement stream.
                                            let (c, mut e) = rebuild(
                                                status,
                                                status.nominal_sample_rate,
                                                status.output_channels,
                                                status.settings,
                                                &stop,
                                            )
                                            .unwrap();
                                            e.fail(generator::Error::OutputStream);
                                            controller = c;
                                            observed_lost_reports = 0;
                                            execution = Some(e);
                                            status = execution.as_ref().unwrap().status();
                                            return Err(generator::Error::OutputStream);
                                        }
                                    }
                                }
                                Ok(())
                            })
                    }
                }
                Command::Attach(producer, metrics) => {
                    if target != Target::Internal {
                        metrics.failed.store(true, Ordering::Release);
                        metrics.ready.store(true, Ordering::Release);
                        let _ = events.try_send(Event::Error(
                            "Internal input requires Internal loopback output".into(),
                        ));
                        Ok(())
                    } else {
                        if let Some((_, old)) = &capture {
                            old.active.store(false, Ordering::Release);
                        }
                        let n = status.next_sample;
                        metrics
                            .nominal_sample_rate
                            .store(status.nominal_sample_rate as u64, Ordering::Relaxed);
                        metrics.first_sample.store(n, Ordering::Relaxed);
                        metrics.input_end.store(n, Ordering::Relaxed);
                        metrics.ready.store(true, Ordering::Release);
                        if capture.is_none() && status.state == State::Stopped {
                            clock = Instant::now();
                            fraction = 0.0;
                        }
                        capture = Some((producer, metrics));
                        Ok(())
                    }
                }
                Command::Shutdown | Command::Refresh => unreachable!(),
            };
            if is_control {
                error = result.err();
                if error.is_some() {
                    pending_revision = None;
                }
            }
        }
        if capture
            .as_ref()
            .is_some_and(|(_, m)| !m.active.load(Ordering::Acquire))
        {
            capture = None;
        }
        controller.flush();
        let now = Instant::now();
        if let Some(e) = &mut execution {
            e.begin_block();
            if target == Target::Internal {
                let elapsed = now.duration_since(clock).as_secs_f64();
                clock = now;
                let s = e.status();
                if capture.is_some() || !matches!(s.state, State::Stopped | State::Error(_)) {
                    fraction += elapsed * s.nominal_sample_rate as f64;
                    if fraction > s.nominal_sample_rate as f64 * 0.25 {
                        e.fail(generator::Error::ProducerSuspended);
                        error = Some(generator::Error::ProducerSuspended);
                        if let Some((_, m)) = &capture {
                            m.failed.store(true, Ordering::Release);
                        }
                        fraction = 0.0;
                    }
                    let count = fraction as usize;
                    fraction -= count as f64;
                    for _ in 0..count {
                        let condition = Condition::from_status(e.status());
                        match e.next_frame() {
                            Ok(frame) => {
                                if let Some((producer, m)) = &mut capture {
                                    let frame = Frame {
                                        sequence: frame.sequence,
                                        samples: [frame.samples[0], frame.samples[1]],
                                        condition,
                                        #[cfg(feature = "qa")]
                                        available_at: now,
                                    };
                                    if producer.push(frame).is_err() {
                                        m.dropped.fetch_add(1, Ordering::Relaxed);
                                    }
                                    m.input_end.store(frame.sequence + 1, Ordering::Release);
                                }
                            }
                            Err(failure) => {
                                error = Some(failure);
                                if let Some((_, m)) = &capture {
                                    m.failed.store(true, Ordering::Release);
                                }
                                break;
                            }
                        }
                    }
                }
            }
            e.end_block();
        }
        // Drain the bounded report queue before reducing to latest UI state.
        // Neither UI stalls nor feedback saturation remove manager evidence.
        for _ in 0..control::CAPACITY {
            let Some(report) = controller.pop_report() else {
                break;
            };
            history.losses(report.lost_reports.saturating_sub(observed_lost_reports), 0);
            observed_lost_reports = report.lost_reports;
            let report_error = match report.status.state {
                State::Error(e) => Some(e),
                _ => report.rejected.map(|r| r.error).or(error),
            };
            history.record(&target, report.status, report_error);
            status = report.status;
            acknowledged_stop = report.stop_epoch;
            if let Some(rejected) = report.rejected
                && pending_revision == Some(rejected.revision)
            {
                error = Some(rejected.error);
                pending_revision = None;
            }
        }
        if let Some((_, metrics)) = &stream {
            let count = metrics.callbacks.load(Ordering::Acquire);
            if count != callbacks {
                callbacks = count;
                last_callback = now;
            }
            let failure = stream_failure(
                metrics.failed.load(Ordering::Acquire),
                now.duration_since(last_callback),
                stop_started.map(|at| now.duration_since(at)),
                acknowledged_stop >= stop.load(Ordering::Acquire)
                    && matches!(status.state, State::Stopped | State::Error(_)),
            );
            if let Some(failure) = failure {
                // Release the stream first, then mark the last reported endpoint
                // invalid. A timeout cannot claim a completed fade or DAC time.
                stream.take();
                let (c, mut e) = rebuild(
                    status,
                    status.nominal_sample_rate,
                    status.output_channels,
                    status.settings,
                    &stop,
                )
                .unwrap();
                e.fail(failure);
                controller = c;
                observed_lost_reports = 0;
                execution = Some(e);
                status = execution.as_ref().unwrap().status();
                error = Some(failure);
                pending_revision = None;
                let _ = events.try_send(Event::Error(failure.to_string()));
            }
        }
        if !matches!(status.state, State::Stopped | State::Error(_)) || capture.is_some() {
            if activity.is_none() {
                activity = Some(crate::activity::Activity::new(
                    "MeasureLab signal generation",
                ));
            }
        } else {
            activity.take();
        }
        if let State::Error(e) = status.state {
            error = Some(e);
            pending_revision = None;
        }
        if let Some(m) = &device_metrics {
            let count = m.notifications.load(Ordering::Acquire);
            history.losses(0, count.saturating_sub(observed_notifications));
            observed_notifications = count;
        }
        history.record(&target, status, error);
        if pending_revision.is_none_or(|rev| status.revision >= rev) {
            acknowledged_request = acknowledged_request.max(pending_request);
        }
        if acknowledged_stop >= seen_stop
            && matches!(status.state, State::Stopped | State::Error(_))
        {
            stop_started = None;
        }
        let _ = feedback.push(Update {
            acknowledged_request,
            stop_epoch: acknowledged_stop,
            status,
            error,
            target: target.clone(),
            #[cfg(feature = "qa")]
            device_metrics: device_metrics.clone(),
        });
        if shutdown
            && (matches!(status.state, State::Stopped | State::Error(_))
                || stop_started.is_some_and(|at| now.duration_since(at) > STOP_TIMEOUT))
        {
            stream.take();
            if let Some(m) = &device_metrics {
                let count = m.notifications.load(Ordering::Acquire);
                history.losses(0, count.saturating_sub(observed_notifications));
            }
            return;
        }
        thread::sleep(Duration::from_millis(2));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn failure_is_latched_and_acknowledged_stop_still_needs_a_terminal_zero_frame() {
        assert_eq!(
            stream_failure(true, Duration::ZERO, None, true),
            Some(generator::Error::OutputStream)
        );
        assert_eq!(
            stream_failure(false, Duration::from_secs(3), None, true),
            Some(generator::Error::CallbackStalled)
        );
        assert_eq!(
            stream_failure(
                false,
                Duration::from_millis(510),
                Some(Duration::from_millis(510)),
                false
            ),
            Some(generator::Error::CallbackStalled)
        );
        assert_eq!(
            stream_failure(
                false,
                Duration::ZERO,
                Some(Duration::from_millis(510)),
                true
            ),
            None
        );
    }
}
