# 製品JSON/CSVとの互換adapter評価

MIG-006-E-compat、2026-10-02。[決定0025](../migration/decisions/0025-product-exchange-compatibility.md)を参照。
Pythonの検証用adapterで、Rustの既存readerと現行の実exporterを接続する。
製品の保存schema、Rust公開型、採用言語の確定ではない。

## 再実行

[準備手順](README.md)の専用環境を使う。保存先は新しいdirectoryを指定する。
GUI/device/SciPy/FFTWをimportせず、元fixtureと数値許容差を変更しない。

```bash
./.venv/bin/python scripts/migration_product_candidate.py --output .migration-local/product-compat-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_product_candidate.py tests/logic_verification/test_migration_result_candidate.py tests/logic_verification/test_migration_async_save_candidate.py tests/core/export/test_json_exporter.py tests/core/export/test_csv_exporter.py
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

別OS/NumPy-only CIは明示`--portable`を使う。manifest/source/input/全保存fileのhashと数値条件は維持する。
runnerは既存result比較を新directoryへ保存し、その2校正契約/4交換例と4/8ch f32/f64の実graph結果を使う。
各snapshotのJSON/CSVの両入口から製品JSONとCSVを読み戻す。12実行/24完全snapshot往復を検査する。
元精度の全配列、校正/Timebase/区間/trigger/route/tap/validityがRust readerを通過し、一致する必要がある。
旧形式は実`ExportTrace`と現行exporterで生成し、JSONとCSVの32条件を独立した手計算値へ照合する。
reportにはcommand、source/binary/fixture/input/artifact hash、失敗と未確認範囲を残す。

## 対応とunknown

| 対象 | 対応・保証範囲 |
| --- | --- |
| 現行JSON | `version: "1.0"`と既存`ExportTrace`全field。軸のbase/display unit、secondary axis、校正、timestamp、任意metadataを維持。既に表示単位にある値へ校正/単位換算を再適用しない |
| 現行CSV | 明示descriptorとoptionsが必要。独立列は元軸と値、merged union列は保存された共通grid上の値を読む。comma/tab、header/metadata/BOMの有無を検査。翻訳済みheaderから単位や校正を推定しない |
| 旧取得情報 | Stream/generation/ChannelId/区間/Timebase/trigger/route/tapは`null`。timestampや相対軸から取得clockを作らず、trace IDをChannelIdと扱わない |
| native FFTの軸 | 相対spectrumはnominal Hz、絶対PSDはcorrected Hz。complexはy/y2のreal/imag。inverse/windowはsample offset、channel単値はchannel index。UTC不明のtimestampは空文字 |
| 無効値 | 旧`ExportTrace.from_dict()`はnumeric nullを読めない。無効要素を含むprojectionを理由付き一覧へ明示し、表示用配列に0/NaNを作らない。完全snapshotには全null/reason/影響区間を維持 |
| 未対応の旧file | 非有限数、重複JSON key/ID、欠落field、矛盾する軸/shape/校正、暗黙descriptor、interior paddingを拒否。全解析専用形式のimporterではない |

`scripts/migration_product_exchange.py`の`import_json()`は旧JSONを読む。
CSVは`csv_spec()`相当のdescriptorを明示して`import_csv()`を使う。
返す`Imported`は旧トレースと取得情報のunknownを区別する。旧fileから架空の`MeasurementResult`を生成しない。
`merged_grid_may_be_interpolated`は元gridの復元保証ではない。現在の試作はunion mergedのみを対象とする。

## 完全snapshotの保存

製品JSONの先頭に空のmetadata carrier traceを置き、`metadata.mig_006_e_snapshot`へ
評価版1の完全snapshotと省略projectionの一覧を保持する。残りのtraceは元配列の有限値projectionである。
現行`ExportTrace`/JSON exporterはこのmetadataを変更せず往復する。
読込みはcarrierが先頭かつ一件であることを要求し、snapshotをRust readerへ通す。
そこからprojectionを再構成し、全trace/軸/校正/metadataが一致しなければ復元を拒否する。
任意のmetadata carrierを信用して無検査で数値resultを作らない。

CSVは現行exporterのindependent列をそのまま保存し、`<file>.metadata.json`へdescriptorと
同じcarrierを保存する。sidecarのSHA-256とCSV bytesの一致、版/layout、列値とsnapshotの一致を要求する。
これは製品CSV自体の新schemaではなく、完全復元に必要な評価用sidecarである。
sidecarがないCSVは元の校正/来歴を復元できない。古いCSVからそれらを捏造しない。

各fileは同じdirectoryの一時fileへ現行exporterで書込み、close/fsync後にhard linkで公開する。
既存fileを置換せず、失敗は例外にし、一時fileをcleanupする。
CSVを先に公開し、その後sidecarを公開するため、後者の失敗はorphan CSVを残しうる。
pair全体の成功を返さず、既存sidecarを変更せず、不一致の組をreaderが拒否する。
pair transaction、hard-link非対応filesystem、directory metadataの電源断耐性は未実装/未検証。

読取fileは各256 MiB、projectionは4,000,000 numeric scalarと1024 traceを上限とする。
完全snapshotの保持、deep copy、encoder scratch、全processのRSS上限ではない。
処理はfile worker用で、audio callbackやGUI threadへ追加しない。
`save_json()`/`save_csv_pair()`は同期APIで、nativeの同形式codecと共通非同期workerは[別単位](product-codec.md)で追加した。

## profileと再起動の範囲

保存したprofileは結果の校正snapshotとして、新しいprocessから再読込しても保持する。
legacy `CalibrationInfo`の係数1や`is_calibrated: false`を校正済みの証拠へ変えない。
読み戻した結果のprofileを現在のdevice/sessionへ自動適用しない。
取得用profileの再起動維持、device再照合、Qt編集設定の保存、旧設定の自動移行は未実装。
MIG-008の製品schema判断時に、結果の復元と取得設定の再開を個別に決める。

007-A-saveのv1操作と[native製品codec/file worker](product-codec.md)を追加した。
次はQt製品format接続、005-A-common、006-D-integrationを進める。
取得中の保存負荷、長時間性能、実機/他OS、製品GUI import操作、MIG-008と採用判断は未完了。
実施結果は[status](../migration/status.md)を正本とする。
