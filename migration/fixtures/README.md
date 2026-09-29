# FFT参照fixture v1

MIG-003-A、2026-09-30。契約は[数値v0.1](../contracts/numerics.md)。
Rust候補や製品UIの試験ではなく、現行FFT・窓と独立理論の比較用データ。
基準sourceは`9fd79958f6a8bbae6808813d3704617612e6d26c`。

MIG-003-Bの4/8ch・route・履歴・校正/保存は別の[コア契約fixture v1](core-v1.md)を参照。
以下は003-Aの保存仕様・結果で、既存の入力・期待値は変更していない。

## 実装と保存形式

[参照runner](../../scripts/migration_fft_reference.py)が現行`FFTManager.rfft/irfft/rfftfreq`と
`get_cached_window(..., fftbins=False)`を呼ぶ。
[理論oracle](../../scripts/migration_fft_oracle.py)は製品DSPやFFTをimportせず、
cosine/DC/Nyquistの有限幾何級数とHannの周波数シフトから`X/N`を求める。
impulseは全binが`1/N`、Hannのn=0は0、無音は0。
小さいNの直接DFT、手計算できるpeak/RMS/PSD積分のテストでoracleも照合する。

- `manifest.json`にはschema/契約版、参照commit、sourceとrunner/oracleのSHA-256、全導入依存版、
  OS/CPU/Python、FFT backend/thread数、fixture一覧、数値尺度・許容差を保存。
- ケースごとにrate、論理channel ID、半開区間、Timebase、identity route、tap、未校正FS、validityを固定。
  このmetadataはFFT入力の記述であり、route/trigger/historyの動作検証は003-Bで行う。
- `.bin`はヘッダなしlittle-endian IEEE754、C順。入力は`[frame, channel]`。
  complexは`[bin, channel, real/imag]`。各ファイルのbytesのSHA-256、dtype/shape/順序/由来をmanifestで指定する。
- 入力、理論値、現行値を別ファイルに保存。通常の検査は保存入力を読み、sin/seedから作り直さない。
  peak/PSD/RMS・Parsevalは契約adapterによる算出であり、製品の同名表示関数を呼んだ結果とは区別する。
- f32は量子化済みの別入力と実際のf32 FFT/inverse。理論FFTは量子化前の解析式なのでf32の許容差で比較する。
  時間RMSと窓付きpowerは保存済み入力に対する有限和。現行Spectrumの窓によるf64昇格とは別経路。
- phaseは閾値以上だけ周期差で、dBは契約のレベル以上だけ比較する。閾値以下はcomplex/線形比較とし、
  phase summaryに`null`とreasonを残す。NaNを一致扱いしない。

runnerはQt/pyqtgraph/sounddevice/AudioEngineをimportしていないことを検査する。
FFT wisdomは空の一時ディレクトリへ分離し、`FFTW_ESTIMATE`・1 threadに固定する。
NumPyへの暗黙fallbackは拒否する。性能protocolの4 threadとは用途が異なり、性能比較には使わない。
再検査は配列hash、版、dtype/shape、ID/metadataと数値を検査し、fixtureを書き換えない。
生成は明示コマンドで**存在しない出力ディレクトリ**へだけ許可する。

## ケースと結果

| 保存先 | ケース | 保存するもの |
| --- | --- | --- |
| [小規模manifest](fft-v1/manifest.json)と同ディレクトリ | 14件。AC01の2ch×矩形/Hann×f64/f32、DC/Nyquist/impulse/無音×矩形/Hann、A=0.25 tone、奇数4095の最終bin | 全入力と理論/現行配列、約6 MiB |
| [拡張manifest](fft-extended-v1.manifest.json) | 6件。N=24000/48000/4194304×矩形/Hann、A=0.25・k=37 | 生成式と全配列hash/shape、代表スカラー/誤差。約651 MiBの配列は`.migration-local/fft-extended-v1/` |
| [小規模run](runs/2026-09-30-intel-small.json)・[拡張run](runs/2026-09-30-intel-extended.json) | 同じ固定環境で保存bytesから再検査、20件成功 | 実行環境、manifest hash、各誤差、既知差、検査全体の時間/プロセスpeak RSS |

小規模runは1.388秒・peak RSS約99.4 MiB、拡張runは8.724秒・約1054.1 MiB。
ファイル読込・理論生成・参照計算・比較を含む単発の診断値で、FFT単体やsteady-stateの性能ではない。
f64の最大`X/N`複素誤差は約`1.34e-13`、f32は約`2.83e-9`、最大phase差は約`7.97e-9 rad`。
窓/周波数軸、inverse、peak/RMS、PSDと時間powerの照合も各契約許容差内。
AC01は2ch部分、AC04は参照fixture側まで。候補実装の合格を意味しない。

## 現行表示の既知差

`SpectrumAnalyzer._compute_standard`だけを元sourceのASTから**本体を変えずに**コンパイルする。
明示state（Left、平均0、矩形窓）と校正offset=0のadapterを渡し、GUIモジュール/engineは生成しない。
これは実際の計算メソッドの参照であり、画面や計測session全体の同等性検証ではない。
単ch入力は現行メソッドの2ch境界へ複製する。製品のDSP/表示コードは修正していない。

DCとNyquist、振幅0.125について両方同じ結果:

| 経路 | 理論 | 現行 | 差 |
| --- | --- | --- | --- |
| Spectrum、dBFS peak | -18.06179974 dBFS | -12.04119983 dBFS | +6.02059991 dB（endpointも2倍） |
| Spectrum、dBV、1 V/FS | -18.06179974 dBV RMS | -15.05149978 dBV | +3.01029996 dB（2倍の後に√2で割る） |
| PSDラベル、ASDの20 log10 | -28.75061263 dB | -25.74031268 dB | +3.01029996 dB（endpointのASDが√2倍） |

PSDの行はN=4096、Fs=48000、単位FS/√Hz。現行ラベル名を新コアのpower/Hzの定義と混同しない。
DC/NyquistのRMSに一律√2を適用しないことを、理論側では維持する。
現行の20〜20000 Hz Overall RMS、平均状態、DPSS、cross、実profileの校正は今回の参照範囲外。

## 再実行

作業ルートで実行する。通常はfixtureを生成し直さず検査する。

```bash
./.venv/bin/python scripts/migration_fft_reference.py verify
./.venv/bin/pytest -q tests/logic_verification/test_migration_fft_reference.py
```

既定ではPython/依存/OS/CPU情報の違いも拒否する。他の環境で保存bytesに対する数値比較だけをする場合は、
明示的に`--portable`を指定する。結果は`portable-numerical-comparison`となり、同一参照環境の再現とは区別される。
source/runner hash、契約、配列hash/shape、許容差はportableでも緩めない。

```bash
./.venv/bin/python scripts/migration_fft_reference.py verify --portable
```

同じ環境で再生成を調べる場合は新しいディレクトリを指定する。生成済み出力を再利用する場合は`verify`だけを実行する。
拡張ケースは保存したmanifestとの一致も必須。異なる依存版等で入力bytesのhashが変わった場合は失敗を保持し、
元の配列を取得するか、参照更新の理由を決定記録へ残す。期待値を自動で差し替えない。

```bash
./.venv/bin/python scripts/migration_fft_reference.py generate --output .migration-local/fft-reproduce-v1
./.venv/bin/python scripts/migration_fft_reference.py verify --fixtures .migration-local/fft-reproduce-v1 --baseline migration/fixtures/fft-v1/manifest.json
./.venv/bin/python scripts/migration_fft_reference.py generate --suite extended --output .migration-local/fft-extended-v1
./.venv/bin/python scripts/migration_fft_reference.py verify --fixtures .migration-local/fft-extended-v1 --baseline migration/fixtures/fft-extended-v1.manifest.json
```

`verify --report <新規ファイル>`で実行記録を保存できる。fixture内への書込と既存reportの上書きは拒否する。
拡張配列はGit管理外なので、他環境への移動やworktree退役前に必要なら明示的にアーカイブする。
