# 0015: bounded control-to-callback output route delivery

日付: 2026-10-01。対象: MIG-005-Aの動的出力route。状態: 検証候補、採用未決定。
[コア契約](../contracts/core.md#routingとmonitortap)、[手順](../../native/dynamic-route.md)を参照。

## 判断

005-graphで取得queue→履歴→共有FFTを接続した。次に、既存RouteControlの同期モデルを
音声callbackへ直接共有せず、制御で検証したRouteを固定容量のmailboxで配送する。
P1のblock境界変更/実sample ackを、実callbackで検査するための追加である。
元のRoute、保存fixture、gain演算、製品Python DSP/UI、Cargo依存/lockは変更しない。

1 endpointにつきcontrol/callback各1 owner。handleはClone/Syncを持たず、音声をreader待ちにしない。
未確認1件はbusyとして返し、暗黙の上書きや要求のcoalesceをしない。
固定16ch/256 termsをatomicに保存し、PENDINGのRelease/Acquireで完全なpayloadを公開する。
callbackはactive固定配列へcopyした後にAPPLIEDをReleaseする。
制御側はackをAcquireしてからslotを再使用する。callbackで元RouteのVec/String/Arcを交換・解放しない。
この候補はunsafe、lock、待機loopを使わない。

source/output bindingとgenerationはendpointに固定する。
変更要求には有限gain、異なるrevision、要求位置の順序、同じoutput ID順を求める。
拒否はtransactional。合法な要求を受けても、callbackの全block検証が失敗すれば適用/ack/位置を変えない。
要求位置未満のblockには適用せず、遅い要求も実適用位置を保持する。
callbackからは数値sequenceだけを返し、文字列revisionは制御側で解決する。
close後の進行中blockの完了を許し、callback破棄後に未適用要求をcancelledとして一度だけ返す。
新generationの開始では新endpointを作り、旧要求や係数を再利用しない。

## 検証境界

保存4/8ch f32の元bytesを12件のblock/ack条件で通し、独立sampleモデルと全mixed/device bytesを照合する。
f64元bytesは既存queue回帰で保持するが、動的callbackはf32のみ。
Rustは無効/旧世代/busy/遅延/停止/再開/16ch/加算順と2,000件の同時配送を検査する。
BlackHoleの2→2/4→16/8→16を各3回取得し、3変更とPreparing中の保留cancelを検査する。
実source/hash/argv/log/終了コードと結果は[進捗](../status.md)へ記録する。

出力ackの位置はoutput callback内のframe。入力/host clockへの写像はunknownのまま。
提出device bufferとraw入力を比較しても、物理出力/絶対遅延/校正の精度には置き換えない。
PortAudioとの動的比較、全tap graph購読、Qt、長時間、製品共通adapter、他OSは未完了。
既存の003-B契約/期待値を変更しておらず、MIG-005全体やP2/採用の完了とは分ける。
