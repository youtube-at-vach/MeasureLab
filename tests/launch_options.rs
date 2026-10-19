#![cfg(feature = "desktop")]

use std::process::Command;

#[test]
fn retired_usb_disconnect_qa_is_rejected_before_any_audio_or_ui_start() {
    for value in ["", "0", "1"] {
        let output = Command::new(env!("CARGO_BIN_EXE_measurelab"))
            .args(["--physical-lockin-smoke", "--input-device", "ZOOM UAC-232"])
            .env("MEASURELAB_PROFILE_GENERATOR_DISCONNECT", value)
            .env("MEASURELAB_PROFILE_GENERATOR_DEVICE", "ZOOM UAC-232")
            .env("MEASURELAB_PROFILE_SECONDS", "300")
            .output()
            .unwrap();
        assert!(!output.status.success());
        assert!(output.stdout.is_empty());
        assert!(
            String::from_utf8(output.stderr)
                .unwrap()
                .contains("Live USB disconnect QA is prohibited for physical device safety")
        );
    }
}

#[test]
fn help_exposes_internal_signals_only_in_qa_builds() {
    let output = Command::new(env!("CARGO_BIN_EXE_measurelab"))
        .arg("--help")
        .env_remove("MEASURELAB_PROFILE_SECONDS")
        .output()
        .unwrap();
    assert!(output.status.success());
    let help = String::from_utf8(output.stdout).unwrap();
    assert_eq!(help.contains("--demo"), cfg!(feature = "qa"));
    assert_eq!(help.contains("--ui-smoke"), cfg!(feature = "qa"));
    assert_eq!(help.contains("--lockin-smoke"), cfg!(feature = "qa"));
    assert_eq!(
        help.contains("--physical-lockin-smoke"),
        cfg!(feature = "qa")
    );
}

#[cfg(not(feature = "qa"))]
#[test]
fn normal_build_rejects_internal_signals_before_opening_ui() {
    for option in [
        "--demo",
        "--ui-smoke",
        "--lockin-smoke",
        "--physical-lockin-smoke",
    ] {
        let output = Command::new(env!("CARGO_BIN_EXE_measurelab"))
            .args([option, "--help"])
            .env_remove("MEASURELAB_PROFILE_SECONDS")
            .output()
            .unwrap();
        assert!(!output.status.success(), "{option} unexpectedly succeeded");
        let error = String::from_utf8(output.stderr).unwrap();
        assert!(error.contains(&format!("{option} requires --features qa")));
        assert!(output.stdout.is_empty());
    }
}

#[cfg(feature = "qa")]
#[test]
fn physical_qa_requires_explicit_supported_device_and_valid_duration() {
    for (arguments, seconds, expected) in [
        (
            vec!["--physical-lockin-smoke"],
            "1",
            "requires --input-device NAME",
        ),
        (
            vec![
                "--physical-lockin-smoke",
                "--input-device",
                "Built-in Output",
            ],
            "1",
            "restricted to ZOOM UAC-232",
        ),
        (
            vec!["--physical-lockin-smoke", "--input-device", "ZOOM UAC-232"],
            "0",
            "MEASURELAB_LOCKIN_SECONDS must be 1–3600",
        ),
    ] {
        let output = Command::new(env!("CARGO_BIN_EXE_measurelab"))
            .args(arguments)
            .arg("--new-instance")
            .env_remove("MEASURELAB_PROFILE_SECONDS")
            .env("MEASURELAB_LOCKIN_SECONDS", seconds)
            .output()
            .unwrap();
        assert!(!output.status.success());
        assert!(String::from_utf8(output.stderr).unwrap().contains(expected));
    }
}

#[cfg(feature = "qa")]
#[test]
fn lockin_qa_rejects_physical_output_and_invalid_duration_without_opening_ui() {
    for (device, seconds, expected) in [
        ("Built-in Output", "1", "Lock-in QA requires BlackHole"),
        (
            "BlackHole 2ch",
            "0",
            "MEASURELAB_LOCKIN_SECONDS must be 1–3600",
        ),
    ] {
        let output = Command::new(env!("CARGO_BIN_EXE_measurelab"))
            .args(["--lockin-smoke", "--input-device", device, "--new-instance"])
            .env_remove("MEASURELAB_PROFILE_SECONDS")
            .env("MEASURELAB_LOCKIN_SECONDS", seconds)
            .output()
            .unwrap();
        assert!(!output.status.success());
        assert!(String::from_utf8(output.stderr).unwrap().contains(expected));
    }
}
