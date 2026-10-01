use super::*;
use crate::tests::{request, wait};

fn submission(format: &IoFormat, revision: u64, start: u64, n: usize) -> String {
    json!({"revision": revision, "request": {"request_id": format!("request.{revision}"),
    "pre": n / 2, "post": n - n / 2, "event": {
        "id": format!("event.{revision}"), "stream_id": format.stream_id,
        "generation": format.generation, "timebase_id": format.timebase_id,
        "sample": {"numerator": (start + n as u64 / 2) * 2 + 1, "denominator": 2},
        "source": "test.manual", "kind": "edge", "polarity": "rising",
        "condition_revision": "test.v1", "validity": [], "received_host_seconds": null
    }}})
    .to_string()
}
fn status(s: &Snapshot, name: &str) -> bool {
    s.trigger.as_ref().is_some_and(|r| r.status == name)
}
#[test]
fn threaded_pending_explicit_retry_shared_hold_release_and_restart() {
    for precision in [Precision::F32, Precision::F64] {
        let mut config = request(precision, 4, false);
        let path = config.input.clone().unwrap();
        let mut display = Display::with_request(config.clone());
        display.subscribe();
        display.subscribe();
        config.format.generation = display.start(false, |_| true).unwrap();
        // A request can queue during preparation; the first query has no acquired samples.
        assert!(display.request_trigger(&submission(&config.format, 1, 0, config.n)));
        assert!(!display.request_trigger(&submission(&config.format, 2, 0, config.n))); // full
        wait(&display, |s| status(s, "pending") && s.produced >= 1);
        let pending = display.peek().trigger.unwrap();
        assert!(pending.frame.is_none());
        assert_eq!(
            serde_json::from_str::<Value>(&pending.encoded).unwrap()["frame"],
            Value::Null
        );
        assert!(display.retry_trigger(config.format.generation, 1));
        wait(&display, |s| status(s, "complete"));
        let held = display.peek().trigger.unwrap();
        let document = held.frame.as_ref().unwrap().result.to_value();
        let before = display.peek().produced;
        wait(&display, |s| s.produced >= before + 4);
        let other_view = display.peek().trigger.unwrap();
        assert!(Arc::ptr_eq(&held, &other_view));
        assert!(!display.retry_trigger(config.format.generation, 1));
        assert!(!display.release_trigger(config.format.generation + 1, 1));
        assert!(display.release_trigger(config.format.generation, 1));
        assert!(!display.release_trigger(config.format.generation, 1));
        assert!(!display.request_trigger(&submission(&config.format, 1, 0, config.n))); // old revision
        wait(&display, |s| s.produced > before + 4);
        display.shutdown();
        assert!(display.peek().reclaimed);
        let generation = display.start(false, |_| true).unwrap();
        assert!(display.peek().trigger.is_none());
        assert!(!display.request_trigger(&submission(&config.format, 2, 0, config.n))); // old generation
        assert!(!display.retry_trigger(config.format.generation, 1));
        wait(&display, |s| s.produced >= 1 && s.generation == generation);
        display.shutdown();
        assert_eq!(document, held.frame.as_ref().unwrap().result.to_value());
        std::fs::remove_file(path).unwrap();
    }
}
#[test]
fn release_supersedes_queued_read_and_stop_cancels_uncompleted_request() {
    let mut config = request(Precision::F64, 4, false);
    let path = config.input.clone().unwrap();
    let mut display = Display::with_request(config.clone());
    display.subscribe();
    config.format.generation = display.start(false, |_| true).unwrap();
    assert!(display.request_trigger(&submission(&config.format, 1, 0, config.n)));
    assert!(display.release_trigger(config.format.generation, 1));
    wait(&display, |s| s.produced >= 2);
    assert!(status(&display.peek(), "released"));
    assert!(display.request_trigger(&submission(&config.format, 2, 1_000_000, config.n)));
    display.shutdown();
    assert!(status(&display.peek(), "cancelled"));
    assert!(display.peek().trigger.unwrap().frame.is_none());
    std::fs::remove_file(path).unwrap();
}
#[test]
fn malformed_event_reports_error_without_failing_acquisition() {
    let mut config = request(Precision::F64, 4, false);
    let path = config.input.clone().unwrap();
    let mut display = Display::with_request(config.clone());
    display.subscribe();
    config.format.generation = display.start(false, |_| true).unwrap();
    assert!(!display.request_trigger("{}"));
    assert!(!display.request_trigger(&"x".repeat(MAX_REQUEST_BYTES + 1)));
    let mut value: Value =
        serde_json::from_str(&submission(&config.format, 1, 0, config.n)).unwrap();
    value["request"]["event"]["sample"]["denominator"] = json!(0);
    assert!(display.request_trigger(&value.to_string()));
    wait(&display, |s| status(s, "error") && s.produced >= 2);
    let s = display.peek();
    assert_eq!(s.state, State::Running);
    assert!(s.trigger.unwrap().frame.is_none());
    display.shutdown();
    std::fs::remove_file(path).unwrap();
}
