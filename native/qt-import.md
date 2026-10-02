# MIG-007-A 両Qtの非同期製品読込み

2026-10-03、MIG-007-A-product-import。[native製品parser](product-import.md)と
[製品保存操作](qt-save.md)の次の評価単位。
[決定0030](../migration/decisions/0030-qt-product-import.md)と[進捗](../migration/status.md)を参照。
Rust/QML採用や製品schemaの確定ではない。

## 操作と所有境界

「保存結果を読み込む」からfileと形式を明示する。製品JSON、CSVとhash付きsidecar、
明示CSV記述fileの3入口を共通parserへ配送する。CSVの翻訳headerから単位や校正を推定しない。
旧トレースの取得情報はunknown、検査済みcarrierがある場合だけ完全snapshotを保持する。
merged CSVは保存された共通gridと明示し、元gridを復元したと扱わない。

独立した参照ダイアログでトレースを選び、元のindexとX/Y/Y2値、base/display unit、
校正有無、source/timestamp、snapshotの無効区間数とerrorを確認する。
表示済み値への単位変換・校正の再適用、現在の取得profileへの反映は行わない。
snapshotにない数値や来歴を生成しない。空のcarrierや無効で省略されたトレースをゼロに置換しない。
取得中のline/heatmap、Trigger保持と保存pinはこの参照表示とは独立している。

読込みと検査、診断fileの出力、プレビュー生成を専用readerで実行する。
GUIの受付は最大16 KiBのtyped JSONを検査し、path/format/specと操作IDだけをqueueへ渡す。
queued+readingは合計2件、receipt履歴は16件。3入口で容量・操作IDを共有する。
操作IDはprocess全体で一意に増加し、Backend再生成で再利用しない。
受付とloadedを区別し、queued/reading/loaded/failed/cancelledとbusy/拒否を表示する。

全配列、metadata、精度、null/reason、校正、Timebaseと取得来歴はworker所有の
`ImportedProduct`に保持する。Qtへ渡すのは元indexから抜き出した値だけで、補間しない。
トレースごと最大256行、全トレース合計8192 numeric scalar以内、preview JSONは1 MiB以内。
数値は元のdecimal tokenを文字列として表示し、JavaScriptによる負のゼロの消失を防ぐ。
ID/名称/軸descriptor等の各文字列は256文字まで。超過はfailedとし、単位やIDを黙って短縮しない。
これらは表示境界の上限であり、parserの256 MiB/4,000,000 scalar上限やprocess RSS予算とは別である。

最新の受付IDと一致するloadedだけを表示する。新しい受付中、最新のfailed/cancelled、
受付終了後に古い完成結果を再表示しない。queuedだけ取消可能。readingは実際の成否を維持する。
ダイアログのCloseは参照表示を閉じる。受付済み要求と参照値はBackend内に保持され、再表示できる。
取得Stop→Startでも参照値は保持し、Backend再生成では旧要求を回収して空の参照表示になる。

QObject破棄はpendingを取消し、readerのjoinと全productのDropを専用終了threadへ渡す。
重い旧productの置換/解放もworkerで、GUI/取得ownerの外で実行する。
retire中を含むreader sessionはprocess内で最大8個。
Qt終了後の両mainが終了threadを回収し、実receiptと`sessions=0`を記録する。
既存取得workerのjoin方式と同期diagnostic I/Oはこの変更の対象外である。

## 再検査

先に[両Qtのbuild](qt-probe.md#導入とビルド)と`result-candidate`のbuildを行う。
新しいdirectoryだけを指定する。runnerは3実行物をコピーして固定し、元fixtureを変更しない。

```bash
./.venv/bin/python scripts/migration_qt_import.py --qt-prefix .tools/qt/6.11.2/macos --all-inputs --jobs 2 --output .migration-local/007-product-import-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_import.py tests/logic_verification/test_migration_qt_save.py tests/logic_verification/test_migration_qt_display.py tests/logic_verification/test_migration_product_import_candidate.py -m "not native"
```

既定は9言語×両Qt。`--all-inputs`で保存4/8ch f32/f64を通す。
別OSのfixture比較は明示`--portable`、単一言語は`--language ja`。
`--jobs 2`は独立processによる短い正確性診断用。性能protocolのsampleには使用しない。

旧JSON→旧CSV pair→merged CSV/spec→破損file→完全snapshot JSON/CSV→取得再開→
reader受付終了→Backend再生成→受付直後の終了を検査する。
実exporterの旧値/軸/Y2とunknown、保存snapshotの全配列・null/reason・校正・来歴を
独立Python readerとnative result readerへ照合し、元入力bytesのNumPy oracleでも確認する。
GUIへ表示した操作ID/preview、最終receipt、旧入力/descriptor不変、失敗後の復帰、
取得継続、9言語の実ラベル/サイズ、failed/拒否/closedの読込み用文言、PNGと全成果物hashを記録する。
close/終了競合はloadedまたはcancelledを実receiptに従って検査し、固定の取消件数を要求しない。

決定的にreaderを止めるRustテストで、busy、queued-only cancel、旧完了のfence、
diskを待たないQObject破棄、取得/profile独立性と全product保持を確認する。
GUI停止・reader終了は短い正確性診断で、長時間/取得中負荷の合格ではない。

参照表の評価範囲であり、import結果のline/heatmap統合、全点cursor/zoom、
再エクスポート、取得profileの再起動維持、実window manager/High DPI、他OSは後続。
MIG-006/007/008全体とRust/QML採用の合格にはしない。
