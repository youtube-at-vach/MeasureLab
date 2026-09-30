# 0007: Pure Rust FFT candidate against fixed reference bytes

日付: 2026-09-30。MIG-006-A。[契約v0.1](../contracts/numerics.md)の変更なし。
開始HEADは`e0b992ce36b7eec562059bc31891378f37d01814`。
`codex/migration-004-b`のremote一致・cleanを確認し、同じworktreeで`codex/migration-006-a`へ分岐した。

## 判断

[RealFFT 3.5.0の公式資料](https://docs.rs/realfft/3.5.0/realfft/)のreal forward/inverseと
無正規化仕様を確認し、候補をRealFFT 3.5.0 / RustFFT 6.4.1へ固定した。
今回の目的は採用判断前の数値比較。FFTW等とのrelease性能比較や最終ライブラリ選定は行っていない。

GUIから独立した`native/dsp-core`へf32/f64のFFT/窓/単位/PSDを実装した。
ファイルadapterの入力は003-A/Bの元のlittle-endian/frame-major bytes。
Rust側でsin/seedから再生成せず、Python側で候補のFFTを代行しない。
参照fixtureの入力・期待値・許容差、現行DSP/UIは変更しない。

## 数値と所有権

forwardは負符号の無正規化DFT、比較は`X/N`、inverseは`1/N`。
DC/偶数Nyquistと奇数最終binを区別し、FS peak/coherent bin RMS/PSD/ASDを明示する。
窓と正規化・有限和はf64。f32の窓乗算/FFT/inverseは実際にf32で、f64 FFTへの昇格を使わない。
coherent bin RMSは任意信号の総RMSではない。

plan/scratchは単一の`Analyzer`が所有し、各結果は独立したowned配列。
plan再利用で前の結果が変化せず、無音への切替えで前の値が残らないことを検査した。
これは006-Bの共有key/result ID/購読token/cache/最後の解除の検証ではない。
allocationと同期処理を行う解析worker用で、callbackへ移さない。

## 確認結果

[全24ケースのreport](../fixtures/runs/2026-09-30-intel-candidate-fft.json)に、
入力/manifest、source/lock/実行物のhash、全コマンドのgzip log、環境と誤差を保存した。
手順は[native FFT](../../native/fft-candidate.md)。

| 対象 | 実行範囲 |
| --- | --- |
| AC01のFFT部分 | 2/4/8ch、f32/f64、保存済みID順・bin・peak/RMS・phase。物理channelやrouteの保証ではない |
| AC04の保存コーパス | DC/Nyquist/impulse/無音、4095、24000/48000、4194304、boxcar/symmetric Hann。理論/現行の両参照、PSD積分、inverse |
| f32の範囲 | 保存済みN=4096の2/4/8ch。拡張/endpoint全構成のf32参照fixtureは今回追加していない |
| 異常系 | 不正rate/schema/window/dtype/次元/ID、非有限入力/結果、入力hash、出力shape/ID/単位/有限性、report上書き拒否 |
| 非Qt CI | pure worker/DSPのRust test/ClippyとNumPyだけのportable比較18件を追加。拡張配列はCIへ配布していない |

現行SpectrumのDC/Nyquist表示の約+6.0206 dB peak、約+3.0103 dB RMS/ASD差は残した。
新候補の契約値と旧表示の差を別記録し、DFT定義を互換表示へ合わせて変更しない。

全24件は理論/現行の両方へ合格。f64の最大正規化FFT差は約1.33e-13、
f32は約8.35e-9、inverse最大差は約5.83e-16 / 1.04e-7。
phase最大差は約1.84e-9 / 5.26e-8 rad。すべて開始時の許容差内。
[最小Python環境のreport](../fixtures/runs/2026-09-30-intel-candidate-minimal.json)は
NumPyとpipのみでportable比較18件に成功。LinuxでのGitHub実行は未確認。
Cargo workspaceのbuild/fmt/Clippyと、DSP5件・模擬worker5件のRustテストも成功。
Cargo.lockは新規9依存とDSPクレートの追加だけで、既存依存版は変更していない。
[既存Qtの回帰report](../qt/2026-09-30-intel-006-a-regression.json)は両方式の寿命検査各1回に成功。
既存CXX-Qtの空init archive/重複rpathのlink警告は残る。ソースlint警告はない。

## 開発反復の扱い

専用コピーで同じ係数分岐変更を5回適用し、各回Rustテストと全24比較までを測る。
setup/warmup、base復帰build、依存取得を測定区間から分ける。
debug・CPU build並列数4・FFT1 threadで、releaseの実行性能や言語だけの効果には使わない。
Python同等変更とGUI波及は未確認。

初回の試行は他のbuild/testと重なったため診断runとして分け、
採用する反復runは他のagent build/testを止めて再実行した。
patch作成は単一の編集操作だが、独立した作成時間は計測していない。
実装中は`ToPrimitive`の不足でコンパイル1回、Clippyのiterator指摘で2回失敗し、修正した。
これらは検証待ち時間へ混ぜず、開発上の修正として記録する。

[採用run](../benchmarks/results/2026-09-30-006-a-intel.json)の5値は
26.093 / 24.544 / 24.770 / 24.493 / 24.453秒。
中央値24.544秒、min/max 24.453 / 26.093秒、母標準偏差0.621秒。
5回ともDSPを再コンパイルし、Rust5テストと24ケース比較が成功した。
warmupとbase復帰を含む161コマンドlogのgzip/hashと終了コード0を確認した。
絶対30秒の目安内だが、Python同等修正との速度比やAC16全体の合格には数えない。
他アプリの負荷・電源状態の時系列は未記録。
[並行作業と重なった診断run](../benchmarks/results/2026-09-30-006-a-development.json)も保持する。

## 残る範囲

Rust/QMLの採用、MIG-006全体、AC01の実音声経路、AC05〜07の共有graph、
trigger/history/validity、filter/rate、校正/export、実機、GUI、他OS、release/steady-stateは未完了。
004-Bの他OS/clean配布とLinux ICU修正後のGitHub CIも別の未確認事項として残す。
次は005-Aまたは006-Bへ進める。今回の候補を製品GUIや音声callbackへ接続しない。
