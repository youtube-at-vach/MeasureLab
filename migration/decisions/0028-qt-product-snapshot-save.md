# 決定0028: 両Qtの製品snapshot保存形式

2026-10-02、MIG-007-A-product-save。
[v1保存操作](0026-qt-snapshot-save.md)と[native製品codec](0027-native-product-snapshot-codec.md)の接続を評価する。
Rust/QMLの採用、製品schemaの確定、import UI、MIG-008の完了は判断しない。

## 接続と所有権

両Qtが共有するdisplay-coreの保存制御へ `product_json` / `product_csv` を追加する。
一つのtyped formatとworkerで既存 `json` / `csv` も処理し、2 job上限/操作ID/receipt履歴/終了を共有する。
GUIに公開した通常/Triggerの完全resultをpinし、そのArcを受付で渡す。
配列copy/encode/ディスクI/Oはwriter内で行い、join/Dropは既存のGUI外の終了threadに維持する。

製品JSONはcarrier、製品CSVは独立列とhash付きsidecarを使い、元精度/校正/来歴/nullを保持する。
CSVとsidecarの両公開が完了した場合だけsavedにする。部分失敗のorphan CSVはfailedを維持し、
旧sidecarを上書きせず、readerで復元を拒否する。pair transactionは今回の保証に含めない。
ダイアログに4形式の翻訳済みラベルと、CSVの付随file保持/部分失敗の説明を追加する。

## 検査と残る範囲

[保存runner](../../scripts/migration_qt_save.py)の `--product-format` で
保存4/8ch f32/f64×9言語×両Qtを通す。通常pin後の校正変更、Trigger hold/分離、
既存file/親不在/sidecar公開失敗と復帰、stop/再開/Backend再生成/終了を検査する。
Python互換readerとRust result readerを使って全値/区間/Timebase/校正/metadata/nullを読み、
元bytesの独立oracleと、同じpinの全format完全一致へ照合する。
receiptのformat/ID/世代/区間/実file、取消時のCSV/sidecar不在、旧sidecar不変/復元拒否、
一時file不在、9言語の実ラベル/geometry/PNGも検査する。

Rust試験は旧pinの4形式往復、部分pair失敗後の復帰と取得継続、
製品/v1混在時のbusy/pending取消/writing実成否、GUI外のwriter終了を検査する。
実施結果・report・未実施は[進捗](../status.md)を正本とする。

製品import UI、旧トレースのnative import、再起動校正維持、取得中の保存負荷/長時間、
process byte/RSS予算、実window manager、他OS、005-A-common/006-D-integration/008-Aは残る。
短い保存入力の正確性診断をAC15/16やMIG-007/008全体の合格に加算しない。
