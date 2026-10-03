# 0032: 一段f64 filterを取得ownerへ接続

日付: 2026-10-03。MIG-006-D-integration。状態: 保存入力の接続候補。Rust/QML採用は未決定。
[正本計画](../../guide/RUST_QML_MIGRATION_PLAN.md)、[pure filter決定](0012-filter-rate-graph.md)、
[取得owner決定](0014-acquisition-history-shared-fft.md)、[再実行手順](../../native/filter-acquisition.md)を参照。

## 問題と判断

filter/rateの独立probeは、全出力を計算した後に履歴/FFTを検査していた。
008-Aへ進むには、callback queueからの連続取得、欠落、派生履歴、共有FFT、終了と再開を
同じownerで検査する必要がある。既存の`Acquisition<T>`へ任意の一段f64 filterを追加する。
入力を消費する前に設定し、実Sourceに一致する親と正確な出力FFT購読を要求する。

P2の最初の対象はf64の因果3-tap 48→24 kHz。保存済みpolyphase/SOSは同じ取得経路の回帰に使う。
現在のCPAL/Qtはf32で、暗黙変換やf32 filterの合格を追加しない。
005-A-commonを待たず保存入力を進め、backend/全tapとQtへの接続は次の評価単位へ残す。

## 所有と失敗

- 一つのgraphにraw/派生の固定FFT需要を置き、filter stateを共有する。
  専用履歴・絶対出力位置と各pollの窓上限を持たせる。GUIの通知時刻をsample位置に使わない。
- FIRは欠落supportを保持し、中心補償は先読みと明示EOFまで待つ。
  producer停止とdrainをEOFの前提とし、未読queueがあれば原子的に拒否する。
  `stop`/cancelは終端paddingを生成しない。
- SOS gap/invalidとfilter容量超過はownerのfailureとする。回復規則を推測しない。
  raw/派生のqueue/history/tokenを回収し、外部の確定snapshotは保持する。
- 最後の派生購読解除でfilter、次のpollで履歴を回収し、raw需要を継続できる。
  解除と処理が交差してfilterが消えた場合は、raw取得を失敗にしない。
  親restartのfenceを派生completionへ伝播し、新世代には明示再設定を要求する。
- 小さい履歴で失った派生窓は位置付きmissingとして返し、正常なFFT値で埋めない。
  processing latencyはunknown、信号遅延は有理数を維持する。

## 証拠と境界

元fixture/契約/許容差/係数を維持する。21ケース×5 chunkを実queueへ通し、
FIRの欠落は実overwriteで発生させる。全出力bytes、最終state、metadata、warmup/gap、
共有FFT、各poll上限、寿命を独立した保存理論/現行値へ照合する。
source/runner/binaryが比較中に変わった場合は合格reportを作らない。
最終結果と失敗・中断は[進捗](../status.md)に記録する。

前後方向SOS/応答と6 rate境界は従来pure adapterの回帰。
取得schedulerへ接続したのは因果状態だけで、SOS全区間warmupは維持する。
Qt/派生Trigger保存、f32/chain/SOS gap回復、backend共通化/全tap、物理clock、
10分/負荷/他OS/配布と008-A全体は未完了。将来の公開型/ABIや採用ライブラリを固定しない。
