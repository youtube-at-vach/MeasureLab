# History / Timebase candidate

MIG-006-C、2026-09-30。[コア契約v0.1](../migration/contracts/core.md#triggerと履歴)と
[AC08/09](../migration/contracts/acceptance.md)を`graph-core::history`と`graph-core::time`で検証する。
依存ライブラリと保存fixtureは追加・変更せず、006-Bの共有FFTへowned窓を渡す。

## 履歴と読取り

`History`は一つのStream/generationを解析worker側で所有する。
frame-major f32/f64 blockを任意のchunk長で追記し、絶対sample位置を保持する。
capacityはframe数。最新取得位置からcapacityより古いframeを捨て、残るblockを正確に切り詰める。
大きな入力のallocationを保持せず、tailを新しいowned配列へコピーする。
保持するframeの合計、numeric bytes、validity span数に上限を設定する。
block数は保持frame数以下。numeric bytesはmetadata、allocator、外部snapshot、process RSSの上限ではない。

開始前、保持期限切れ、取得gapは正確な半開区間で返す。
将来のsampleはpending、既取得区間の欠落はgap。両方ある場合はgapとし、両区間を残す。
`HistoryReader`ごとにcursorを持ち、snapshot読取り成功だけでそのreaderの位置を進める。
gap/pendingでcursorを黙って移動せず、呼出し側がseek/再試行を選ぶ。
trigger queryは非消費で、整数trigger kなら`[k-pre,k+post)`、分数triggerはfloorと残差を保存する。
受信host時刻はsample位置の計算に使わず、TriggerEventの診断項目に分ける。
読取り済みのowned `Arc<SignalBlock>`は追記・eviction・restart後も不変。

重複/逆順、古い世代、同世代のchannel順/precision/Timebase変更は追記前に拒否する。
route/filter/校正revisionの変更はblock別に保持し、条件の異なるblockを横断する窓は
`mixed_source_conditions`で拒否する。同じ条件のchunkだけを結合する。
validityのreason/channel/originは要求窓へclipしてsnapshotへ残す。

## graphとの接続と再開

`Graph::schedule_history()`はsnapshotだけを既存DAGへ渡す。
gap/pendingは診断として返し、ゼロ埋めしたFFT jobを作らない。
取得値はあるがvalidity spanがある窓は既存graphで数値を無効にし、購読別平均をresetする。
同じ要求区間のFFTは一つのjobから全購読へ同じresult ID/allocationで公開する。
TriggerEventと分数残差は`HistoryRead`に保持し、共有raw FFTのkeyへ通知時刻を混ぜない。
trigger付きMeasurementResultや製品保存形式への統合は006-E/008で扱う。

再開時は`History::restart_with_graph(new_source, graph)`を制御/解析の単一所有者から呼ぶ。
新履歴の構成を先に検証し、既存stream購読のgraphへgeneration fenceを入れてから履歴を交換する。
旧node/cache/最新mailbox/平均を解除し、旧Job/Completionは所有権を保ちながら公開を拒否する。
外部が保持した確定snapshotは参照できる。既存tokenは明示reconfigureで新しい世代へ接続する。
古いevent、reader、block、subscribe/reconfigure、cache参照も新世代へ適用できない。
fence数はgraphの購読上限まで。永続的に多数のStreamを切替える製品session管理は008の範囲。

履歴単体の`restart()`はgraphを変更しない。graphを併用する呼出し側は上記の接続APIを使う。
すべてalloc/解放を含むworker APIであり、音声callbackで使用しない。
005-A queue、永続取得scheduler、CPAL/PortAudio、Qtとの接続はまだ含まない。

## 正確な時刻と写像

Timebaseのrate/nominal rate、原点・clock domain・generation、不確かさは既存Sourceに保持する。
同じclock domainのsample時刻は有理数で計算し、未知原点は`unknown_origin`。
別clock domainは明示写像がなければ`unsynchronized`。同じ公称rateだけでは同期成立としない。
写像はfrom/toのTimebase IDと世代、有効sample区間、offset/rate比、手法、不確かさを検証する。
期限切れ/世代不一致はunsynchronized、未知の不確かさはNoneのまま残す。
演算はchecked i128/u128で約分し、表現できない結果は`rational_overflow`として拒否する。
物理clockの推定・写像の取得・絶対遅延精度は別の未確認範囲。

## 再検査と証拠

[native環境](README.md#このworktreeで使う)を設定する。Qt SDKとdeviceは不要。

```bash
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p graph-core
cargo +1.98.1 clippy --offline --locked --manifest-path native/Cargo.toml -p graph-core --all-targets -- -D warnings
./.venv/bin/python scripts/migration_history_candidate.py --report .migration-local/history-new.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_history_candidate.py
```

runnerは003-Bの保存履歴9例/時刻4例を完全一致で比較する。期待値は候補processへ送らない。
4/8ch × f32/f64の元input bytesを1/127/256/17 frameへ分割し、独立readerと遅れた通知から復元する。
retention後もsnapshotの全bytes一致、FFTの理論/現行数値、Source/区間、同一ID/allocation、
FFT評価1、shutdown後のnode/subscription/cache/in-flight数0を要求する。
明示`--portable`では依存環境差だけを許容し、保存hash/期待値/数値条件を維持する。
reportにsource/runner/lock/binary/input/output hashとcommandのgzip log/hash/終了コードを保存する。

AC08/09のworker所有履歴とpure graph境界までの合格。
製品scheduler/実取得/GUI/外部trigger/物理時刻、release/長時間性能/他OS、採用判断は未確認。
結果は[決定0011](../migration/decisions/0011-history-timebase-graph.md)と[進捗](../migration/status.md)に記録する。
