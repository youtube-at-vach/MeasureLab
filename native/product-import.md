# native製品JSON/CSVの読込み

MIG-006-E-native-import、2026-10-02。[決定0029](../migration/decisions/0029-native-product-import.md)と
[互換adapter](product-exchange.md)を参照。製品schemaとRust/QML採用の確定ではない。

## 読込みと所有境界

`graph-core::product::ImportedProduct`は検査済みの製品1.0トレースを保持する。
`snapshot()`は検査済みcarrierがある場合だけ`MeasurementResult`を返す。
carrierのない旧トレースは`None`、取得のStream/generation/ChannelId/区間/Timebase/trigger/route/tapは
すべてunknownの`null`である。trace ID、timestamp、相対軸から取得情報を生成しない。
旧トレースの軸、base/display unit、secondary axis、校正、任意metadata、元の有限配列を保持し、
表示済み値へ単位換算・校正を再適用しない。読込resultのprofileを現在のdevice/sessionへ適用しない。

| 入口 | 対象・条件 |
| --- | --- |
| `import_json()` / `load_import(ProductJson)` | 旧JSONまたは完全snapshot付き製品JSON。version 1.0、全field、ID/shape/軸/校正/数値を検査 |
| `import_csv()` / `load_csv_with_spec()` | 明示options/descriptorを要求。independent/merged、comma/tab、header/metadata/BOMの32条件 |
| `import_csv_pair()` / `load_import(ProductCsv)` | `.metadata.json` sidecarの版/kind/CSV hashを検査。independentだけ。旧トレースまたは完全snapshot |
| 既存`decode_json()` / `decode_csv_pair()` / `load()` | 完全snapshotだけを返す従来の入口を維持。旧トレースは引き続き拒否 |

independent列は`original_trace_arrays`、merged列は`merged_grid_may_be_interpolated`として返す。
mergedは保存された共通gridと値をそのまま読む。元gridの逆算、追加補間、完全snapshotの復元は行わない。
翻訳済みheaderは列数だけを検査し、単位・校正を推定しない。

予約carrierがあるfileは先頭/一件のenvelopeと全snapshotを既存Rust readerへ通し、
再構成したprojectionとすべて一致する場合だけ復元する。破損carrierを旧トレースへfallbackしない。
null/reason/影響区間は完全snapshotに保持し、無効projectionを0で埋めない。
重複JSON key/ID、欠落field、非有限値、f64へ非可逆な整数、CSVの未閉鎖quote、
空のdata行、欠落cell、interior padding、sidecar不一致を拒否する。

各fileは256 MiB、1024 trace、4,000,000 numeric scalarを上限とする。
JSONの整数tokenはsigned/unsigned 64bit内に限定し、範囲外をserdeのf64変換前に拒否する。
任意精度整数metadataは対象外。浮動小数tokenは有限f64として扱う。
snapshot/projection/JSON保持とencoder scratchはallocationを伴い、process RSSのbyte予算ではない。

すべて同期のfile-worker APIであり、GUI/audio callback/取得ownerから直接呼ばない。
新しいprocessの独立CLIで結果を検査し、入力/descriptor/sidecarを変更せずowned resultを返す。
[両Qtの非同期配送・参照表](qt-import.md)に容量/取消/旧要求のfenceとGUI外joinを追加した。
この同期APIをGUI/取得ownerから直接呼ばず、独立reader経由で利用する。

## 再検査

[Rust環境](README.md#このworktreeで使う)を設定し、新しい保存先を使う。

```bash
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p graph-core -p display-core -p dsp-core -p audio-core -p probe-core --lib
cargo +1.98.1 clippy --offline --locked --manifest-path native/Cargo.toml -p graph-core -p display-core -p dsp-core -p audio-core -p probe-core --all-targets -- -D warnings
./.venv/bin/python scripts/migration_product_import_candidate.py --output .migration-local/native-import-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_product_import_candidate.py tests/logic_verification/test_migration_product_candidate.py tests/logic_verification/test_migration_qt_save.py tests/core/export/test_json_exporter.py tests/core/export/test_csv_exporter.py -k 'not complete_corpus_headless_product_roundtrips'
```

別OS/NumPy-only CIはrunnerへ明示`--portable`を追加する。元fixture/source/許容差は変更しない。
実exporterの旧JSON/CSV 32条件と旧CSV pairを独立Python readerと手計算値へ照合する。
保存2校正契約/4交換例と4/8ch f32/f64の6完全snapshotを作り、JSON/CSV pair/明示CSV specの
3入口、計18のnative importを全配列・元精度・校正・Timebase・区間・trigger・validityまで比較する。
reportは固定binary、source/helper、fixture/input/descriptor/sidecar/成果物hash、command、失敗を保持する。
短いheadless正確性診断であり、Qt操作/取得中負荷/長時間/他OS/製品採用の合格ではない。
最終結果と未確認範囲は[status](../migration/status.md)を正本とする。
