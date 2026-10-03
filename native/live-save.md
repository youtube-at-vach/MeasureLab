# MIG-007-A 取得中の非同期保存診断

[両Qt保存操作](qt-save.md)を[BlackHole取得](live-display.md)へ接続する。
v1 JSON/CSVと製品JSON/CSVは既存の共通worker、pin、receipt、GUI外の終了を使う。
[決定0031](../migration/decisions/0031-live-snapshot-save.md)と[進捗](../migration/status.md)を参照。

## 再実行

[固定Rust/Qt環境](qt-probe.md#導入とビルド)で両displayとresult readerを先にbuildする。
他のbuild、GUI、音声試験を終了してから、未使用の出力directoryで実行する。

```bash
./.venv/bin/python scripts/migration_qt_save.py --virtual-device --load-test --qt-prefix .tools/qt/6.11.2/macos --repeat 3 --output .migration-local/live-v1-save-new
./.venv/bin/python scripts/migration_qt_save.py --virtual-device --load-test --product-format --qt-prefix .tools/qt/6.11.2/macos --repeat 3 --output .migration-local/live-product-save-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_save.py tests/logic_verification/test_migration_qt_live.py tests/logic_verification/test_migration_qt_display.py tests/logic_verification/test_migration_qt_calibration_edit.py
```

macOSで明示 `--virtual-device` を付けた場合だけdeviceを開く。
BlackHole 2chの逆順2chと、16chから飛び飛びの4ch/8chを両Qtへ通す。
48 kHz、256-frame、f32、N=1024/boxcar、2view、既存のport別toneを使用する。
BlackHoleのrate/frame設定を変更しうる。system default deviceは変更しない。
実入力の既定言語は英語。`--language ja` などで追加言語を明示できる。
保存入力の既定9言語/4入力と `--all-inputs` は従来のまま。

通常pin→校正編集→元snapshotの保存→既存file/親不在failure→復帰→
Trigger保持/分離→保存→Stop/保存受付終了→Start→Backend再生成→終了を検査する。
製品形式では既存sidecarを残す部分pair失敗/復元拒否も含む。
同じpinのJSON/CSVと復帰保存は全fieldを完全一致へ照合する。
異なる結果の全配列/校正/区間/来歴は、該当区間の実取得bytesから独立したNumPy oracleで検査する。
診断Timerも停止したGUIの旧表示から直ちにTriggerを要求せず、新しい通知を受け取る。

## 遅い保存と記録の境界

`--load-test` はwriterだけに250 msの待ちを注入する。実ディスクの測定値ではない。
writing 1件とqueued 1件を観測し、3件目をbusyとして拒否する。
queuedを受付直後に取り消し、320 msのGUI待機中にもFFTが進むことを確認する。
writingの実成否を保存し、取消済み/拒否されたfileとsidecarを作らない。
取得queueのgap、callback error/XRUN、停止/回収の失敗は不合格とする。
`--load-test` を省略すると待ちの注入と追加のbusy/取消診断を行わない。

診断requestの `save_input_evidence` はliveとevidence directoryの両方を要求する。
`save_diagnostic_delay_ms` は既定0、最大500 msで、入力記録を有効にした診断に限定する。
音声callbackと保存受付には配列copy/encode/file I/Oを追加しない。
解析ownerだけが各FFT窓の実入力を連続順で保持し、stream/graphを止めてから
`save-input-<generation>.f32` と対応JSONを公開する。通常の取得では無効。
1世代最大256窓かつ8 MiB。上限超過、欠落/重複区間を明示failureとし、黙って切り詰めない。
N=1024では256窓が約5.46秒に相当する。長時間測定用の記録方式には使わない。
これは診断raw記録の上限であり、全result/worker/processのbyte/RSS予算ではない。
診断raw/CSVの終了処理は既存取得workerのjoin時間に含まれる。取得workerのjoinをGUI外へ一般化していない。

reportは全receipt/命令/失敗理由、実取得と刺激bytes、閉じたstreamのqueue/FFT指標、
全artifact/source/runner/binaryのhash、主画面/保存ダイアログ内容PNGを保持する。
busy/取消と実fileの整合、古い校正pinの不変性、全世代のraw/FFT範囲も検査する。

短い正確性と注入待ちの並行動作の診断であり、30秒warmup＋10分×3回の性能評価、
実ディスク負荷限界、CPU/RSS予算、同条件Python比較、物理USB/clock/遅延、他OS、
実window manager/High DPIの合格にはしない。005-A-common/006-D-integration/008-Aも残る。
