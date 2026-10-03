# MIG-008の受け入れ条件

更新: 2026-10-04。[評価計画](../../guide/RUST_QML_MIGRATION_PLAN.md)の範囲を適用する。
下表は契約試験の参照一覧。すべての構成を実装・再検証するチェックリストにはしない。
数値の意味と許容差は[コア](core.md)・[数値](numerics.md)・固定fixtureを維持する。
実施済み結果は[進捗](../status.md)、比較条件は[短い比較protocol](../benchmarks/protocol.md)。

## MIG-008に適用する範囲

| 契約 | 今回確認すること |
| --- | --- |
| AC01/02/04 | 2ch統合と同じcoreの保存4/8chを各1条件。FFT/窓/単位の既存参照結果を再利用 |
| AC03 | 対象フローの固定route、ChannelId/port対応。全動的route統合は延期 |
| AC05〜09 | 同一区間の共有FFT、Trigger/hold/release、購読解除、gap・世代を短い統合確認で検査 |
| AC10/14 | 固定filterを利用する場合だけ既存結果と対象回帰を利用。chain/SOS/全rateの追加は延期 |
| AC11 | 全MonitorTapの実装・検証は延期。今回使うinput.rawの位置と来歴を保持 |
| AC12/13 | V/FS校正、不変snapshot、CSV/JSONの値・来歴と再読込。開始/停止/再開、失敗、終了回収 |
| AC15/16 | 各30秒・1回の代表実行比較、core/表示編集の各1回。全OS配布・長時間試験は不要 |

## fixtureの最小セット

| ID | 入力・操作 | 合格条件 | 実装・検証タスク |
| --- | --- | --- | --- |
| AC01 | 2/4/8ch、Fs=48000、N=4096。chごとにk=[37,71,113,173,251,331,419,509]、A=(c+1)/32、φ=cπ/16のcosine | 各IDのbin・peak・RMS・phaseが理論と数値契約内。channel配列は固定長2でない | 003-A/B、005-A、006-A |
| AC02 | 4→2: y0=x3、y1=(x0+x2)/2。8→4: y0=x7、y1=x1、y2=(x2+x4)/2、y3=-x0。2→8: 交互複製を明示 | frameごとの値・ID・出力数が一致。校正は入力IDを追跡し、mix後の単位条件を検証 | 003-B、005-A |
| AC03 | route変更、未知ID、重複出力、次元不一致、gain NaN | 合法な変更のみ指定block境界で適用しack。無効設定で物理出力や既存routeを変更しない | 003-B、005-A |
| AC04 | DC/Nyquist/impulse/無音、奇数4095、24000/48000、4194304、rect/symmetric Hann | endpoint、正規化、PSD積分、inverseが数値契約内。旧表示との既知差を別記録 | 003-A、006-A |
| AC05 | 同じFFTをSpectrumとSpectrogram相当の2購読で要求 | 1区間につきFFT評価count=1、同じresult ID/区間/Timebase。単独購読と値が一致 | 006-B、007-A |
| AC06 | 一方だけwindow/hop/入力校正/世代を変更、表示色・単位だけ変更 | 信号条件の差でnode分離、表示条件だけならraw FFTを共有。旧結果は不変 | 006-B |
| AC07 | 2view+保存session→一つ閉じる→両view閉じる→session終了 | 必要なnodeのみ継続。最後の購読解除で停止/回収。遅いGUIは取得を妨げない | 004-A、006-B、008 |
| AC08 | event k=2048、pre=256/post=768、保持4096。2読者へ異なる時刻で通知 | 両方が `[1792,2816)`を取得。一方のreadで他を消費しない。保持を越えた場合は正確なgap | 003-B、006-C |
| AC09 | gap `[100,104)`、overflow、再開、別device clock | gap位置を詰めない。世代切替後に旧event/resultを適用しない。未知clock差はunsynchronized | 003-B、005-A、006-C |
| AC10 | 3-tap 48→24 kHz、trigger1024、gap、chunk分割変更 | trigger512、signal遅延0.5 output sample、gap `[50,53)`、warmup `[0,1)`。直接有限和と一致 | 003-C、006-D |
| AC11 | output.mixed / device_bufferを購読、mute/量子化を変更 | tapが示す位置だけが変化。mixedが非zeroでも物理出力の証拠にしない。muteでdevice buffer=0 | 003-B、005-A/B |
| AC12 | channel校正/並替え、profile変更、未校正、CSV/JSON保存 | ID/軸/単位/来歴/validity/trigger/routeを保持。旧結果不変、未校正を絶対値にしない、再読込一致 | 003-B、006-E、008 |
| AC13 | start→準備中stop、開始失敗、重複stop、画面再生成、終了 | 実状態のみ通知。callback/worker/token回収。失敗とcancelを正常完了にしない | 004-A、005-B、008 |
| AC14 | 既存polyphaseと代表SOS filterを同一入力/係数/stateで比較 | 理論と現行を別比較。端点、warmup、連続chunkに差があれば明示 | 003-C、006-D |
| AC15 | 代表2chフローを30秒・1回、2viewと保存 | CPU/RSS、表示応答、gap、停止結果を同条件Pythonと比較。長時間安定性は未確認 | 008-B |
| AC16 | core編集・表示編集を各1回 | 編集から確認までの時間・失敗を記録。既存build/package結果を再利用。Windows/ARMとclean配布はMIG-008後 | 008-B |

AC01のfixtureでは配列順とは別の論理ID（例: `input.alpha`等）を明示する。
AC02のmixはFSで行い、異なるV/FSを持つ入力の物理単位を単純な一つの校正係数で表さない。
物理単位のmixが必要なら各channelへ校正を先に適用し、その演算順と単位を結果へ残す。
欠落・NaN・未校正等は正常ケースと別の期待metadataを持つ。期待値と実装を同じ関数で作らない。

## 最初のフローの終了条件

2ch生成→固定route→取得/Timebase→波形・共有FFT→line/heatmap→校正付きCSV/JSONを通す。
boxcar/Hann、peak/RMS/PSD、基本V/FS校正、Trigger保持、開始/停止/失敗、購読解除と終了を含める。
保存には区間・Timebase・trigger・tap・校正revision・validityを残し、同じcoreの保存4/8chで回帰を確認する。

008-Bの短い比較を行い、008-Cで四案の方針・理由・重大な問題・未確認範囲を記録する。
Windows・ARM、全tap/profile/校正map、他OS配布、物理遅延/USB復帰は延期。
長時間試験は行わない。延期事項を成功とは扱わず、現在の対象範囲で判断する。
全41機能の移行、製品切替、全ACの全構成合格をMIG-008の完了条件にしない。
