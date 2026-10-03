# 0027: 製品snapshot codecを共通保存workerへ接続する

日付: 2026-10-02。状態: native評価実装。製品schema・Rust/QML採用の決定ではない。

## 判断

[決定0025](0025-product-exchange-compatibility.md)のPython adapterを独立した比較基準として維持し、
同じJSON carrier/CSV sidecarを`graph-core::product`へ実装する。
完全snapshotは既存Rust readerへ通し、そこから再構成した全projectionの一致を要求する。
表示配列の補間/間引き/校正の再適用、旧fileにない取得情報の生成は行わない。

既存`SaveWorker`のformat型をparameter化し、v1型をdefaultとして既存Qt経路を維持する。
native製品writerは同じ容量/状態/取消/終了処理を共有し、receiptで製品形式を明示する。
異なるcodecのために二つ目のqueueや寿命規則を作らない。encode/I/Oは保存workerのみで行う。

## 境界と代償

native writerのCSVは既存製品exporterのindependent/comma/headerなし/metadata行なし/BOMなしのoptionを使う。
descriptorと校正/来歴はsidecarに保持し、翻訳headerから推定しない。
実exporterの16 independent条件はnative readerへ通す。merged snapshot復元は対象外。
carrierのない旧トレースを読むPython adapterと、検証済みsnapshotだけを復元するnative入口を区別する。

CSVとsidecarの公開は引き続きfileごとで、pair transactionではない。
部分公開はfailedにし、旧fileを置換せず、不一致の組を復元しない。
snapshot/projection/encoderにはallocationと重複があり、job数とfile上限を全processのRSS保証にしない。
製品Qt接続、取得設定の再起動維持、取得中の保存負荷、長時間/他OSは別単位とする。

## 検証と後続

[native再検査手順](../../native/product-codec.md)で全保存fixtureの双方向往復、全配列/来歴、
receiptと実file、既存file拒否、親directory不在、pair部分失敗、失敗後の復帰を検査する。
型を共通化したworkerのbusy/取消/Drain/終了、既存Qt保存経路、破損/欠落field/符号付きゼロも確認する。
source/fixture/入力/成果物とbinaryのhashをreportへ保持し、短い正確性検査を性能合格にしない。

次は製品形式のQt接続と005-A-common/006-D-integrationを進め、008-Aの同じ2chフローへ統合する。
AC12全体、MIG-006/008と採用判断を完了にせず、今回の範囲の結果を[status](../status.md)へ記録する。
