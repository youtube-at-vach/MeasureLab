# Rust core段階導入の評価計画

更新: 2026-10-04。[MIG-008の判断](../migration/decisions/0037-mig008-integrated-evaluation.md)により、
Rust/QMLの一括展開を見送り、現行Python/PyQt GUIへのRust core段階導入を評価する。
MIG-008の統合・短い比較・四案の判断は完了。製品への組込み・切替は未実施。
現在地と保存済みの記録は[進捗](../migration/status.md)、buildは[native手順](../native/README.md)。

## 次の対象と完了条件

対象は現行Spectrum Analyzer一つへのRust FFT／共有resultの接続評価。
現行の音声I/Oとrendererを使い、同じ入力・窓・精度・区間・更新条件で利益を判断する。
Python bindingはまだ実装していない。今回の境界調査・整理では新しいbindingや製品機能を追加しない。

| 確認すること | 完了条件 |
| --- | --- |
| 数値と来歴 | FFT・peak/RMS/PSD、ChannelId、区間、Timebase、世代、校正revision、validityが境界を通って一致する。f32/f64を暗黙に変換しない |
| 所有権と停止 | 配列のcopy・寿命・結果の不変性、停止・再開・終了、失敗時の回収を確認する |
| 校正付き保存 | 元値・精度・単位・校正・区間を保存し、再読込で一致する |
| 実測の利益 | 同じ現行rendererでCPU/RSS、更新・応答、copy費用を短く比較し、導入するか現行Pythonを継続するか判断する |

利益を示せなければ現行Pythonを継続し、共有解析・履歴・不変snapshotの設計改善だけを取り込む。
数値・時刻・保存の誤りを性能改善で相殺しない。
[コア契約](../migration/contracts/core.md)と[数値基準](../migration/contracts/numerics.md)は意味・許容差の参照とし、
そこに記載された全機能・全構成の実装を、この評価の必須条件にしない。

## 実装境界の調査結果

2026-10-04、HEAD `b8c94da2`の製品とnative libraryを調査した。
最初の境界は **Spectrum Analyzerの取得済み区間 → ワーカー内の一括解析 → 不変result** とする。
窓処理・複数ch FFT・線形のpeak/RMS/PSD正規化を一度の呼出しにまとめる。
実装量、共有resultへの接続、現在の表示との互換性からの判断であり、製品での性能利益は未実証。

| 境界候補 | 評価 |
| --- | --- |
| `FFTManager.rfft`を全体置換 | ch別FFI・copy、窓・正規化の重複が残る。同一区間resultを共有できず、多数の既存モジュールとinverse/wisdomへ影響する |
| Spectrumの標準解析をワーカーで一括実行 | 採用候補。取得・PyQt/pyqtgraphを保ち、線形解析と来歴を一つのresultへまとめられる。変更を一モジュールに限定できる |
| AudioEngine callbackからRust取得queueへ直接接続 | callback、論理ch/loopback、dtype、stream再起動まで変更が広がる。最初の解析比較に必須ではない |
| QML/renderer/backendも同時置換 | MIG-008で見送り済み。今回の実装境界へ含めない |

### コードの接続点と所有権

| 層 | 既存の入口と最初の変更 |
| --- | --- |
| 取得 | [Spectrum Analyzer](../src/gui/widgets/spectrum_analyzer.py)の`start_analysis`と[RingBuffer](../src/core/ring_buffer.py)を使う。callbackには新しいFFI・FFT・JSON化を入れない |
| 区間の受渡し | `process_queue`の`read_with_metadata`が返すstart/end/dropを保持し、連続したN framesを渡す。現在の`get_latest_data`だけでは区間の来歴を復元できない |
| Python境界 | 薄いPyO3/NumPy binding候補。frame-major `(N, ch)`、dtype、ChannelId順、Source/Timebase/世代/区間/validity、窓条件を検査する。配列のlist/JSON/CLI受渡しは使わない |
| Rust解析 | [Graph](../native/graph-core/src/lib.rs)の`SignalBlock`→`schedule`→`Job`→`FftResult`を内部利用する。公開Python APIにはgraph全体の操作を要求しない。ワーカーがplan/scratchを所有する |
| 表示 | `compute_spectrum`の線形解析をadapterへ分離し、`update_plot`は最新の完成resultを読む。重み付け、指数平均、peak hold、octave/RTA、marker、描画はPython側に残す |
| 保存 | 選択resultの取得条件・校正revisionを固定して[MeasurementResult](../native/graph-core/src/result.rs)へ渡し、[保存worker](../native/graph-core/src/export.rs)と[product codec](../native/graph-core/src/product.rs)で再読込を確認する。現在設定から来歴を後付けしない |

最初は入力をRustの`Vec`へ一度copyし、その後にGILを解放して計算する。
出力はhandleが`Arc<FftResult>`を保持し、GUIへ必要な列だけcopyして渡す。
Python配列の変更がRustの保存resultを変えないことを保証する。
zero-copyを導入条件にせず、scratchへのview公開やcallback配列の借用を避ける。
入力pendingと表示latestは容量を制限し、解析/保存の保持resultを上書きしない。
停止/再開・設定変更で世代を切り替え、古い完了結果を現在の表示へ渡さない。
graphの停止待ちや保存workerのjoinをGUI/GIL保持中に行わない。

PyO3の[parallelism手順](https://pyo3.rs/main/parallelism.html)はRust処理中の`Python::detach`を説明する。
rust-numpyの[readonly borrow](https://docs.rs/numpy/latest/numpy/borrow/struct.PyReadonlyArray.html)は
Rust側の借用管理であり、NumPyメモリを非同期ワーカーの所有物にする機能ではない。
[ToPyArray](https://docs.rs/numpy/latest/numpy/convert/trait.ToPyArray.html)はcopy、
[IntoPyArray](https://docs.rs/numpy/latest/numpy/convert/trait.IntoPyArray.html)は所有権移動を伴う。
共有`Arc`内の配列をそのまま移動できると仮定しない。依存版と配布方式は導入時に固定する。

### 接続前に解消する差

- 製品Spectrumは現在`input_data`/transferをf64で保持する。backendがf32でも現行比較の基準はf64解析。
  初回は2ch/f64、boxcar/symmetric Hann、通常rollingの標準Spectrum/PSD、dBFS/dBVへ絞る。
  f32解析は別の明示した条件とし、f32入力/FFTとf64の正規化・reductionを区別する。
- 現在のrolling入力は起動時のゼロを含み、drop後も旧窓と結合できる。
  nativeへは完全な連続区間だけ渡し、欠損・未充足を正常なゼロとして扱わない。
  Python比較側も同じ有効区間・更新条件に合わせる。
- AudioEngineはLeft/Right/monoを論理入力へ写像し、loopbackも扱う。
  ChannelIdは論理列と明示したrouteに対応させ、物理portと同一と仮定しない。
  sample indexはRingBuffer resetに対する相対位置。stream再開・rate/route変更を世代で区別し、
  未確認のclock対応は`origin_seconds=None`などunknownのまま保持する。
  現行callbackには取得世代・format revisionが渡らないため、stream設定を不変metadataとして
  blockへ付ける最小の変更が必要。GUI設定の事後読取だけで取得時のrate/routeを決めない。
- 製品はDC/偶数Nyquistにも係数2を使うが、Rust契約のendpoint係数は1。
  [固定FFT参照の既知差](../migration/fixtures/README.md)を表示adapterで明示して比較し、
  正本resultと保存には契約値を保持する。数値修正と性能比較を混ぜない。
- SpectrumのAverageは振幅平均、PSDのAverageはpower平均。現在の指数平均を
  graphの`CumulativePsd`へ置換しない。unit、校正、平均状態とraw resultを区別する。
- 現行`CalibrationManager`のglobal V/FSとprofile名だけではRustのch別revision/適用区間を表せない。
  実際の取得routeと校正snapshotをIDに対応させ、校正変更時にrevisionを固定する。
  未校正をV/FS=1の校正済みprofileにせず、二重校正もしない。
  `MeasurementResult`の絶対SPLは未対応（列はunknown、数値の再読込は拒否）。
  dB SPL、その他の窓・multitaper・Cross Spectrum・大容量snapshotは既存Python経路を使う。

### 短い計測と実装順

macOS Intel、Python 3.12.14 / NumPy 2.2.6 / pyFFTW 0.15.1、Rust 1.98.1 release。
48 kHz、N=4096、2ch f64、symmetric Hann、1 kHz tone（右ch振幅0.5）、
PythonはDual/Spectrum、Z重み、平均係数0、peak holdなし。
各経路20回warmup後500回×3組を順番に実行し、組ごとの平均時間の中央値を示す。
採用した計測はbuild完了後に実施し、経路間で並行実行していない。

| 呼出し | 中央値、µs/回 | 3組の範囲、µs/回 |
| --- | --- | --- |
| Pythonの所有入力copy、64 KiB | 3.876 | 3.849–3.881 |
| Pythonの2ch `FFTManager.rfft`、既存plan、窓処理を含まない | 42.388 | 42.110–42.640 |
| Pythonの`_compute_standard` | 214.812 | 213.968–215.974 |
| Pythonの`compute_spectrum`、取得済みbufferから | 372.886 | 370.681–378.222 |
| Rustの`Analyzer::new`+`analyze`、毎回plan構築 | 257.932 | 250.866–259.331 |
| Rustの同じ`Analyzer`で`analyze`、plan再利用 | 146.829 | 144.180–153.776 |

Rustの二行は同じ数値・全出力を計算し、plan再利用の有効性を示す。
現行graphの`analyze`は毎回`Analyzer::new`を実行するため、そのままbindingへ接続しない。
node/workerごとに型別Analyzerを保持し、plan/scratchを同時利用しない仕組みを先に整える。
現在のDSPは全列の確保とinverseも毎回実行する。forwardのみの通常表示経路を分ける場合も、
既存`analyze`とinverseの固定fixture検証は保持し、必要な出力だけを生成・公開する。

PythonとRustは計算・平均・出力列が異なるので、この表を言語間の速度比には使わない。
binding、queue、graphの入力補正copy、GUI描画、校正付き保存、CPU/RSSは含まない。
所有copyの例は小さく、初手でunsafeなzero-copyを選ぶ根拠にはならない。
一時的な計測source/buildはリポジトリ外で作成し、計測後に削除する。常設runnerは追加しない。

実装順は次のとおり。今回行ったのは境界調査と下記の不要source整理まで。

1. Rustのplan/scratch再利用と通常解析の出力範囲を整理し、変更した数値・所有権を対象テストで確認する。
2. 薄いbindingとSpectrum専用workerを追加し、同一区間の値・endpoint adapter・世代・停止/失敗回収を検証する。
3. 同じresultから校正付き保存/再読込を確認し、現在のpyqtgraphで同条件の短いCPU/RSS・応答・copy比較を行う。
4. 利益が確認できた範囲だけ採用する。FFTW/Python fallbackを残し、他モジュールへの展開は別の判断にする。

### この調査で除去したsource

`product/import.rs`と専用テストを削除した。残っていたpublic import APIの呼出しは専用テストだけで、
Git履歴`75581059`では削除済み`result-candidate`評価CLIが利用していた。
旧traceを`ImportedProduct`へ包む処理、外部CSV descriptor指定、merged grid読込は今回の解析境界に不要。
同adapterだけが使った`product.rs`のmerged分岐も除去した。

snapshotのJSON/独立CSV+hash付きsidecarのcodecと入力検査、非同期保存workerは保持する。
共用JSON parserの整数丸め防止テストは`product/tests.rs`へ移して残した。
DSP/graph、filter/derived、queue、履歴/Trigger、Timebase、校正はcore内の参照と回帰検証があり、削除しない。
製品の`FFTManager`、取得、CSV/JSON exportとPython fallbackも利用中のため保持する。

## 残すもの

RustのDSP／共有graphと、そこから使う容量制限付きqueue、履歴、Timebase、Trigger、校正、保存codecを残す。
coreの回帰テストと[固定FFT fixture](../migration/fixtures/README.md)18条件を維持する。
元の入力・期待値・係数・許容差を変更せず、直接libraryを検証する。
MIG-008の判断と圧縮reportを保持し、終了したQt/QML・renderer・backend試作、評価CLI／runner、
台帳検査、重複計画・手順・中間生成物を除去する。過去のコードと詳細記録はGit履歴から復元できる。

## 現在の対象に含めないもの

- QML画面の全面展開、renderer追加比較、41機能の移行計画。
- CPAL／PortAudioの製品backend化、全MonitorTap、動的route、永続profile、VST／ネットワーク音声の先行試作。
- Windows・ARM、clean環境の配布、全機器・全rate・全校正構成の網羅検証。
- 長時間連続運転・耐久試験、10分×3回、全backend×全Qt×全言語×全chの反復。

これらは未確認のまま保持し、必要になった時点で目的と順序を決める。

## 検証と記録

変更した挙動の対象テストを実行する。通った検証は関連変更・新たな失敗がなければ繰り返さない。
MIG-008の完了済み2ch統合や全fixture再監査を、再開時の必須手順に戻さない。
固定fixtureのhash検査とcodecの入力検査は維持する。
Rust coreのCIは明示した手動実行だけとし、Python CIは通常どおり実行する。
Ruff lint/formatと、Markdown変更時のlintは[共通手順](../.agents/workflows/tool_usage.md)に従う。
UIサイズ検証はレイアウト・翻訳の変更時、またはCI相当の最終確認を依頼された場合に行う。

工程は本書、現在地は進捗、MIG-008の測定条件・四案の理由は判断0037に集約する。
小変更ごとの新規手順書・決定記録、source/binaryの複製、全artifactの再hash監査は追加しない。
