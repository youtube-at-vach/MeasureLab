# 数値と参照データの契約 v0.1

MIG-002、2026-09-29。対象はP1/P2の小さなフロー。全41機能の数値仕様を一律に置き換えない。
以下の許容差は**検証開始時の基準**で、達成済みの実測値ではない。
旧版との比較と理論値との比較を別項目にし、不一致を期待値の自動更新で解消しない。

## 参照基準と再現性

Python参照コミットは`9fd79958f6a8bbae6808813d3704617612e6d26c`。
MIG-001後のsrcは同一。実際に使うソースはファイルのSHA-256もmanifestへ記録し、
基準と異なる場合は参照生成を止めて意図を確認する。移行用adapterとgenerator自体の版/hashも記録する。

fixtureにはschema version、fixture ID、目的、契約版、入力/期待配列のSHA-256、dtype/shape/layout/byte order、
rate、ch ID、区間、seed/生成式/パラメータ、Timebase、route/tap、校正、validity、
期待値の由来（理論/現行関数/新契約モデル）、比較尺度・許容差を持たせる。
環境はPython/OS/CPU、NumPy/SciPy/pyFFTW/PyWavelets/netCDF4等の全導入版、FFT backend/thread数を保存する。

MIG-003-Aで[FFT参照fixture v1](../fixtures/README.md)を作成。数値契約の変更はなく、
同ページに実行済み範囲、source固定、保存形式、現行表示の既知差と再現コマンドを記録した。

標準入力はlittle-endian IEEE754 f64のframe-major配列。f32ケースは別配列・別期待値で、
quantize済み入力を双方へ同一に渡す。complex値は実部/虚部を明示し、言語固有のpickleを使わない。
小さな配列はレビューできるJSONでもよい。SHA-256はシリアライズ後のファイルbytesへ適用する。
sinや乱数生成は環境差があり得るため、後続実装は保存された入力bytesを使う。
seedだけで同一性を主張しない。大規模データは生成手順とhashを固定し、小さな代表値をGitへ残す。

参照ランナーはGUI/QApplication/deviceを起動せず、現行の純粋関数または明示的なadapterを呼ぶ。
Qt importを要するwidget計算は無理に新しいNumPy式へ置き換えて「現行参照」と呼ばない。
基準実装の式、理論式、新契約のoracleを区別して保存する。期待値の再生成は通常の検査から分離する。

## 最初のFFT・振幅・RMS

実数列 `x[n]`、窓 `w[n]`、長さNに対し、forwardは符号が負の無正規化DFT:
`X[k] = sum_n(x[n] w[n] exp(-i 2πkn/N))`。inverseは1/N正規化。
real FFTはk=0〜floor(N/2)を返す。Hz軸は`k × Fs/N`、単位補正前のnominal rateも保持する。
windowは係数そのものとperiodic/symmetricを固定。初期ケースはboxcarとsymmetric Hann
`w[n] = 0.5 - 0.5 cos(2πn/(N-1))`（N≥3）。Nが小さすぎる/窓和が0の条件は拒否する。

| 量 | 定義 |
| --- | --- |
| one-sided係数 d[k] | DCは1、偶数NのNyquistは1、その他は2。奇数Nの最終binは2 |
| tone peak振幅 | `d[k] × abs(X[k]) / sum(w)`。coherent tone向け。漏れのあるtoneのpeak推定は別契約 |
| PSD | `d[k] × abs(X[k])² / (Fs × sum(w²))`、FS²/Hz |
| ASD | sqrt(PSD)、FS/√Hz。現行UIのPSDラベルとの対応をadapterに記録 |
| 時間RMS | `sqrt(sum(x²)/N)`。無窓の元系列に対して定義 |
| 窓付きpower照合 | `sum(PSD) × Fs/N = sum((xw)²)/sum(w²)`。任意窓で無窓RMSと等しいとはしない |
| coherent正弦のRMS | DC/Nyquist以外ではpeak/√2。DCとNyquistの実数系列へ一律に√2を適用しない |
| dBFS peak / RMS | それぞれの線形量に20 log10を適用し、種別を明示。power/PSDは10 log10 |
| phase | atan2(Im,Re)、radを基準。差分は2π周期で最短差。ゼロ振幅のphaseは未定義 |
| cross | 初期の伝達関数検証は`conj(X_ref) × X_meas`、正の位相差はmeas進み。現行Spectrumの`X_left × conj(X_right)`とは参照向きが違い得る |

理論fixtureはcosineを使い、`A cos(2πkn/N + φ)`のpositive-bin位相をφとする。
rect、N=4096、k=37、A=0.25のpeakは0.25、RMSは0.25/√2。
DCは定数0.125、Nyquistは`0.125 × (-1)^n`、impulseはn=0だけ1。
無音・奇数N=4095・非2冪N=24000/48000・N=4194304を別ケースにする。
大規模ケースの許容差も同じ正規化尺度で測り、時間/RSSを別記録する。

現行Spectrumの標準表示は全binへ2倍係数を掛け、物理単位では一律√2で割る経路がある。
DC/Nyquistの理論値との差をMIG-003で数値化し、「既知差」として両方保存する。
旧表示との完全一致が必要な箇所は互換変換で明示し、新コアのDFTの定義を変えない。
現行の20〜20000 HzのOverall RMS、平均、DPSS、cross等もこの最小仕様とは別に比較する。

## 比較尺度と初期許容差

スカラー/配列は各要素で`abs(actual-expected) <= atol + rtol × abs(expected)`。
complexは複素差の絶対値。配列shape/順序、ID、整数位置、状態、validity、schemaは厳密一致。
NaN同士を合格にしない。理論的に未定義な量はnullとreasonの一致で確認する。

| 対象 | atol / rtol | 適用範囲 |
| --- | --- | --- |
| 窓、route/mix、校正scale、3-tap FIR | 1e-12 / 1e-12 | FSまたは定義した線形単位、f64 |
| FFT | 2e-11 / 1e-9 | X/Nのcomplex値。極大FFTを含む。生Xの絶対値を同じ閾値で比較しない |
| peak/RMS、積分power、PSD | 2e-11 / 1e-9 | 各線形量、f64。PSDは積分powerの比較も必須 |
| phase | 1e-7 rad / 0 | peak振幅1e-8 FS以上。以下はcomplex値だけ比較 |
| dB表示 | 1e-5 dB / 0 | -120 dBFS以上。以下は線形絶対誤差と床の状態を比較 |
| f32経路 | 2e-6 / 2e-5 | 正規化FFT/FS/RMS。f64解析の許容差をこれで緩めない |
| f32のphase/dB | 1e-4 rad、1e-3 dB / 0 | -80 dBFS以上。低レベルは線形比較 |
| 現行polyphase resample | 1e-10 / 1e-8 | 同一係数・同一入力のf64参照値。独立理論との通過帯域RMS差は0.01 FS、peak周波数は1 Hz以下（既存1秒/1 kHzケース） |
| 代表filterの係数/出力 | 1e-10 / 1e-8 | f64、係数・初期state・端点が同じ条件。帯域/位相特性も別照合 |

整数遅延やtrigger位置を浮動小数の許容差で救済しない。分数写像は有理数で一致。
高度なfit、wavelet、心理音響、ノイズ統計等はこの許容差を無条件に流用せず、
既存試験・尺度・入力範囲・規格/近似の別を個別契約へ追加してから合格にする。
閾値変更は決定記録とfixture版変更を要し、失敗runと変更理由を保存する。

## 最小レート変換

時刻/validity検証には独立して理論値を計算できる因果FIRを使う。
48 kHz→24 kHz、`h=[1/4, 1/2, 1/4]`、`y[m]=Σ(j=0..2) h[j] x[2m-j]`。
出力長はceil(N/2)、負位置は計算上0だが出力m=0をwarmupとして記録。tailの自動flushはしない。
これは契約検証用であり、製品の高品質resamplerを選定した意味ではない。

- 出力frame mの時刻は入力の2m。signal遅延は入力1sample＝出力1/2sample。
- 入力trigger位置1024の時刻は出力512。遅延した波形特徴の中心は512.5。両者を混同しない。
- 入力gap `[100,104)` は出力 `[50,53)`を無効にする（support `[2m-2,2m]`の交差）。
- impulse・DC・低周波cosineで直接有限和と比較。分割1/127/256/不規則chunkでもstate/位相を保持して同じ結果。
- 現行`AudioCalc.resample`のKaiser polyphaseは別fixtureで比較し、係数・padding・遅延補償を固定する。
  source/target rate≤0で入力を返す現行挙動は新契約の拒否動作と分けて保存する。

## 校正の最小ケース

チャンネルcごとに`V_per_FS = 1 + c/4`を割り当て、並替え後もIDに追随することを確認する。
入力相対波形×V_per_FSがV、coherent sineのV RMSからdBVを求める。
profile未設定ではFS値を残し、VとSPLはuncalibrated。周波数補正1と1.0001の軸を区別する。
profileを切替えた後も保存済みsnapshotの値・revision・軸は不変。
SPLと周波数/位相mapの個別比較は現行CalibrationManagerのfixtureを追加して行う。
