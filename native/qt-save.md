# MIG-007-A 両Qtの非同期測定結果保存

[非同期worker](async-save.md)と[Qt校正編集](calibration-edit.md)の次の評価単位。
[決定0026](../migration/decisions/0026-qt-snapshot-save.md)と[進捗](../migration/status.md)を参照。
保存形式は006-Eの評価用v1 JSON/CSVと[native製品JSON/CSV](product-codec.md)。
製品形式の接続は[決定0028](../migration/decisions/0028-qt-product-snapshot-save.md)で追加した。

## 操作と所有境界

主画面の「測定結果を保存」から保存先と4形式のいずれかを指定する。ダイアログを開いた時点の
完成結果をpinし、結果IDと区間を表示する。通常取得/Trigger保持/分離viewは同じ不変resultを使用する。
ダイアログ表示中も取得と表示は続く。後の校正変更・Stop→Startでpinした旧結果を再生成しない。
pending/gap/errorでは画面に完成resultがなく、保存入口を無効にする。
表示用JSONから全精度resultを再構築せず、GUIへ公開したsnapshotのArcを保持する。

要求は最大16 KiBのtyped JSONで、`generation` / `result_id` / `destination` / `format`を要求する。
pinとID/世代が一致しない要求、未知field/形式、不正JSON、容量超過を拒否する。
`true`は受付であり、完了ではない。受付は配列copy/encode/ディスクI/Oを行わない。
専用workerはqueued+writing合計2件、GUIは最大16件の小さなreceiptを保持する。
履歴は操作IDで選択し、表示更新で別の操作へ戻さない。
上限はjob数であり、全processのbyte/RSS上限ではない。

queued / writing / saved / failed / cancelledと、busy/拒否を表示する。
取消は選んだqueued要求だけ。「保存を停止」は受付を閉じ、pendingだけを取消す。
writingは実際の成否を維持し、取得を止めない。閉じた保存受付はBackend再生成で再開する。
ダイアログを閉じても受付済みの処理は継続し、pinだけを解放する。
I/O失敗は取得をFailedにせず、次の保存へ復帰する。
既存fileを上書きせず、全書込み/sync/no-clobber publish後だけsavedを通知する。
製品CSVは同じdirectoryの `.metadata.json` 付随fileと一緒に保持する。両fileの公開完了をsavedの条件とする。
sidecar公開に失敗するとCSVだけが残りうる。失敗を成功に変更せず、既存sidecarを保持し、組としての復元を拒否する。
4形式は一つのworker/2 job上限/操作ID/receipt履歴を共有し、formatの変更で容量を増やさない。

QObject破棄時はwriterのcloseを行い、join/Dropを別の終了threadへ渡す。
retire中も含めて保存sessionはprocess内で最大8個。上限時は新規受付をbusyにする。
Qt終了後、両mainが終了threadを回収し、最終receiptと `sessions=0` を記録してからprocessを終了する。
取得workerの既存joinはこの変更の対象外。診断evidenceの同期I/Oも置換していない。

## 再検査

先に[両Qtのbuild](qt-probe.md#導入とビルド)を行う。

```bash
./.venv/bin/python scripts/migration_qt_save.py --qt-prefix .tools/qt/6.11.2/macos --all-inputs --output .migration-local/007-save-new
./.venv/bin/python scripts/migration_qt_save.py --qt-prefix .tools/qt/6.11.2/macos --product-format --all-inputs --output .migration-local/007-product-save-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_save.py tests/logic_verification/test_migration_qt_display.py tests/logic_verification/test_migration_qt_workspace.py tests/logic_verification/test_migration_qt_trigger.py tests/logic_verification/test_migration_qt_calibration.py tests/logic_verification/test_migration_qt_calibration_edit.py
```

既定は9言語×両Qt、`--all-inputs`で保存4/8ch f32/f64をすべて通す。
単一言語は `--language ja`。新しいdirectoryだけを使い、fixture/許容差を変更しない。
通常結果pin→校正変更→旧結果JSON/CSV→既存file/親不在failure→復帰→Trigger保持/分離→
JSON/CSV→保存受付終了/取得停止→再開/旧世代拒否→Backend再生成→受付済みの終了を検査する。
各保存fileの全値/来歴を比較し、異なる結果だけ元bytesの独立NumPy oracleへ照合する。
同じ結果の別format・復帰保存・停止時保存は全fieldの完全一致を要求する。
取消済みfile、stale file、残った一時fileを拒否する。
writingとcloseの競合はsavedまたはcancelledを実receiptに従って検査し、固定の取消件数を要求しない。
9言語の実ラベル、主画面/ダイアログのサイズ、PNGと全file/hashを記録する。
製品形式では `result-candidate` も事前buildする。Python互換readerと既存Rust result readerで
carrier/sidecarを検査し、全snapshotを同じ元bytesのoracleへ照合する。
sidecar既存の部分pair失敗を追加し、旧file不変/復元拒否/復帰と、savedには両fileがあることを検査する。

Rust新規テストではwriterを決定的に停止し、busy、queued-only cancel、graph継続、
diskを待たないQObject破棄、終了後の実file/全配列を検査する。
`SaveWorker::with_writer()`は明示codec境界で、既定writerと同じsync/no-clobber完了条件を要求する。
製品形式も同じwriter境界へ接続し、混在formatのbusy/取消/終了と、旧pinの4形式完全往復を検査する。

保存入力の短い正確性診断に加え、明示BlackHole取得と注入待ちでのbusy/取消を
[取得中保存診断](live-save.md)へ追加した。実window manager、長時間/実負荷下の性能、
byte予算、他OS、import結果のplot統合、pair transaction、再起動校正維持は後続。
旧トレースnative importと[両Qtの読込み・参照表](qt-import.md)は独立した評価単位へ追加した。
MIG-007/008全体とRust/QML採用の合格にはしない。
