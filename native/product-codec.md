# native製品snapshot codecと保存worker

MIG-006-E-native-product、2026-10-02。[既存の検証結果](../migration/status.md#再利用する証拠)と
[Python互換adapterの実装](../scripts/migration_product_candidate.py)を参照。製品schemaとRust/QML採用の確定ではない。

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
旧トレースと取得情報のunknownは[別のnative import入口の実装](graph-core/src/product/import.rs)でも読む。
既存の完全snapshot専用readerは旧fileを拒否し、返す型と保証を維持する。

## 保存完了と制限

各fileを同じdirectoryの一時fileへ書き、flush/sync後にhard linkでno-clobber公開する。
CSVを先、sidecarを後に公開し、両方が完了した場合だけreceiptをsavedにする。
sidecar公開の失敗はorphan CSVを残しうるが、failedを維持し、旧sidecarを置換せず、readerは不一致の組を拒否する。
失敗後も同じworkerで次の保存を処理する。pair transactionやdirectory metadataの電源断耐性は保証しない。

各fileは256 MiB、projectionは4,000,000 numeric scalar/1024 trace、workerは1〜8 jobを上限とする。
完全snapshot/表示用projection/encoder scratchには重複とallocationがあり、process RSSのbyte予算ではない。
進行中のOS書込みの中断、終了時間の上限、hard-link非対応filesystemは未対応。

## 対象変更の検証

現在の範囲は[MIG-008計画](../guide/RUST_QML_MIGRATION_PLAN.md)に従う。
関連する変更がある場合だけ[対象テスト](../tests/logic_verification/test_migration_product_candidate.py)と[runner](../scripts/migration_product_candidate.py)を使う。
オプションは`./.venv/bin/python scripts/migration_product_candidate.py --help`で確認する。
全条件の再実行・長時間試験・他OS検証はMIG-008の前提にしない。
