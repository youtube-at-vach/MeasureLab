# Rust core段階導入の評価と再開

2026-10-04。[判断0037](../migration/decisions/0037-mig008-integrated-evaluation.md)に従い、
次の対象は現行Spectrum AnalyzerへのRust FFT/共有result接続評価。
Python bindingと製品切替は未実装。現在地は[進捗](../migration/status.md)を参照する。
Qt/QMLの両adapter・表示用core・初期probe・renderer試作と専用runnerを削除した。

## このworktreeで使う

リポジトリルートで導入済みのRustツールを有効にする。全fixture再verifyは不要。

```bash
export CARGO_HOME="$PWD/.tools/cargo"
export RUSTUP_HOME="$PWD/.tools/rustup"
export PATH="$CARGO_HOME/bin:$PATH"
export CARGO_BUILD_JOBS=4
export MACOSX_DEPLOYMENT_TARGET=13.0
```

Rust 1.98.1は[rust-toolchain.toml](rust-toolchain.toml)、依存版は[Cargo.lock](Cargo.lock)へ固定済み。
試作用Qt SDKとbuild用venvは削除済み。現行GUIはルートの`.venv/`を使う。

FFT/共有graphのbuild（変更した場合だけ）:

```bash
cargo +1.98.1 build --offline --locked --manifest-path native/Cargo.toml -p dsp-core -p graph-core
```

関連crateだけをtestする。Windows/ARM、長時間試験、MIG-008フローの再実行は今回の対象に含めない。

## 実装の入口

| 対象 | 実装・必要な手順 |
| --- | --- |
| f32音声/ID/queue | [audio-core](audio-core/src/lib.rs)、[共通入力](audio-core/src/backend.rs)、[CPAL](audio-probe/src/lib.rs)、[PortAudio](portaudio-input/src/lib.rs) |
| route | [実装](audio-core/src/dynamic_route.rs)、[配送・ack](dynamic-route.md) |
| 取得/履歴/Timebase | [取得owner](graph-core/src/acquisition.rs)、[履歴](graph-core/src/history.rs)、[時刻](graph-core/src/time.rs) |
| FFT/共有 | [DSP](dsp-core/src/lib.rs)、[共有graph](graph-core/src/lib.rs)、[参照fixture](../migration/fixtures/README.md) |
| filter | [stateと明示精度変換](graph-core/src/filter.rs)、[派生取得](graph-core/src/acquisition/derived.rs) |
| Trigger | [取得履歴からのcapture](graph-core/src/acquisition/trigger.rs) |
| 校正 | [ID対応校正/result](graph-core/src/result.rs) |
| 保存/読込み | [snapshot/worker](graph-core/src/export.rs)、[製品codec](product-codec.md)、[製品import](graph-core/src/product/import.rs) |

runnerの追加オプションは`./.venv/bin/python scripts/migration_<対象>.py --help`で確認する。
既存のcore/input runnerは対象変更の必要な条件だけ指定する。
CPAL/PortAudioは入力境界の既存実装として保持し、製品backend切替は行っていない。

## 文書とアーティファクト

基準/数値契約、固定fixture、core実装、既存比較の要約を保持する。
方針決定後に削除したQt/rendererコード・手順はGit履歴`edad0838`から取得できる。
MIG-008の未コミット差分の保存先は[進捗](../migration/status.md#方針決定後の整理)。
選んだ最終reportと関連失敗は`.migration-local/evidence/`にgzipで保存。
古いreport内のartifactパスは実施時の記録で、削除済み中間物の存在を保証しない。
再実行は現在のコードから新しい出力先へ行う。
