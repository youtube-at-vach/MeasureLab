# P0以降の受け入れ条件

MIG-002、2026-09-29。下表は試験の定義で、表そのものを合格の記録とはしない。
[コア](core.md)・[数値](numerics.md)・[性能条件](../benchmarks/protocol.md)を正本とする。
MIG-003は入力/期待値を用意し、MIG-005/006以降で候補実装を同じ入力に通す。

2026-09-30に003-Aの[AC01の2ch・AC04の参照fixture](../fixtures/README.md)を作成・理論照合済み。
続いて003-Bの[4/8chとコア契約fixture](../fixtures/core-v1.md)を作成・照合済み。
下表の候補実装に対する合格とは別で、003-Bの履歴は区間の可用性oracleまで。実バッファは006-Cで検証する。
006-Aで[純粋FFT候補24件](../decisions/0007-pure-fft-candidate.md)が保存済み理論/現行参照へ合格した。
AC01のFFT部分とAC04の保存コーパスの結果であり、物理I/O・共有graph・他のACの合格ではない。
006-Bで[pure共有graph](../decisions/0008-shared-fft-graph.md)のRust16テストと保存18ケースが合格した。
AC05/06とAC07のnode/cache/in-flight寿命まで。実音声・QML画面・保存sessionの統合は後続で検証する。

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
| AC15 | 小さなP2フローを10分、複数表示、保存、遅いGUI | データ欠落なし、表示遅延/CPU/RSSを記録、負荷超過は条件とgapを残す。性能予算で判定 | 007-B、008 |
| AC16 | clean/incremental/core編集/QML編集/package、対象OS起動 | 反復時間と失敗回数を保存。未実行OSを合格にしない。実機2chとpackageの記録が必要 | 004-B、005-B、006-A、007-B、008 |

AC01のfixtureでは配列順とは別の論理ID（例: `input.alpha`等）を明示する。
AC02のmixはFSで行い、異なるV/FSを持つ入力の物理単位を単純な一つの校正係数で表さない。
物理単位のmixが必要なら各channelへ校正を先に適用し、その演算順と単位を結果へ残す。
欠落・NaN・未校正等は正常ケースと別の期待metadataを持つ。期待値と実装を同じ関数で作らない。

## 最初のフローの終了条件

2ch生成 → 明示route → 取得/Timebase → 波形と共有FFT → Spectrum/heatmapの複数表示 → 校正付きCSV/JSON保存を通す。
最低限boxcar/Hann、peak/RMS/PSD、基本V/FS校正、開始/停止/失敗を含める。
保存データには元の区間・Timebase・trigger・tap・校正revision・validityを残す。
同じコアにAC01/02の4/8chを通す。単なる別のNumPy計算の合格で代替しない。

終了にはAC01〜16の対象結果、2ch実機loopback、対応OSの配布物起動、
window再生成/終了、cursor/zoom/画像保存、全言語UIサイズと操作評価、性能/反復速度の比較が必要。
実機振幅/遅延の閾値はdevice/校正/配線の条件とともに005-Bで測定前に決める。未定のまま実機合格にしない。
数値・時刻・validityの不正を速度改善で相殺しない。

P2最小フローの合格と41機能の移行完了は別。MIG-008で四つの方針を比較して判断する。
MIG-002だけでは実行性能、配布、技術採用、製品切替を決定しない。
