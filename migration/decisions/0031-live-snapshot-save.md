# 決定0031: BlackHole取得中の両Qt snapshot保存

2026-10-03、MIG-007-A-live-save。[製品保存形式](0028-qt-product-snapshot-save.md)の次の診断単位。
実施結果と失敗logは[進捗](../status.md)、再実行は[手順](../../native/live-save.md)を参照。
Rust/QML採用、MIG-008統合、長時間性能は判断しない。

## 接続と元bytesの保持

既存の両Qt保存操作をCPAL input.raw/共有FFTへ接続する。
通常/Triggerのpin、校正snapshot、容量2件、receipt16件、GUI外のwriter joinを維持する。
v1と製品JSON/CSVは既存writer/codecを使い、取得停止後の診断exportだけで保存成功を代用しない。
製品CSVの部分pair公開はfailedのまま保持し、旧sidecarを保護して復元を拒否する。

任意のpin結果を実取得bytesへ照合するため、明示診断requestで解析ownerにraw窓記録を追加する。
各世代で連続した最大256窓/8 MiBを保持し、callback/stream/graphを回収してからfileへ保存する。
不正なlive/evidence設定、500 ms超の注入待ち、区間不連続、容量超過を拒否する。
全processのメモリ上限や長時間記録への一般化は行わない。

## 並行動作の検査

writerに250 msを明示注入し、writing+queuedでbusy、queued-only取消、
GUIの320 ms待機中の取得進行、実fileとのreceipt整合を検査する。
待ち時間は実ディスク性能ではなく、制御/所有境界の検査条件である。
通常snapshot pin後のprofile編集、Trigger保持/分離、I/O失敗後の復帰、
Stop/保存受付終了/再開/Backend再生成/終了を同じ両Qt経路で通す。
旧結果を新しい校正で再計算せず、完成resultの全値/単位/metadataと元bytes oracleを照合する。

初回診断の取消競合と、GUI待機後の古いTrigger区間を指す問題は検証Timerで修正した。
取消は受付直後に行い、GUI待機後は新しい通知を受け取ってから区間を選ぶ。
容量や数値許容差を緩めず、初回の容量超過/取消失敗を成功記録へ混ぜない。

## 残る判断

短いBlackHole診断の結果はAC07/12/13の対象境界だけへ加える。
AC15/16の10分試験、同条件Python比較、実ディスク保存負荷、byte/RSS予算、
全tap/共通backend、対象filter統合、物理USB/clock/遅延、他OS/clean配布/手動操作は残る。
P2の2ch統合物を固定してから性能を比較し、短い診断だけで採用を決めない。
