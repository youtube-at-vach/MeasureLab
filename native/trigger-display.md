# MIG-007-A Qt Trigger要求配送

2026-10-01。[Trigger取得owner](trigger-capture.md)を独立解析threadと両Qt adapterへ接続する。
[決定0021](../migration/decisions/0021-qt-trigger-delivery.md)と[進捗](../migration/status.md)を参照。
手動sampleイベントの短い検証で、検出器・外部clock・製品Oscilloscopeの実装や採用判断は含まない。

## 配送と所有境界

Qtは`request_trigger()`へJSONのrevision/request ID/元TriggerEvent/pre/postを送る。
制御側で8 KiB上限・型・世代・単調revisionを検査し、未処理操作一件のmailboxへ入れる。
解析threadだけが`capture_trigger()`を呼ぶ。callbackのqueue・処理内容は変更しない。
新要求は元イベントを置き換え、retryは同じイベント/revisionを再配送する。
他の未処理操作があると要求を拒否し、既存の状態を維持する。

queued/pending/gap/errorには数値frameを付けない。pendingは明示retryまで保留する。
完成時は一つのArcと不変projectionを両viewへ渡し、通常取得・共有FFTは継続する。
同一区間の別requestはraw IDを共有し、capture metadataの異なるresult IDを保存する。
履歴容量は8窓。表示projectionは必要な軸/peak列だけを読み、完成MeasurementResultはArcで共有する。
全数値列のJSON化と取得bytesのcopyは、明示した診断保存の時だけ行う。
QMLはJSON文字列が変わった時だけprojectionを生成・凍結する。
通常counterのQt通知で保持objectを再生成しない。cursor/zoomと分離は同じframeを参照する。

releaseは保留/実行中要求の後続公開を直ちにfenceし、両viewを通常表示へ戻す。
追加raw cacheの解除は解析ownerで行い、処理前の新要求にはbusyを返す。
stop/最後の需要解除で未完成要求をcancelledにし、完成済みの外部snapshotは維持する。
restartは新世代のmailboxへ初期化し、旧世代request/retry/release/Qt通知を拒否する。
再生成・終了ではworker/graph/streamを回収する。

手動欄は元Timebaseのsample位置を整数または0.5 sampleで指定する。
pre/postは現在のNの半分ずつ。受信host時刻とclock写像はnullで、GUIの時刻から位置を推定しない。
これは容量付きの評価用境界で、複数独立hold queueや検出器のarm/cancelではない。

## 再検査

[ローカルRust環境](README.md#このworktreeで使う)を設定し、ルートで実行する。
元fixtureと既存runを保持し、新規出力先を指定する。

```bash
export QMAKE="$PWD/.tools/qt/6.11.2/macos/bin/qmake"
cargo +1.98.1 build --offline --locked --manifest-path native/Cargo.toml -p cxxqt-display -p qtbridge-display
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p display-core -p graph-core
./.venv/bin/python scripts/migration_qt_trigger.py --qt-prefix .tools/qt/6.11.2/macos --all-inputs --output .migration-local/007-trigger-display-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_trigger.py tests/logic_verification/test_migration_qt_workspace.py tests/logic_verification/test_migration_trigger_candidate.py
```

保存4/8ch f32/f64×9言語×両Qtの72実行。通常2世代の完全result、保留/完成/欠落のreceipt、
triggerの完全result二件と元精度の取得bytes、PNGを各実行へ保存する。
全数値配列・source/ID/位置/分数残差・未校正reasonは独立NumPy oracleと固定fixtureへ照合する。
元bytes/完全resultと表示projectionの一致、同じraw ID/追加FFT数不変、
保持中の取得継続、分離/zoom、release、stop、restart、Backend破棄後の不変性を検査する。
GUIは640 ms停止させ、停止中のFFT評価増分を保存する。少なくとも二窓の継続を求める短い診断で、
FFTの定常throughput・GUI通知遅延やAC15/16の性能予算の合格には数えない。
9言語の実ラベル/button幅/1180×690 px上限も検査する。
fixtureの環境差だけを許容する場合は`--portable`を明示する。

BlackHoleがあるmacOSでは、callbackを変更せず同じ解析ownerへ実入力の要求を送れる。
通常の音声検証はBlackHole 2ch／16chを使用する。

```bash
./.venv/bin/python scripts/migration_qt_trigger.py --virtual-device --qt-prefix .tools/qt/6.11.2/macos --repeat 3 --output .migration-local/007-trigger-live-new
```

2→2/4-from-16/8-from-16×両Qt。全trigger取得bytesから全FFT配列を独立計算し、
port bindingとtoneを照合する。二世代の取得窓とstream停止診断も検査する。
deviceは完全一致、48 kHz/256 frame/f32。default deviceを変更せず、fallbackしない。
実入力診断とGUI/build負荷を同時実行しない。gap/error/XRUNを成功やzeroへ置き換えない。

reportへsource/翻訳/runner/binary/request/receipt/result/bytes/PNGのhashと実行出力を記録する。
証拠破損テストはNumPyだけで実行でき、独立Native CIへQt比較を追加した。
GitHub実行、実window manager、長時間/負荷下/他OS、前段filter後のtrigger、
校正・製品保存互換/非同期保存、Rust/QML採用と007-A全体の完了は別に残す。
