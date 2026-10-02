# 0024: 不変snapshotのencodeと書込みを専用workerへ分離する

日付: 2026-10-02。状態: 評価用境界。製品保存形式・公開ABI・採用の決定ではない。

## 判断

006-Eのv1 JSON/CSVとno-clobber publishを再利用し、最大8件の保存workerを追加する。
007-A校正編集で通常/Triggerの完全JSON encodeが取得の進行を妨げたため、
製品保存操作を接続する前にencode/I/Oと取得/graphの所有を分離する。
今回のworkerは診断I/Oを置換せず、独立した保存境界として検証する。

要求は不変の `Arc<MeasurementResult>` を持ち、GUIの現在設定や表示用配列から結果を作り直さない。
受付時は配列copy/encode/I/Oをしない。容量はqueued+writingで数え、満杯を同期的に拒否する。
ticketは小さなreceiptだけを保持するため、利用者が完了をpollしなくてもworkerが数値snapshotを回収できる。

enqueueを保存完了と区別し、全書込み/sync/publish後だけsavedにする。
pending-only cancelと実書込み開始を同じstatusで直列化し、書込み中は実際の成否を保つ。
I/O failureは取得・元resultに波及させず、次の保存へ復帰する。
writer panicだけはpublish状態unknownを通知してworkerを閉じ、未開始の要求をcancelする。

## 境界と代償

容量はjob数であり、全metadata・encoder scratch・外部snapshot・RSSのbyte上限ではない。
mutex/allocationを含むcontrol APIで、audio callbackへ追加しない。
OS書込みを中断せず、join/Dropは待つため、Qt接続時の終了処理をGUI外へ配送する必要がある。
hard link publishのfilesystem要件とdirectory crash durability未保証は006-Eから継承する。
JSON/CSV pairのatomic commitと、旧製品形式/importer、保存UI・再起動維持は別の作業票へ残す。

## 検証と次の工程

[手順](../../native/async-save.md)のRustテストはwriterを停止したまま実graphを進め、
共有FFT/回収、pending/writingとcancel/stop、profile不変、容量、失敗/panicと実fileを検査する。
独立runnerは既存2校正契約と4入力を理論/現行へ比較し、両formatから非同期保存した全値/来歴を完全照合する。
receiptの未完了やID/世代/区間/保存先/errorの破損を合格にしない。

次は007-A-saveで保持中の通常/Trigger snapshotと同じworkerを両Qtの保存操作へ接続する。
製品互換adapterと取得中の保存負荷は別々に検査し、MIG-008の統合フローと判断材料へ渡す。
実施結果は[進捗](../status.md)、残工程は[整理表](../remaining-to-mig008.md)へ記録する。
