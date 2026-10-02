# 0021: Qt Trigger要求を解析ownerへ配送する

日付: 2026-10-01。状態: 評価用境界。Rust/QML採用・公開ABIの決定ではない。

## 判断

0020の同期取得APIを、display-coreのreplay/BlackHole解析threadから呼ぶ。
Qt側は8 KiB以下のtyped JSON要求と世代/revisionを送り、未処理操作一件のmailboxへ配送する。
GUI/callbackで履歴queryやFFTを実行せず、通常graphへ過去窓を再公開しない。
pendingは明示retry、gapは欠落区間、completeは両view共通のowned result/projectionとして返す。

releaseは制御側で古い公開をfenceし、cache解除をownerへ配送する。
stopは未完成要求をcancelledにし、新世代はmailboxを初期化する。
完成snapshotは外部所有のまま不変で、分離/停止/再開/Backend破棄で書き換えない。
Qt Bridgeの共通changed通知もあるため、QMLはencoded文字列の変更を介して保持objectを一度だけ凍結する。

## 範囲と代償

一つのactive要求・一件の未処理操作・一件の追加raw cacheまで。
二つの表示は同じcaptureを保持する。別metadataの同一区間要求はrawを共有する。
要求中/解除処理中の新しい操作はbusyを返す。複数要求を無制限に蓄積しない。
履歴は8窓に制限する。完成MeasurementResultはArcで共有し、表示は必要な軸/peak列だけを読む。
同期FFT/result生成/診断file保存は解析ownerの負荷であり、RT性能合格の根拠にしない。
外部snapshotとprocess RSSはmailbox/cacheの容量とは別の寿命を持つ。

手動sampleイベントは元Timebaseの明示位置。GUI受信時刻から位置を算出せず、
clock原点/写像と絶対電圧はunknown/uncalibratedのまま維持する。
検出器、arm/cancel、前段filter、外部clock、製品校正・保存互換、長時間/他OSは別タスク。

## 検証と引き継ぎ

[手順](../../native/trigger-display.md)のrunnerは保存元bytes/BlackHole取得窓を独立NumPy oracleへ比較する。
全result metadataと数値、pending/gap非数値、raw共有、hold/retry/release、分離/zoom、
停止/世代/破棄後の不変性、翻訳/サイズ/PNG/stream回収を両Qt方式で検査する。
成功件数と失敗run、source/hash、command/log、未実施範囲は[進捗](../status.md)に記録する。

開発スモークではQt内部contentItemの画像取得失敗と、Qt Bridgeの共通通知によるhold object再生成を検出した。
既存QML canvasから撮影し、encoded文字列の変更でobjectを生成するよう修正した。
release直後はownerによるcache解除が残るため、次の要求はbusy解消後に配送する検査へ変更した。
最初の型境界とClippyの大きなenum指摘はSerialize/Arc要求へ修正し、失敗logを保持する。
最初の全72実行では操作/数値/寿命は成功したが、32画像のregion検査が失敗した。
dock直後の未反映geometryを記録していたため、viewとpaneの実サイズ一致を待ってから撮影・座標記録する。
全件再検査のv2は71成功、8ch f64/Qt Bridge一件が320 ms GUI停止中のFFT評価二窓の条件で失敗した。
原因は特定していない。Trigger診断は640 msへ固定し、実評価増分を保存するv3として再実行する。
元runを性能合格へ書き換えず、短い診断と定常throughput/通知遅延予算の判断を分ける。

最初のBlackHole 18実行は11成功、7失敗。二度目の同一区間要求が2窓の履歴から失効し、
8chでは解析ownerが取得queueに追いつかずgapも記録した。
履歴を8窓へ広げ、通常表示のたびに全数値列をJSON化していた処理を必要列の読取りへ変更した。
Triggerの完成resultもcloneせずArcを共有する。元の失敗reportを保持し、
同じgap/error判定と独立oracleで保存入力/BlackHoleを再検査する。
