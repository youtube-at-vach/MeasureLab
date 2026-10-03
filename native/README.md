# Native評価の実装と再開

2026-10-04。[MIG-008の計画](../guide/RUST_QML_MIGRATION_PLAN.md)と[進捗](../migration/status.md)が入口。
現在のmacOS Intel環境と既存コードを再利用する。Windows・ARMはMIG-008後、長時間試験は不要。

## このworktreeで使う

リポジトリルートで導入済みのツールを有効にする。再導入・Hello world・全fixture再verifyは不要。

```bash
export CARGO_HOME="$PWD/.tools/cargo"
export RUSTUP_HOME="$PWD/.tools/rustup"
export PATH="$CARGO_HOME/bin:$PWD/.tools/build-venv/bin:$PATH"
export QMAKE="$PWD/.tools/qt/6.11.2/macos/bin/qmake"
export CARGO_BUILD_JOBS=4
export MACOSX_DEPLOYMENT_TARGET=13.0
export DYLD_FRAMEWORK_PATH="$PWD/.tools/qt/6.11.2/macos/lib"
```

Rust 1.98.1は[rust-toolchain.toml](rust-toolchain.toml)、Qt 6.11.2は[qt-sdk.toml](qt-sdk.toml)、
依存版は[Cargo.lock](Cargo.lock)へ固定済み。
Qt SDKの環境変数はPython参照版の別processへ引き継がない。

主経路のbuild（変更した場合だけ）:

```bash
cargo +1.98.1 build --offline --locked --manifest-path native/Cargo.toml -p cxxqt-display -p graph-core
```

関連crate/featureだけをtestする。Qt Bridgeのbuildや全workspace再検査は対象変更に必要な場合に行う。

## 実装の入口

| 対象 | 実装・必要な手順 |
| --- | --- |
| f32音声/ID/queue | [audio-core](audio-core/src/lib.rs)、[共通入力](audio-core/src/backend.rs)、[CPAL](audio-probe/src/lib.rs)、[PortAudio](portaudio-input/src/lib.rs) |
| route | [実装](audio-core/src/dynamic_route.rs)、[配送・ack](dynamic-route.md) |
| 取得/履歴/Timebase | [取得owner](graph-core/src/acquisition.rs)、[履歴](graph-core/src/history.rs)、[時刻](graph-core/src/time.rs) |
| FFT/共有 | [DSP](dsp-core/src/lib.rs)、[共有graph](graph-core/src/lib.rs)、[参照fixture](../migration/fixtures/README.md) |
| filter | [stateと明示精度変換](graph-core/src/filter.rs)、[派生取得](graph-core/src/acquisition/derived.rs)、[固定filter/Qt](filter-qt.md) |
| 表示/Trigger | [BlackHole表示](live-display.md)、[Qt接続](display-core/src/lib.rs)、[Trigger](display-core/src/trigger.rs)、[QML](qml/Display.qml) |
| 校正 | [result](graph-core/src/result.rs)、[Qtの編集・適用](calibration-edit.md) |
| 保存/読込み | [snapshot/worker](graph-core/src/export.rs)、[製品codec](product-codec.md)、[Qt保存](qt-save.md)、[製品import](graph-core/src/product/import.rs) |
| GUI初期probe | [Qt環境と起動](qt-probe.md)。模擬workerの結果を統合フローの成功に置き換えない |

runnerの追加オプションは`./.venv/bin/python scripts/migration_<対象>.py --help`で確認する。
既存の全条件runnerは対象変更の必要な条件だけ指定する。
通常の音声確認はBlackHole 2ch。UAC-232や別OSの追加試験をMIG-008の前提にしない。

## 文書とアーティファクト

試作ごとの重複手順書・決定記録・詳細な進捗履歴は整理した。
基準/数値契約、固定fixture、実装・上表の操作手順、既存比較の要約を保持する。
削除した文書の元内容はGit履歴の`1bc1e21c`から取得できる。
選んだ最終reportと関連失敗は`.migration-local/evidence/`にgzipで保存。
古いreport内のartifactパスは実施時の記録で、削除済み中間物の存在を保証しない。
再実行は現在のコードから新しい出力先へ行う。
