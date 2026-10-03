# 0014: 取得queueから履歴・共有FFTへの接続

日付: 2026-10-01。対象: MIG-005-A/B、P02/P03/P15、AC01/05/07/09。
状態: 評価用input.raw境界。Rust/QML採用・製品backendの置換は未決定。

## 判断と責務

[取得queue](../../native/audio-core/src/lib.rs)を
[単一所有のAcquisition worker](../../native/graph-core/src/acquisition.rs)へ接続する。
workerはqueueの唯一のconsumer、bounded履歴、固定N/hopのFFT scheduler、graphを所有する。
呼出側の取得loopがpollし、表示のtake_latestとは独立して全完成窓を解析する。
callbackは従来の事前確保atomic queueへのwriteだけ。graph構築、FFT、JSON/保存、解放をcallbackへ移さない。
新しい外部crateは追加せず、Cargo lockの変更はaudio/graph間のローカル依存だけ。

IoFormatのinput ID/portを明示して、deviceのframe-major配列から論理channelを選択・並替えする。
入力専用のinput.rawだけを対象とする。f32/f64の元bits、絶対frame位置、backend flags/secondsを保持する。
Timebaseのrate/clock/generationは設定を保持し、原点・不確かさはunknown。
backendのhost推定secondsを正確なdevice原点やclock同期の証拠へ昇格しない。

pollごとのdequeue数と完成窓数を別に制限し、大きなgapの全窓を一度に走査しない。
一回のpollは最大8192 delivery、4096窓。実CPAL診断は1024 delivery/16窓、履歴8192 frame。
履歴のnumeric bytes/span上限は既存HistoryLimits。外部snapshotの保持量や全process RSSの保証ではない。

## 欠落・世代・寿命

queue overflowの半開gapをHistoryへ明示する。末尾gapもacquired_untilを進め、pendingと区別する。
欠落窓は数値を作らず、区間/reasonをreportへ返す。非有限入力はchannelごとのnonfinite、
未解釈のbackend flagsは元flagsとunsupportedを保持し、無効FFTを正常なゼロ値にしない。

欠落時のGraph::invalidate_sourceは未読表示・cache・独立平均をresetし、予約済みの旧jobもfenceする。
既に外部で保持されたsnapshotは変えない。次の有効窓は新しい平均を開始する。
表示更新の省略で取得gapを作らず、内部の独立した常駐購読も作らない。
2viewを閉じても保存tokenだけで解析を続け、最後のtokenでFFT node/cacheを回収する。
取得queue/履歴は明示stopまたはworker破棄まで継続する。

restartは新queue/format/history/keyを先に検証し、同一Streamのより新しい世代だけを受け付ける。
成功後に旧graph publicationをfenceし、旧callback queueを切り離す。各購読は新keyへ明示reconfigureする。
失敗したrestartは現queue/履歴/未読結果を変更しない。
worker処理の失敗はFailed(reason)とし、queue/履歴/demandを解放する。stopは冪等。
backendのPreparing/Stopping/再オープン全状態の製品schedulerとは分ける。

## 検証と後続

[独立runner](../../scripts/migration_audio_graph.py)は003-Bの4/8ch f32/f64入力を、
identityと逆順bindingの計8件でqueue→履歴→共有FFTへ通す。期待値は候補processへ渡さない。
poll raw/履歴/停止後に保持したsnapshotは期待するport順の元bytesと完全一致し、
FFTは保存理論/現行値へ既存許容差で比較する。2view＋保存tokenの評価1回と回収も確認する。
Rust試験はoverflow、巨大gapのpoll上限、backend flags、nonfinite、世代、失敗、並行overwriteを扱う。

CPAL診断の入力consumerもこのworkerへ置き換える。
[BlackHole runner](../../scripts/migration_audio_virtual.py)は元のPortAudio比較に加えて、
完成窓数＝数値窓数＝FFT評価数、2購読の同じallocation、unknown原点、停止後の回収を検査する。
Preparing中cancelもgraph/queue/履歴の停止まで通す。callback内の処理は変更しない。
最終件数とreportは[進捗](../status-history-2026-10-03.md#mig-005取得graph接続の成果と検証)を参照。

動的出力routeの配送、全tap、製品PortAudio共通adapter、独立した永続thread scheduler、
Qt表示、校正/保存sessionの実取得統合、clock写像、長時間、USB復帰・排他、他OSは未確認。
MIG-005全体、最小2chフロー、性能/採用の完了にしない。
