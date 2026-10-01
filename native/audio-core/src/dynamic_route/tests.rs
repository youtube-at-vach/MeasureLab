use super::*;

fn route(revision: &str, gains: Vec<Vec<f64>>) -> Route {
    Route {
        inputs: vec!["b".into(), "a".into()],
        outputs: vec!["x".into(), "y".into(), "z".into()],
        gains,
        revision: revision.into(),
    }
}
fn initial() -> Route {
    route("initial", vec![vec![0., 1.], vec![1., 0.], vec![0., 0.]])
}
fn changed() -> Route {
    route("changed", vec![vec![1., 0.], vec![0.5, 0.5], vec![0., -1.]])
}
fn pair() -> (RouteController, RouteCallback) {
    route_mailbox(vec!["a".into(), "b".into()], initial(), 7).unwrap()
}

#[test]
fn applies_at_next_boundary_and_preserves_published_blocks() {
    let (mut ctl, mut cb) = pair();
    assert_eq!(ctl.publish(&changed(), 7, 3), Ok(1));
    let mut first = [0.; 6];
    let block = cb.process_block(0, &[1., 3., 2., 4.], &mut first).unwrap();
    assert_eq!(first, [1., 3., 0., 2., 4., 0.]);
    assert_eq!(block.sequence, 0);
    let mut out = [0.; 6];
    cb.process_block(2, &[1., 3., 2., 4.], &mut out).unwrap();
    assert!(ctl.take_event().is_none());
    let applied = cb.process_block(4, &[1., 3., 2., 4.], &mut out).unwrap();
    assert_eq!(out, [3., 2., -1., 4., 3., -2.]);
    assert_eq!(applied.interval, [4, 6]);
    assert_eq!(applied.sequence, 1);
    assert_eq!(
        ctl.take_event(),
        Some(RouteEvent {
            generation: 7,
            sequence: 1,
            revision: "changed".into(),
            requested_sample: 3,
            applied_sample: Some(4),
            status: RouteStatus::Applied,
        })
    );
    assert!(ctl.take_event().is_none());
    drop(cb);
    assert_eq!(block.sequence, 0);
    assert_eq!(first, [1., 3., 0., 2., 4., 0.]);
}

#[test]
fn late_request_and_slow_ack_do_not_block_callback() {
    let (mut ctl, mut cb) = pair();
    let mut out = [0.; 3];
    cb.process_block(0, &[1., 3.], &mut out).unwrap();
    ctl.publish(&changed(), 7, 0).unwrap();
    for start in 1..100 {
        assert_eq!(
            cb.process_block(start, &[1., 3.], &mut out)
                .unwrap()
                .sequence,
            1
        );
    }
    assert_eq!(ctl.publish(&initial(), 7, 100), Err("route_busy"));
    assert_eq!(ctl.rendered_through(), 100);
    assert_eq!(ctl.take_event().unwrap().applied_sample, Some(1));
    assert_eq!(ctl.publish(&initial(), 7, 100), Ok(2));
    assert_eq!(
        cb.process_block(100, &[1., 3.], &mut out).unwrap().sequence,
        2
    );
}

#[test]
fn rejected_commands_preserve_route_position_and_next_sequence() {
    let (mut ctl, mut cb) = pair();
    assert_eq!(ctl.publish(&changed(), 6, 0), Err("route_generation"));
    let mut bad = changed();
    bad.gains[0][0] = f64::NAN;
    assert_eq!(ctl.publish(&bad, 7, 0), Err("nonfinite_gain"));
    bad = changed();
    bad.inputs[0] = "unknown".into();
    assert_eq!(ctl.publish(&bad, 7, 0), Err("unknown_or_duplicate_input"));
    bad = changed();
    bad.outputs.swap(0, 1);
    assert_eq!(ctl.publish(&bad, 7, 0), Err("route_output_binding"));
    bad.outputs[0] = bad.outputs[1].clone();
    assert_eq!(ctl.publish(&bad, 7, 0), Err("duplicate_or_empty_output"));
    bad = changed();
    bad.gains[0].pop();
    assert_eq!(ctl.publish(&bad, 7, 0), Err("gain_shape"));
    assert_eq!(
        ctl.publish(&initial(), 7, 0),
        Err("route_revision_unchanged")
    );
    let mut out = [0.; 3];
    assert_eq!(
        cb.process_block(0, &[1., 3.], &mut out).unwrap().sequence,
        0
    );
    assert_eq!(out, [1., 3., 0.]);
    assert_eq!(ctl.publish(&changed(), 7, 10), Ok(1));
    for start in 1..=10 {
        cb.process_block(start, &[1., 3.], &mut out).unwrap();
    }
    ctl.take_event().unwrap();
    assert_eq!(ctl.publish(&initial(), 7, 9), Err("route_request_order"));
    assert_eq!(ctl.publish(&initial(), 7, 10), Ok(2));
}

#[test]
fn invalid_blocks_do_not_apply_pending_route_or_touch_output() {
    let (mut ctl, mut cb) = pair();
    ctl.publish(&changed(), 7, 0).unwrap();
    let mut out = [99.; 3];
    for (start, values, expected) in [
        (0, vec![], "frame_shape"),
        (0, vec![1.], "frame_shape"),
        (0, vec![0.; (MAX_CALLBACK_FRAMES + 1) * 2], "frame_shape"),
        (1, vec![1., 3.], "output_position"),
    ] {
        assert_eq!(cb.process_block(start, &values, &mut out), Err(expected));
        assert_eq!(out, [99.; 3]);
        assert!(ctl.take_event().is_none());
        assert_eq!(ctl.rendered_through(), 0);
    }
    assert_eq!(
        cb.process_block(0, &[1., 3.], &mut out).unwrap().sequence,
        1
    );
    assert_eq!(ctl.take_event().unwrap().applied_sample, Some(0));
    cb.next_sample = u64::MAX;
    assert_eq!(
        cb.process_block(u64::MAX, &[1., 3.], &mut out),
        Err("sample_overflow")
    );
}

#[test]
fn preparing_cancel_and_stop_return_pending_once_and_reject_reuse() {
    let (mut ctl, mut cb) = pair();
    ctl.publish(&changed(), 7, 100).unwrap();
    ctl.close();
    ctl.close();
    let mut out = [99.; 3];
    assert_eq!(
        cb.process_block(0, &[1., 3.], &mut out),
        Err("route_closed")
    );
    assert_eq!(out, [99.; 3]);
    assert!(ctl.take_event().is_none());
    drop(cb);
    assert_eq!(ctl.take_event().unwrap().status, RouteStatus::Cancelled);
    assert!(ctl.take_event().is_none());
    assert_eq!(ctl.publish(&changed(), 7, 100), Err("route_closed"));
    let (mut restarted, mut cb) =
        route_mailbox(vec!["a".into(), "b".into()], initial(), 8).unwrap();
    assert_eq!(restarted.publish(&changed(), 7, 0), Err("route_generation"));
    assert_eq!(
        cb.process_block(0, &[1., 3.], &mut out).unwrap().sequence,
        0
    );
    assert_eq!(out, [1., 3., 0.]);
}

#[test]
fn callback_drop_distinguishes_applied_from_unapplied_command() {
    for apply in [false, true] {
        let (mut ctl, mut cb) = pair();
        ctl.publish(&changed(), 7, 0).unwrap();
        if apply {
            cb.process_block(0, &[1., 3.], &mut [0.; 3]).unwrap();
        }
        drop(cb);
        let event = ctl.take_event().unwrap();
        assert_eq!(event.applied_sample, if apply { Some(0) } else { None });
        assert_eq!(
            event.status,
            if apply {
                RouteStatus::Applied
            } else {
                RouteStatus::Cancelled
            }
        );
        assert_eq!(ctl.publish(&initial(), 7, 1), Err("route_closed"));
    }
    let (ctl, mut cb) = pair();
    drop(ctl);
    assert_eq!(
        cb.process_block(0, &[1., 3.], &mut [0.; 3]),
        Err("route_closed")
    );
}

#[test]
fn reduction_order_zero_terms_and_unclipped_sum_match_compiled_route() {
    let known = vec!["a".into(), "b".into(), "c".into()];
    let route = Route {
        inputs: vec!["c".into(), "a".into(), "b".into()],
        outputs: vec!["x".into(), "y".into()],
        gains: vec![vec![1., 1., 1.], vec![0., 2., 0.]],
        revision: "r".into(),
    };
    let static_route = route.compile(&known).unwrap();
    let (_ctl, mut cb) = route_mailbox(known, route, 0).unwrap();
    for (start, input) in [[1e20, -1e20, 3.], [2., f32::NAN, f32::NAN]]
        .iter()
        .enumerate()
    {
        let mut expected = [0.; 2];
        let mut observed = [0.; 2];
        static_route.process_into(input, &mut expected).unwrap();
        cb.process_block(start as u64, input, &mut observed)
            .unwrap();
        assert_eq!(observed.map(f32::to_bits), expected.map(f32::to_bits));
    }
}

#[test]
fn maximum_channel_count_and_callback_frames_are_supported() {
    let ids: Vec<_> = (0..MAX_CHANNELS).map(|i| i.to_string()).collect();
    let mut route = Route {
        inputs: ids.clone(),
        outputs: ids.clone(),
        gains: vec![vec![0.; MAX_CHANNELS]; MAX_CHANNELS],
        revision: "r0".into(),
    };
    for (i, row) in route.gains.iter_mut().enumerate() {
        row[i] = 1.;
    }
    let (mut ctl, mut cb) = route_mailbox(ids, route.clone(), 0).unwrap();
    route.revision = "r1".into();
    for row in &mut route.gains {
        row.reverse();
    }
    ctl.publish(&route, 0, 0).unwrap();
    let input: Vec<_> = (0..MAX_CALLBACK_FRAMES * MAX_CHANNELS)
        .map(|i| (i % MAX_CHANNELS) as f32)
        .collect();
    let mut out = vec![0.; input.len()];
    cb.process_block(0, &input, &mut out).unwrap();
    for row in out.as_chunks::<MAX_CHANNELS>().0 {
        let expected: [f32; MAX_CHANNELS] = std::array::from_fn(|i| (MAX_CHANNELS - 1 - i) as f32);
        assert_eq!(*row, expected);
    }
}

#[test]
fn concurrent_delivery_never_tears_matrix_revision_or_ack() {
    let (mut ctl, mut cb) = pair();
    let thread = std::thread::spawn(move || {
        let mut start = 0;
        loop {
            let mut out = [0.; 3];
            match cb.process_block(start, &[1., 3.], &mut out) {
                Ok(stamp) => {
                    if stamp.sequence > 0 {
                        let value = stamp.sequence as f32;
                        assert_eq!(out, [value, value * 3., value * -2.]);
                    }
                    start += 1;
                }
                Err("route_closed") => break,
                other => panic!("{other:?}"),
            }
            std::thread::yield_now();
        }
        start
    });
    for sequence in 1..=2000 {
        let value = sequence as f64;
        let next = route(
            &format!("r{sequence}"),
            vec![vec![0., value], vec![value, 0.], vec![0., -2. * value]],
        );
        assert_eq!(ctl.publish(&next, 7, 0), Ok(sequence));
        loop {
            if let Some(event) = ctl.take_event() {
                assert_eq!(event.sequence, sequence);
                assert_eq!(event.status, RouteStatus::Applied);
                assert_eq!(event.revision, format!("r{sequence}"));
                break;
            }
            std::thread::yield_now();
        }
    }
    ctl.close();
    assert!(thread.join().unwrap() >= 2000);
}
