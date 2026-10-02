# native製品snapshot codecと保存worker

MIG-006-E-native-product、2026-10-02。[決定0027](../migration/decisions/0027-native-product-snapshot-codec.md)と
[Python互換adapter](product-exchange.md)を参照。製品schemaとRust/QML採用の確定ではない。

## codecと所有境界

`graph-core::product`は既存の製品JSON 1.0、先頭carrier、独立列CSVとhash付きsidecarを使う。
全snapshotを既存`MeasurementResult::decode()`へ通し、全projectionを再構成して一致を要求する。
値/元精度/軸/単位/校正/Timebase/区間/trigger/route/tap/validityとnull/reasonを保持する。
校正を再適用せず、無効projectionは理由付きで省略し、carrierには元配列を残す。
重複JSON key、欠落field、非有限値、f64へ非可逆な整数、projectionの改変と符号付きゼロの改変を拒否する。

`SaveWorker<ProductFormat>::start_product()`は同じbounded workerを使い、不変resultのArcを受付で共有する。
受付で配列の複製/encode/ファイルI/Oを行わず、workerだけがcodecとpublishを実行する。
receiptのformatは`product_json`/`product_csv`で、既存v1の`json`/`csv`と区別する。
容量、busy/closed、pending-only cancel、writingの実成否、Drain/CancelPending、終了とsnapshot回収は共通である。
wait/join/Dropは制御・終了threadで行い、GUI/audio callbackへ置かない。
[両Qt保存操作](qt-save.md)は同じworkerへ4形式を配送し、一つの容量/操作ID/receiptを共有する。

native CSV writerは製品exporterの既存optionであるindependent/comma/headerなし/metadata行なし/BOMなしを使う。
列descriptorと完全carrierはsidecarへ保存するため、翻訳済みheaderの生成や解釈を必要としない。
readerはindependentのcomma/tab、header/metadata/BOMの16条件を実exporterで検査する。
headerは列数だけを確認し、単位/校正をそこから推定しない。CSVの未閉鎖quote、空のdata行、interior paddingも拒否する。
merged表の完全snapshot復元、carrierのない旧fileからのresult生成は拒否する。
旧トレースと取得情報のunknownは[別のnative import入口](product-import.md)でも読む。
既存の完全snapshot専用readerは旧fileを拒否し、返す型と保証を維持する。

## 保存完了と制限

各fileを同じdirectoryの一時fileへ書き、flush/sync後にhard linkでno-clobber公開する。
CSVを先、sidecarを後に公開し、両方が完了した場合だけreceiptをsavedにする。
sidecar公開の失敗はorphan CSVを残しうるが、failedを維持し、旧sidecarを置換せず、readerは不一致の組を拒否する。
失敗後も同じworkerで次の保存を処理する。pair transactionやdirectory metadataの電源断耐性は保証しない。

各fileは256 MiB、projectionは4,000,000 numeric scalar/1024 trace、workerは1〜8 jobを上限とする。
完全snapshot/表示用projection/encoder scratchには重複とallocationがあり、process RSSのbyte予算ではない。
進行中のOS書込みの中断、終了時間の上限、hard-link非対応filesystemは未対応。

## 再検査

[Rust環境](README.md#このworktreeで使う)を設定し、新しい出力directoryを指定する。

```bash
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p graph-core -p display-core -p dsp-core -p audio-core -p probe-core --lib
cargo +1.98.1 clippy --offline --locked --manifest-path native/Cargo.toml -p graph-core -p display-core -p dsp-core -p audio-core -p probe-core --all-targets -- -D warnings
./.venv/bin/python scripts/migration_product_candidate.py --native-product --output .migration-local/native-product-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_product_candidate.py tests/logic_verification/test_migration_async_save_candidate.py tests/logic_verification/test_migration_result_candidate.py tests/logic_verification/test_migration_qt_save.py tests/core/export/test_json_exporter.py tests/core/export/test_csv_exporter.py
```

別OS/NumPy-only CIは明示`--portable`を追加する。元fixture/source hash/数値許容差を変更しない。
runnerは2校正契約/4交換例と4/8ch f32/f64から12実行を行い、
native保存→Python readerの4往復と、実exporter→native readerの2往復を各実行で照合する。
計72の完全snapshot往復、48 saved/48 expected failedを検査し、部分pairと失敗後の復帰も確認する。
既存Pythonの24往復と旧JSON/32 CSV条件は別の検査として維持する。
reportにsource/binary/fixture/input/artifact hash、command、receipt、失敗と未確認範囲を残す。

Qtの製品保存formatは[決定0028](../migration/decisions/0028-qt-product-snapshot-save.md)で接続した。
旧トレースと完全snapshotの[native import](product-import.md)を追加した。
Qt製品import操作、取得profile再起動維持、取得中の保存負荷/長時間、他OS、
005-A-common/006-D-integration/008-Aの統合と採用判断は未完了。結果は[status](../migration/status.md)を正本とする。
