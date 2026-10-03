# Rust coreの評価用workspace

[評価計画](../guide/RUST_QML_MIGRATION_PLAN.md)に従い、現行Spectrum Analyzerへの
Rust FFT／共有result接続を次の対象とする。Python bindingと製品切替は未実装。
現在地とMIG-008の結果は[進捗](../migration/status.md)を参照する。
最初のPython境界、plan再利用と数値互換の差、短い計測は
[実装境界の調査結果](../guide/RUST_QML_MIGRATION_PLAN.md#実装境界の調査結果)にまとめる。

## buildと検証

このworktreeのRust 1.98.1をリポジトリルートから使う。

```bash
export CARGO_HOME="$PWD/.tools/cargo"
export RUSTUP_HOME="$PWD/.tools/rustup"
export PATH="$CARGO_HOME/bin:$PATH"
export CARGO_BUILD_JOBS=4
```

新しい環境では[rust-toolchain.toml](rust-toolchain.toml)のtoolchainを用意し、初回だけ
`cargo fetch --locked --manifest-path native/Cargo.toml`で依存を取得する。
このworktreeでは導入済み。依存版は[Cargo.lock](Cargo.lock)へ固定する。

```bash
cargo build --offline --locked --manifest-path native/Cargo.toml --workspace
cargo test --offline --locked --manifest-path native/Cargo.toml --workspace
cargo fmt --all --manifest-path native/Cargo.toml --check
cargo clippy --offline --locked --manifest-path native/Cargo.toml --workspace --all-targets -- -D warnings
```

開発中は変更したcrate・テストに絞る。DSPのintegration testは
[固定fixture](../migration/fixtures/README.md)の18条件をlibraryへ直接渡して比較し、期待値を生成し直さない。
[Native evaluation](../.github/workflows/native-evaluation.yml)は明示した手動実行だけ。
Qt SDK、CMake/Ninja、音声backend開発パッケージとPython検証用venvは不要。
現行GUI・Pythonの開発ツールはルートの`.venv/`を使う。

## 実装の入口

| crate | 役割 |
| --- | --- |
| [dsp-core](dsp-core/src/lib.rs) | f32/f64 FFT、窓・振幅・RMS・PSD。plan/scratchはAnalyzerが所有 |
| [graph-core](graph-core/src/lib.rs) | 同条件FFTの共有、不変result、履歴／取得／Timebase、Trigger、filter、校正、保存 |
| [audio-core](audio-core/src/lib.rs) | graphの取得境界で使うChannelId・世代・容量制限付きqueue |

Qt/QML・renderer・CPAL/PortAudio試作と評価CLIは削除済み。
保存codecのunit testは残す。製品とのPython境界・同条件性能・配布保証は未検証。
旧評価CLI専用のlegacy trace import adapterとmerged CSV読込は除去した。
snapshotのJSON/独立CSV+sidecar保存と再読込は保持する。
