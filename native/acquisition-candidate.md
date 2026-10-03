# Acquisition queue / history / shared FFT candidate

MIG-005のinput.raw接続、2026-10-01。
[決定0014](../migration/decisions/0014-acquisition-history-shared-fft.md)と[進捗](../migration/status.md)を参照。
既存003-A/B/Cの入力・期待値・契約・許容差を変更しない。製品UI/音声engineへの変更ではない。

## デバイスなしの再検査

Rust環境の設定は[準備手順](README.md#このworktreeで使う)を参照する。

```bash
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p graph-core -p audio-core
cargo +1.98.1 clippy --offline --locked --manifest-path native/Cargo.toml -p graph-core -p audio-probe --all-targets -- -D warnings
./.venv/bin/python scripts/migration_audio_graph.py --report .migration-local/005-graph-new.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_audio_graph.py
```

runnerは新規reportを要求し、fixtureを更新しない。
4入力（4/8ch × f32/f64）をidentity/逆順の2bindingで取得queue→履歴→共有FFTへ通す。
callback相当の1/127/256/17 frameとpollの71 deliveryを独立に分割する。
各caseで全元bits/ChannelId/物理port/区間/unknown時刻、FFT評価1と同じallocationを検査する。
保存tokenだけで続行、最後の解除とstop、履歴失効後も保持したsnapshotが不変であることも確認する。
`--portable`はNumPy-only環境用で、source/hash/数値検査を維持する。

## BlackHole実取得

通常deviceはBlackHole 2ch／16ch。物理測定が必要な条件だけUAC-232を使う。

```bash
./.venv/bin/python scripts/migration_audio_virtual.py --virtual-device --output .migration-local/005-graph-blackhole-new
```

[既存音声比較](audio-boundary.md)の全sample誤差・port対応・mute・準備cancelに加えて、
CPALのanalysis_graphを検査する。入力取得と解析は同じqueue/worker経路。
N=1024、hop=512、symmetric Hann。2購読は同じraw FFT allocationを受け、全完成窓に対する評価は1回。
GUI通知相当の未読snapshot置換と取得gapは別に数える。
停止後はnodes/subscriptions/cache/in-flightが0で、Timebase原点と不確かさはunknownのまま。

raw input/output/manifest、各runのgraph件数とhashは新規出力先へ保存する。
短いloopback診断であり、長時間/定常性能、USB復帰・排他、物理clockの精度、他OSの合格ではない。
出力routeは開始時の固定設定。動的配送、全tap、Qt、製品save/校正統合は後続。

取得ownerの追加[Trigger capture API](trigger-capture.md)では履歴から過去窓を非消費で読み、
通常の最新位置/平均を変えずに不変resultを返す。保存入力で検証し、Qt/実入力の要求配送は後続とする。
