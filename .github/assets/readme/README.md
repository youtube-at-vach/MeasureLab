# Rust README screenshots

These are unedited screenshots of MeasureLab's Rust prototype, captured on macOS with the Metal renderer from application source at `db2d044dd7146a6d3cb3558bf25c9d78ae8e71e3`.

| Image | Input and view |
| --- | --- |
| `rust-workspace.png` | Synthetic QA fixtures; Scope, Spectrum, Spectrogram and XY; collapsed sidebar. The orange spectrogram band is an intentional input gap |
| `rust-scope-spectrum.png` | Synthetic QA fixtures with time cursors; Scope + Spectrum; hidden sidebar |
| `rust-lockin.png` | Software Loopback; experimental Lock-in R/θ display; 750 Hz REF, 0.0625 FS peak response, +30° phase |

The images show the interface and do not establish physical-device accuracy. Preserve the QA labels and the README captions when reusing them.

To refresh them, run these commands from the repository root on a desktop with a working GPU. Each capture opens the app briefly, writes `dist/ui-smoke.png` and exits. The commands copy each image before the next capture replaces that temporary file.

```sh
./scripts/cargo.sh build --release --locked --features qa

MEASURELAB_UI_SMOKE_SETTINGS=collapsed \
    target/release/measurelab --ui-smoke --new-instance
cp dist/ui-smoke.png .github/assets/readme/rust-workspace.png

MEASURELAB_UI_SMOKE_VIEW=pair MEASURELAB_UI_SMOKE_CURSORS=1 \
    MEASURELAB_UI_SMOKE_SETTINGS=hidden \
    target/release/measurelab --ui-smoke --new-instance
cp dist/ui-smoke.png .github/assets/readme/rust-scope-spectrum.png

MEASURELAB_UI_SMOKE_LOCKIN=polar \
    target/release/measurelab --ui-smoke --new-instance
cp dist/ui-smoke.png .github/assets/readme/rust-lockin.png
```

Update the source revision above after refreshing the images. The capture switches belong to the `qa` feature; normal users can try Software Loopback without it.
