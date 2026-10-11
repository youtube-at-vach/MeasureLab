#![cfg(feature = "desktop")]

use std::process::Command;

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
}

#[cfg(not(feature = "qa"))]
#[test]
fn normal_build_rejects_internal_signals_before_opening_ui() {
    for option in ["--demo", "--ui-smoke"] {
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
