# FIR・rate・SOS参照fixture v1

MIG-003-C、2026-09-30。対象は[数値契約](../contracts/numerics.md)のAC10/14参照側。
[manifest](filter-v1/manifest.json)と133ファイル（合計9,420,594 bytes）をGit対象に保存する。
既存の003-A/Bのfixture、現行DSP、契約の許容差は変更しない。

## ケースと由来

入力はlittle-endian f64、frame-major `[frames, 2]`、順序付きIDは`input.alpha` / `input.beta`。
信号はimpulseの振幅`[1, -0.5]`、DCのレベル`[0.25, -0.125]`、
cosineの振幅`[0.25, 0.125]`・位相`[0, 0.375]` rad。
後続実装には生成式からの再計算でなく、保存した入力bytesを渡す。

| 群 | 数 | 入力・固定条件 | 比較する値 |
| --- | --- | --- | --- |
| 最小FIR | 5 | 1031 frames、48→24 kHz、`[1/4,1/2,1/4]`。偶数/奇数位置impulse、DC、1 kHz cosine、gap付きcosine | 独立有限和と状態を持つ新契約モデル。warmup/gap、長さ、chunk一致、時刻/遅延の有理数写像 |
| 現行polyphase | 12 | 48→24、24→48、44.1→48、48→44.1 kHz × impulse/DC/1 kHz cosine。前二者129 frames、cosineは1秒 | 現行係数とsinc/Kaiser式、現行出力と中心を補償した有限和、cosineのRMS/peak周波数 |
| 代表SOS | 4 | 48 kHz、8次Butterworth lowpass、4 kHz cutoff。先頭/中央impulse、DCは1024 frames、1/12 kHz cosineは8192 frames | 現行前後処理と独立差分方程式、因果出力/最終state、chunk一致、複素応答/Butterworth振幅/位相 |
| rate境界 | 6 | source/targetの0/負値5件、同一rate1件 | 現行の同一object返却と新契約の正rate検査を区別。入力値も保持 |

[ケース定義](../../scripts/migration_filter_cases.py)、[独立oracle](../../scripts/migration_filter_oracle.py)、
[参照runner](../../scripts/migration_filter_reference.py)、[テスト](../../tests/logic_verification/test_migration_filter_reference.py)を使用する。

## 最小FIRの時刻・欠落

`y[m] = Σ h[j] x[2m-j]`、出力長ceil(N/2)、tailをflushしない。
最初の出力は数値計算上の負位置0を使うが、`warmup [0,1)`を保持する。
gapは入力blockの絶対位置の飛びとして状態モデルに渡す。欠落後を詰めず、
計算用の0を使う全出力に`gap`を付け、無効値を有効な測定として扱わない。
`[100,104)`の影響は厳密に出力`[50,53)`。

出力frame mの時刻は入力2m、信号遅延は入力1sample＝出力1/2sample。
入力trigger1024は出力512、遅延した波形特徴の中心は512.5。丸めない。
出力は別Stream/Timebase、同じclock由来、親・世代・比・原点写像・filter revisionを持つ。
処理遅延は未測定のnullとreasonを保存し、信号遅延から推定しない。

whole、1、127、256、`[3,128,1,7,256,2]`の各chunkで出力とvalidityを照合する。
テストでは4ch、異なる長さ、奇偶gap、複数gap、入力の事後変更、重複/逆順・不正blockの拒否も確認。
末尾gapだけで終わる場合の終端通知、世代切替、実際のgraphへの組込みはこのモデルに含めない。

## polyphaseの係数・端点

現行`AudioCalc.resample`をそのまま呼ぶ。既約比up/down、係数長`20×max(up,down)+1`、
Kaiser beta=5、cutoff=`1/max(up,down)`（Nyquist比）、DC正規化を固定する。
独立係数式はsincとI0から作り、SciPyのfirwinを使わない。
現行出力に対する有限和は次の式で、SciPyのresample_poly/upfirdnを使わない。

```text
half = (len(h)-1)/2
y[m,c] = up × Σ_n x[n,c] h[m×down + half - n×up]
```

範囲外入力/係数は0、長さはceil(N×up/down)。現行の係数前padding、出力先頭の除去数、
補償前の信号遅延と補償済み状態をmanifestへ残す。
入力不足を検知するvalidity APIは現行関数にはないため、新契約のgap合格とは扱わない。

## SOSのstate・位相

製品の`_get_butter_sos`から係数を取得し、`AudioCalc.lowpass_filter`を各chに直接適用する。
この製品APIのaxisは末尾なので、2次元frame-majorをそのまま渡さない。
既定のodd extension、padlen=27、拡張端点に合わせた定常初期状態と前後処理を固定する。
独立oracleはdirect form Iのスカラー差分方程式と端点のDC定常履歴から計算し、
SciPyのsosfilt/filtfilt/zi生成を使わない。

別にSciPyの`sosfilt`へ同じSOSとzero stateを渡し、因果出力・最終state・各chunk分割を照合する。
最終DF-II stateは独立oracleの入力/出力履歴から算出する。
これは現行係数の因果参照であり、現行AudioCalcがstateを受け渡すAPIを提供するという意味ではない。
zero stateの過渡応答を保存し、任意の時間経過を理由にwarmup解除とはしない。
IIRのgap後の回復規則は今回の契約外。

0/1/4/12/20 kHzの複素応答と、双一次変換後のButterworth振幅式を比較する。
cosineは両端1024 framesを明示して除き、因果処理の振幅/位相と前後処理の二乗振幅/ゼロ位相も確認する。

## 結果と既知差

[固定環境の実行report](runs/2026-09-30-intel-filter.json)に全ケースの誤差と診断値を保存。
Python 3.12.14、NumPy 2.2.6、SciPy 1.18.1、macOS Intel。
最大差はFIR約2.78e-17、polyphase約1.11e-16、SOS約4.77e-14で契約内。
1秒/1 kHzのpolyphaseではRMS差の最大は約0.000175 FS、peak周波数は全chで1000 Hz。

独立した短い呼出しを連結すると、現行の一括処理とは違う結果になる。
以下は不具合修正やストリーミング対応の合格ではなく、現在のAPI境界の記録。

| 1 kHz cosineを分割した経路 | wholeのframes | 独立呼出し連結のframes | 共通先頭区間の最大絶対差 FS |
| --- | --- | --- | --- |
| polyphase 48→24 kHz、127 frames/call | 24000 | 24189 | 約0.505 |
| polyphase 24→48 kHz、127 frames/call | 48000 | 48000 | 約0.125 |
| polyphase 44.1→48 kHz、127 frames/call | 48000 | 48267 | 約0.518 |
| polyphase 48→44.1 kHz、127 frames/call | 44100 | 44221 | 約0.520 |
| SOS lowpass、256 frames/call（第2chは12 kHz） | 8192 | 8192 | 約0.117 |

polyphaseは各呼出しのceilと端点・phaseの再初期化、SOS前後処理は各区間の端点処理で差が出る。
MIG-006-Dで候補の状態/位相を保持する経路を作る際、一括の保存参照へ照合する。
現行rate≤0は入力objectを返す。新契約の正rate検査は拒否し、この差をmanifestへ別記録する。

検査全体の時間約2.64秒・process peak RSS 106,176,512 bytesは単発の診断値。
並行してPytestを実行したrunであり、性能protocolの新旧比較には使用しない。

## 再検査・明示生成

```bash
./.venv/bin/python scripts/migration_filter_reference.py verify
./.venv/bin/pytest -q tests/logic_verification/test_migration_filter_reference.py
```

通常verifyは入力・期待値を読み、書き換えない。source/runner/契約hash、全導入版、
ケースの集合/順序・metadata・array schema・SHA-256・非有限値を検査する。
portable比較もsource/hash/schema/許容差は緩和しない。

```bash
./.venv/bin/python scripts/migration_filter_reference.py verify --portable
./.venv/bin/python scripts/migration_filter_reference.py generate --output .migration-local/filter-v1-reproduced
./.venv/bin/python scripts/migration_filter_reference.py verify --fixtures .migration-local/filter-v1-reproduced --baseline migration/fixtures/filter-v1/manifest.json
```

generateの出力先は存在しないディレクトリを指定する。別環境での生成を基準更新として自動採用しない。
reportもfixture外の新しいファイルにだけ保存できる。
Pytestは異なる環境でもportable比較を行う。全bytes再生成一致のテストだけは固定環境が異なると明示skipする。
本環境では全133ファイルの再生成一致を確認した。

MIG-003-A/B/Cの参照側は完了。候補coreのAC10/14合格、製品resampler選定、
共有graph、物理I/O、Qt、他OSは後続作業。
