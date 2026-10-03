# MIG-007-A 両Qtの非同期測定結果保存

[非同期workerの実装](graph-core/src/export.rs)と[Qt校正編集](calibration-edit.md)の次の評価単位。
[進捗・検証結果](../migration/status.md)を参照。
保存形式は006-Eの評価用v1 JSON/CSVと[native製品JSON/CSV](product-codec.md)。

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

## 対象変更の検証

現在の範囲は[MIG-008計画](../guide/RUST_QML_MIGRATION_PLAN.md)に従う。
関連する変更がある場合だけ[対象テスト](../tests/logic_verification/test_migration_qt_save.py)と[runner](../scripts/migration_qt_save.py)を使う。
オプションは`./.venv/bin/python scripts/migration_qt_save.py --help`で確認する。
全条件の再実行・長時間試験・他OS検証はMIG-008の前提にしない。
