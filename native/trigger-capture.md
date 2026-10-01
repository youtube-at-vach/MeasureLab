# MIG-007-A Trigger capture worker

2026-10-01。既存のinput.raw取得ownerへ[Triggerと履歴契約](../migration/contracts/core.md#triggerと履歴)を接続する。
[決定0020](../migration/decisions/0020-trigger-capture-worker.md)と[進捗](../migration/status.md)を参照。
Qt操作・実入力への要求配送は[追加手順](trigger-display.md)で検証する。
検出器は後続。Rust/QML採用や007-A全体の完了を意味しない。

## 所有境界と読取り

`Acquisition::capture_trigger()`は解析ownerから呼ぶ。callback・Qt threadから直接呼ばない。
要求はrequest ID、元TriggerEvent、pre/postで、区間は厳密に
`[floor(event.sample)-pre, floor(event.sample)+post)`。pre+postは取得ownerのNと一致させる。
受信host時刻は診断として保存し、窓の位置計算に使わない。分数残差はHistoryReadへ保存する。
取得前はpending、開始前・取得gap・保持超過は正確なmissing区間を含むgap。
いずれもsnapshot/数値結果を作らず、呼出し側が明示的に再試行する。

完成区間は元精度のowned SignalBlock、raw FFTのArc、不変MeasurementResultを返す。
MeasurementResultへ元eventと有理数sample、source/世代/Timebase、全配列、単位・未校正reasonを残す。
未知clock原点・不確かさはnull。結果生成host時刻やphysical clockの写像は推定しない。
同じrawを再利用しても、異なるcapture metadataを持つ結果には別の不変result IDを割り当てる。

## FFT共有と通常表示

通常schedulerの同じkey/区間がcacheにあれば同じraw ID/allocationを使う。
それ以外は既存FFT実装を容量付きの一時graphで一回だけ計算し、graphを回収する。
追加cacheはraw一件。同じkey/区間への次の読取りはこれを共有する。
保持を超えた要求へcacheだけを返すことはなく、履歴のgapを優先する。

通常graphのscheduleは逆順・重複区間を拒否する。過去窓を通常購読へ再公開せず、
最新mailbox、独立平均、FFT件数、通常schedulerの次位置を保つ。
遅い読者へ合わせて取得を待たせず、外部が保持したsnapshotはeviction/restart/stop後も不変。
restart/stopはworkerの追加cacheを解除し、旧eventはstale_generationとして拒否する。

これは最小の同期worker API。Nは4096以下、ChannelId/形式は取得ownerと共通。
保存fixtureのN=4096/boxcarまで数値比較済み。一般的な複数要求queue、arm/cancel、検出器、
全FFTサイズ・前段filter後のtrigger、異なるclockの写像、長時間・負荷下の性能は未確認。
一時graphの構築・FFT・resultコピーは解析ownerの仕事で、callback安全性や性能合格の証拠にはしない。
容量は内部raw一件の境界であり、外部snapshot・resultコピーやprocess RSSの上限とは別。

## 再検査と証拠

[ローカルRust環境](README.md#このworktreeで使う)を設定し、リポジトリのルートで実行する。
元fixtureと既存runは変更しない。新規出力先を指定する。

```bash
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p graph-core
cargo +1.98.1 clippy --offline --locked --manifest-path native/Cargo.toml -p graph-core --all-targets -- -D warnings
./.venv/bin/python scripts/migration_trigger_candidate.py --output .migration-local/007-trigger-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_trigger_candidate.py
```

4/8ch × f32/f64 × identity/逆順bindingの8条件。元bytesを1/127/256/17 frameへ分割してqueueへ渡す。
未取得要求、完成後/遅い通知、1frameずらした分数triggerと別読者、保持超過、旧世代、二重stopを検査する。
32件の完全result、保持bytes、原event/残差、raw ID/allocation共有、通常graphの前後statsを保存する。
全数値配列を元bytesの独立NumPy oracleへ、未移動FFTを保存済み理論/現行値へ既存許容差で比較する。
期待値をcandidate processへ渡さず、未校正電圧をzeroにする証拠も拒否する。

reportはmanifest/source/runner/lock/binary、request/input/result/bytesのhash、command/終了コードとgzip logを持つ。
各caseのrequestと元観測はreportと同じdirectoryへ残す。`--portable`は環境差だけを許容し、
fixtureのhash・数値・metadata検査を維持する。NumPyだけの証拠破損テストは通常Python CIへ、
`native` markerの実行比較はNative evaluationへ置く。

[Qt要求配送](trigger-display.md)でrequest/revisionと2viewの共有hold/retry/releaseを接続した。
BlackHole実入力もcallbackを変更せず解析ownerへ配送する。短い取得gap検査と性能合格を区別する。
