# 0026: 両Qtは表示済みの完成resultをpinして非同期保存する

日付: 2026-10-02。状態: 評価用境界。製品保存形式・公開ABI・採用の決定ではない。

## 判断

006-Eの保存workerを両Qtへ接続し、保存ダイアログを開く時点の完全resultを固定する。
解析mailboxの最新結果をクリック後に選ぶと、表示と異なる区間・校正を保存しうるため、
adapterが公開するsnapshotとfull resultのArcを同時に保持する。
QMLからはID/世代/保存先/形式を渡し、配列・校正を送り返して結果を再構築しない。
Trigger pending/gapから数値を作らず、completed captureだけを保存する。

pinした旧snapshotは取得停止・世代更新・profile変更でも不変。
保存要求はpinのID/世代へ一致する必要があるが、現在取得中の世代へ一致させて再校正しない。
新しいBackendは旧pinを持たない。ダイアログのcloseはpinを解放し、受付済みjobはworkerが所有する。

## 終了・表示・代償

保存workerは2件、GUI receipt履歴は16件、retire中を含むprocess内sessionは8個へ制限する。
busy/closedの同期拒否と、queued/writing/完了を分ける。pending-only cancelを維持する。
履歴の表示は操作IDで維持し、model配列の交換で先頭に戻さない。
I/O failureは取得へ波及させず、次の保存で復帰する。

writerのjoin/DropはGUI外の終了threadが行う。Qt終了後にmainで終了threadを回収する。
OS書込みは中断せず、進行中のjobは実際のsaved/failedを保持する。
mutex/Arc/小さなJSONのcontrol APIであり、audio callbackのRT APIではない。
job数制限はbyte予算ではなく、RSS/encoder scratch/長時間性能は008で別に測る。

## 検証と後続

[手順](../../native/qt-save.md)の保存4入力/9言語/両Qtで、全配列・来歴・旧校正・
Trigger・失敗復帰・停止/再生成/破棄を検査する。Rustではwriterを止めたままgraphを進め、
busy/取消とdiskを待たない破棄を決定的に検査する。
最終件数と失敗/未実施は[進捗](../status.md)へ記録する。

形式は実験用v1。006-E-compatのnative製品codec接続、診断I/O置換、
取得中の負荷/長時間/BlackHole保存操作、他OS/実window manager、MIG-008判断は後続。
