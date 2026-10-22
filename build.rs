fn main() {
    // rust-i18n discovers new/deleted nested catalogs at macro expansion time.
    // Track the directory too, so a YAML-only change always reruns expansion.
    if std::env::var_os("CARGO_FEATURE_DESKTOP").is_some() {
        println!("cargo:rerun-if-changed=locales");
        println!("cargo:rerun-if-changed=i18n/source-hashes.json");
        println!("cargo:rerun-if-changed=tests/fixtures/i18n");
    }
    println!("cargo:rerun-if-changed=packaging/windows/app_icon.ico");
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows")
        && std::env::var_os("CARGO_FEATURE_DESKTOP").is_some()
    {
        winresource::WindowsResource::new()
            .set_icon("packaging/windows/app_icon.ico")
            .set("ProductName", "MeasureLab")
            .set("FileDescription", "MeasureLab audio measurement workspace")
            .set("OriginalFilename", "measurelab.exe")
            .set(
                "LegalCopyright",
                "Released into the public domain under The Unlicense",
            )
            .compile_for("measurelab")
            .expect("Windows resources require the Windows SDK (MSVC) or windres (GNU)");
    }
}
