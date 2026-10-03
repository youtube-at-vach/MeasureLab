use super::*;
use audio_core::Delivery;
use std::sync::atomic::{AtomicI32, AtomicUsize};

fn binding() -> InputBinding {
    InputBinding {
        backend: Backend::PortAudio,
        device: "explicit".into(),
        device_channels: 4,
        sample_format: SampleFormat::F32,
        format: IoFormat {
            stream_id: "stream".into(),
            generation: 7,
            timebase_id: "clock".into(),
            clock_domain: "portaudio.device:explicit".into(),
            rate: [48000, 1],
            input_ids: vec!["z".into(), "a".into()],
            input_ports: vec![3, 0],
            output_ids: vec![],
            output_ports: vec![],
        },
    }
}
fn context() -> (Box<Context>, Consumer) {
    let (writer, rx) = binding().queue::<f32>(4).unwrap();
    (
        Box::new(Context {
            writer,
            channels: 4,
            counters: Arc::new(Counters::default()),
        }),
        rx,
    )
}
#[test]
fn callback_keeps_bits_position_and_unknown_clock() {
    let (mut context, mut rx) = context();
    let values = [f32::from_bits(0x3f800001), -0., 0., f32::MIN_POSITIVE];
    // SAFETY: exact callback context, f32 buffer and frame count, all retained here.
    assert_eq!(
        unsafe {
            callback(
                values.as_ptr().cast(),
                ptr::null_mut(),
                1,
                ptr::null(),
                0,
                ptr::from_mut(context.as_mut()).cast(),
            )
        },
        0
    );
    let Some(Delivery::Frame {
        sample,
        values: captured,
        seconds,
        flags,
    }) = rx.take()
    else {
        panic!("frame");
    };
    assert_eq!(sample, 0);
    assert_eq!(seconds, None);
    assert_eq!(flags, 0);
    assert_eq!(
        captured.iter().map(|v| v.to_bits()).collect::<Vec<_>>(),
        values.iter().map(|v| v.to_bits()).collect::<Vec<_>>()
    );
    assert_eq!(context.writer.next_sample(), 1);
}
#[test]
fn xrun_null_and_oversized_blocks_abort_before_publishing() {
    for (frames, flags) in [
        (1, 1),
        (1, 2),
        (1, 4),
        (1, 16),
        (1, 64),
        (0, 0),
        (1, 0),
        (8193, 0),
    ] {
        let (mut context, mut rx) = context();
        // SAFETY: context is valid; bad input shape/pointer is rejected before access.
        assert_eq!(
            unsafe {
                callback(
                    ptr::null(),
                    ptr::null_mut(),
                    frames,
                    ptr::null(),
                    flags,
                    ptr::from_mut(context.as_mut()).cast(),
                )
            },
            2
        );
        assert!(rx.take().is_none());
        assert_eq!(context.writer.next_sample(), 0);
        assert_eq!(context.counters.xruns.load(Relaxed), u64::from(flags != 0));
        assert_eq!(
            context.counters.rejected.load(Relaxed),
            u64::from(flags == 0)
        );
    }
}
#[test]
fn configuration_rejects_clock_precision_ports_and_relative_library_before_load() {
    let mut b = binding();
    validate(
        Path::new("/missing/trusted-portaudio"),
        &b.device,
        4,
        &b.format,
    )
    .unwrap();
    assert!(validate(Path::new("relative"), &b.device, 4, &b.format).is_err());
    b.format.clock_domain = "cpal.device:explicit".into();
    assert!(validate(Path::new("/missing"), &b.device, 4, &b.format).is_err());
    b = binding();
    b.format.input_ports = vec![3, 3];
    assert!(validate(Path::new("/missing"), &b.device, 4, &b.format).is_err());
    b = binding();
    b.format.rate = [44100, 1];
    assert!(validate(Path::new("/missing"), &b.device, 4, &b.format).is_err());
}

static MOCKS: Mutex<()> = Mutex::new(());
static LEASE: Mutex<()> = Mutex::new(());
static ABORT: AtomicI32 = AtomicI32::new(0);
static CLOSE: AtomicI32 = AtomicI32::new(0);
static TERMINATE: AtomicI32 = AtomicI32::new(0);
static CLOSE_CALLS: AtomicUsize = AtomicUsize::new(0);
static TERMINATE_CALLS: AtomicUsize = AtomicUsize::new(0);
unsafe extern "C" fn zero() -> c_int {
    0
}
unsafe extern "C" fn terminate() -> c_int {
    TERMINATE_CALLS.fetch_add(1, Relaxed);
    TERMINATE.load(Relaxed)
}
unsafe extern "C" fn device(_: c_int) -> *const ffi::DeviceInfo {
    ptr::null()
}
unsafe extern "C" fn supported(
    _: *const ffi::Parameters,
    _: *const ffi::Parameters,
    _: f64,
) -> c_int {
    0
}
unsafe extern "C" fn open(
    _: *mut *mut c_void,
    _: *const ffi::Parameters,
    _: *const ffi::Parameters,
    _: f64,
    _: c_ulong,
    _: c_ulong,
    _: ffi::Callback,
    _: *mut c_void,
) -> c_int {
    0
}
unsafe extern "C" fn start(_: *mut c_void) -> c_int {
    -9999
}
unsafe extern "C" fn abort(_: *mut c_void) -> c_int {
    ABORT.load(Relaxed)
}
unsafe extern "C" fn close(_: *mut c_void) -> c_int {
    CLOSE_CALLS.fetch_add(1, Relaxed);
    CLOSE.load(Relaxed)
}
unsafe extern "C" fn active(_: *mut c_void) -> c_int {
    1
}
unsafe extern "C" fn info(_: *mut c_void) -> *const ffi::StreamInfo {
    ptr::null()
}
#[cfg(target_os = "macos")]
unsafe extern "C" fn mac_setup(_: *mut ffi::MacInfo, _: c_ulong) {}
fn mock_input(started: bool) -> PortAudioInput {
    let (context, _) = context();
    let counters = context.counters.clone();
    ABORT.store(0, Relaxed);
    CLOSE.store(0, Relaxed);
    TERMINATE.store(0, Relaxed);
    CLOSE_CALLS.store(0, Relaxed);
    TERMINATE_CALLS.store(0, Relaxed);
    PortAudioInput {
        session: Some(Session {
            api: ffi::Api {
                version: 19 << 16,
                _library: None,
                initialize: zero,
                terminate,
                device_count: zero,
                device_info: device,
                supported,
                open,
                start,
                abort,
                close,
                active,
                info,
                #[cfg(target_os = "macos")]
                mac_setup,
            },
            _owner: LEASE.lock().unwrap(),
            context,
            stream: ptr::dangling_mut(),
            started,
        }),
        counters,
        terminated: false,
        version: 19 << 16,
        reported_rate: None,
        stream_info_version: None,
    }
}
#[test]
fn close_and_terminate_release_context_even_after_abort_error() {
    let _serial = MOCKS.lock().unwrap();
    let mut input = mock_input(true);
    ABORT.store(-9999, Relaxed);
    assert!(input.stop().is_err());
    assert!(input.session.is_none());
    assert!(input.terminated);
    assert_eq!(CLOSE_CALLS.load(Relaxed), 1);
    assert_eq!(TERMINATE_CALLS.load(Relaxed), 1);
    assert_eq!(Arc::strong_count(&input.counters), 1);
    input.stop().unwrap();
    assert_eq!(TERMINATE_CALLS.load(Relaxed), 1);
}
#[test]
fn failed_close_retains_context_and_lease_until_successful_retry() {
    let _serial = MOCKS.lock().unwrap();
    let mut input = mock_input(true);
    CLOSE.store(-9999, Relaxed);
    assert!(input.stop().is_err());
    assert!(!input.report()["closed"].as_bool().unwrap());
    assert_eq!(TERMINATE_CALLS.load(Relaxed), 0);
    assert_eq!(Arc::strong_count(&input.counters), 2);
    assert!(LEASE.try_lock().is_err());
    CLOSE.store(0, Relaxed);
    input.stop().unwrap();
    assert_eq!(Arc::strong_count(&input.counters), 1);
    assert!(LEASE.try_lock().is_ok());
}
#[test]
fn start_failure_drop_closes_and_terminates_without_callback_or_device() {
    let _serial = MOCKS.lock().unwrap();
    let mut input = mock_input(false);
    assert!(input.start().is_err());
    let weak = Arc::downgrade(&input.counters);
    drop(input);
    assert!(weak.upgrade().is_none());
    assert_eq!(CLOSE_CALLS.load(Relaxed), 1);
    assert_eq!(TERMINATE_CALLS.load(Relaxed), 1);
}
#[test]
fn unavailable_device_and_termination_error_do_not_claim_success() {
    let _serial = MOCKS.lock().unwrap();
    let mut input = mock_input(false);
    input.session.as_mut().unwrap().stream = ptr::null_mut();
    assert_eq!(
        input.open_stream("missing", 4).unwrap_err(),
        "live_exact_device_not_unique"
    );
    TERMINATE.store(-9999, Relaxed);
    assert!(input.stop().is_err());
    assert!(!input.terminated);
    assert_eq!(CLOSE_CALLS.load(Relaxed), 0);
    assert_eq!(TERMINATE_CALLS.load(Relaxed), 1);
    assert!(LEASE.try_lock().is_err());
    assert!(input.session.is_some());
    TERMINATE.store(0, Relaxed);
    input.stop().unwrap();
    assert!(LEASE.try_lock().is_ok());
}
