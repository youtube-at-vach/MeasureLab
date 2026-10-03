# Pure FFT candidate comparison

MIG-006-A、2026-09-30。[数値契約v0.1](../migration/contracts/numerics.md)と
[参照fixture](../migration/fixtures/README.md)の同じ入力bytesをRustへ通す。
Rust/QMLの採用、製品API、FFTライブラリの最終選定ではない。

## 実装と境界

`dsp-core`はQt、音声backend、Python FFIに依存しない純粋演算クレート。
[RealFFT 3.5.0の公式仕様](https://docs.rs/realfft/3.5.0/realfft/)を確認し、
RealFFT 3.5.0 / RustFFT 6.4.1をCargo.lockへ固定した。
forwardの符号は負、無正規化。比較出力は`X/N`、inverseは`1/N`正規化。
偶数NのDC/Nyquistは係数1、その他と奇数Nの最終binは係数2。

`Analyzer<f32>`/`Analyzer<f64>`がplanと専用scratchを所有する。窓はf64で作り、
f32経路では窓をf32へ変換してからf32で乗算・FFT・inverseする。
単位変換、正規化、時間RMS/PSDの有限和はf64で計算する。f32入出力だけの全f32演算ではない。
frame-majorのN-channel入力をchannel別に計算し、bin-majorで元の論理ID順へ戻す。
同じplanの再利用は結果共有ではない。各結果は独立した配列を所有する。

boxcar/symmetric Hann、Hz、FS peak、coherent bin RMS、無窓時間RMS、
PSD（FS²/Hz）、ASD（FS/√Hz）、積分power、inverseを返す。
bin RMSはcoherent tone用であり、漏れのある任意信号の総RMSではない。
非有限入力/結果、非正rate、N<3、重複/空ID、次元不一致を拒否する。
allocationと同期処理を含む解析worker用で、音声callbackへ入れない。

## ファイル比較

[runner](../scripts/migration_fft_candidate.py)はlocked/offline/debugで`dsp-core`だけをbuildする。
[CLI](dsp-core/src/main.rs)へrequest JSON、**元の`input.bin`**、新規出力ディレクトリを渡す。
入力を書き換えないことを呼出し前後のhashでも確認する。
CLIの評価上限はN=4194304、32ch。これは物理I/Oや製品の能力宣言ではない。

保存済みmanifestのsource/generator、契約、許容差、metadata、入力/期待値hashを確認し、
出力のschema/ID/順序/shape/dtype/単位/有限性を検査する。
理論値と現行FFT値の両方へ比較し、phaseは周期差、dBは定義した閾値以上で判定する。
ASD²とPSD、coherent bin RMSとendpoint規則も検査する。
期待値の再生成、許容差変更、現行Spectrumのendpoint表示の修正は行わない。

## 再実行

このworktreeではRust依存を取得済み。別環境で初回の取得だけ、
[native環境手順](README.md#このworktreeで使う)を設定して`cargo fetch --locked --manifest-path native/Cargo.toml`を実行する。
Qt SDKを用意する必要はない。

```bash
./.venv/bin/python scripts/migration_fft_candidate.py --report .migration-local/fft-candidate.json
./.venv/bin/python scripts/migration_fft_candidate.py --extended .migration-local/fft-extended-v1 --report .migration-local/fft-candidate-all.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_fft_candidate.py
```

小規模14件と4/8chの4件はGit管理下。拡張6件の配列はこのworktreeのローカル保存を使い、
[拡張baseline](../migration/fixtures/fft-extended-v1.manifest.json)との厳密一致も要求する。
別OS/依存環境は`--portable`を明示する。source/hash/shape/数値条件は緩めない。
reportは新規ファイルかつfixture外に限る。コマンドlog/gzip/hash、lock/source/実行物hash、
環境、各誤差、旧表示の既知差を保存する。
詳細reportはローカル生成物としてGit管理外に置き、Gitには
[決定0007](../migration/decisions/0007-pure-fft-candidate.md)へ条件・誤差・判定・限界を要約する。
時間/RSSはファイル比較全体の診断値で、FFT throughputやsteady-state性能ではない。
RSSはPython親processのみで、Rust子processのpeak RSSは未計測。

## コア編集の反復

[反復runner](../scripts/migration_fft_iteration.py)が専用sourceコピー/targetで、
one-sided係数の同値な分岐変更を5回適用する。
各回はpatch適用後からRust対象テストと24ケース比較完了までを測り、
baseへの復帰・再buildは区間外。依存取得は無効、build並列数4、FFTは1 thread。
元のcheckout、元のtarget、fixtureを編集しない。
測定中は他のbuild/testを実行しない。

```bash
./.venv/bin/python scripts/migration_fft_iteration.py --extended .migration-local/fft-extended-v1 --report .migration-local/fft-core-edit.json
```

初回setup/warmupと全5値、中央値/min/max/標準偏差、patch/hash、全logを保存する。
絶対30秒の目安と、現行Pythonの同等修正との比率を分ける。
Pythonの同等編集は未測定。Qt adapterはまだDSPクレートを参照せず、GUI波及は未検証。
結果と制限は[決定0007](../migration/decisions/0007-pure-fft-candidate.md)を参照。
