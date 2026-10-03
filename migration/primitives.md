# プリミティブ台帳（MIG-002）

2026-10-04: この台帳は将来の対象範囲の参照。MIG-008の工程は[現在の計画](../guide/RUST_QML_MIGRATION_PLAN.md)を優先し、全項目の実装を先行条件にしない。

基準コミット・更新日は[機能台帳](inventory.md)と同じ。数値だけでなく取得、同期、手順、結果受渡しも含める。
以下は言語非依存の分解先であり、クレート名や採用ライブラリを決めない。利用機能IDは機能台帳への逆引き。

全20項目の検証段階は **契約作成: P0範囲を記録／単体比較: 未着手／グラフ統合: 未着手／利用機能での検証: 未着手**。
高度演算・規格固有の完全な仕様は個別着手時に作る。記載した参照テストは現行資産への入口であり、移行合格ではない。
共通の精度・許容差・共有key・validityは[コア](contracts/core.md)・[数値](contracts/numerics.md)に従う。
実行予算は[比較条件](benchmarks/protocol.md)。新しい常時監視を追加する根拠にはしない。

## P01

生成・変調・noise

利用機能: M01, M05, M06, M07, M08, M12, M14, M15, M19, M21, M27, M28, M30, M31, M36, M37, M38, M41

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | 条件/seed/phase → FS波形（frames×channels） |
| Timebase・状態・初期化 | Stream世代内の絶対位置。phase/filter/fadeをブロック間で継続、再開は明示reset |
| validity・精度・共有条件 | f64参照、f32 I/O別比較。seed・phase・条件・経路・位置が一致する場合のみ共有。乱数生成法も固定 |
| 現行の入口 | [source](../src/core/generators.py) |
| 参照検証 | [test](../tests/logic_verification/generators/test_signal_generator_logic.py) |

## P02

取得・Routing・MonitorTap

利用機能: M01, M03, M04, M05, M11, M14, M20, M23, M24, M29, M30, M34, C01, C02, C03

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | 端点/対応表/gain → FS SignalBlock、I/O状態 |
| Timebase・状態・初期化 | N-in/M-out、route世代と適用sample。mute/quantize前後を分離 |
| validity・精度・共有条件 | チャンネル不一致は拒否。XRUN/欠落は区間付き。f32/f64形式を保持。同一tap/route/stream世代のみ共有 |
| 現行の入口 | [source](../src/core/audio_engine.py) |
| 参照検証 | [test](../tests/logic_verification/core/test_audio_engine.py) |
| 候補検証 | 005の[queue→履歴→共有FFTの実装](../native/graph-core/src/acquisition.rs)と[動的出力route](../native/dynamic-route.md)。f32 callback/BlackHoleまで。全tap/製品共通adapterは後続 |

## P03

履歴・Trigger・区間取得

利用機能: M02, M09, M10, M11, M12, M13, M15, M16, M17, M18, M19, M20, M21, M22, M25, M27, M31, M32, M36, C01

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | SignalBlock/event → sample区間と所有snapshot |
| Timebase・状態・初期化 | 購読者別cursor、半開区間、保持容量。再開/時間基準変更で旧世代を閉じる |
| validity・精度・共有条件 | 上書き・未取得区間を欠落として返す。位置は整数、subsampleは有理数。同一eventでも読取りは非消費 |
| 現行の入口 | [source](../src/core/ring_buffer.py) |
| 参照検証 | [test](../tests/logic_verification/core/test_ring_buffer.py) |
| 候補検証 | 006-Cの[履歴/Timebaseの実装](../native/graph-core/src/history.rs)、[Rust試験](../native/graph-core/src/history/tests.rs)、[保存比較](../scripts/migration_history_candidate.py)。input.rawは005の[取得workerの実装](../native/graph-core/src/acquisition.rs)、過去窓の不変resultは007-Aの[Trigger captureの実装](../native/graph-core/src/acquisition/trigger.rs)へ接続。[Qt要求配送の実装](../native/display-core/src/trigger.rs)で共有hold/retry/releaseを検査。検出器・外部triggerは後続 |

## P04

窓・FFT・cross/PSD

利用機能: M02, M06, M07, M08, M18, M22, M28, M33, M35, M36, M39, M41

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | FS区間/window → complex FS、FS peak、FS²/Hz、Hz軸 |
| Timebase・状態・初期化 | N/hop/window/fftbins/前処理/精度と区間を固定。FFTはstateless、平均は別状態 |
| validity・精度・共有条件 | f64を基本。DC/Nyquistと窓補正は数値契約。欠落窓は無効。同じkeyに限り一回計算 |
| 現行の入口 | [source](../src/core/fft_manager.py) |
| 参照検証 | [test](../tests/logic_verification/analysis/test_spectrum_rms_accuracy.py) |

## P05

積分・RMS・重み付け・loudness

利用機能: M02, M03, M04, M19, M22, M26, M33

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | FS²と時間窓 → FS RMS、dB/SPL/LUFS等 |
| Timebase・状態・初期化 | time/frequency weighting、gate、積算時間、warmup/resetを条件化 |
| validity・精度・共有条件 | f64積算。欠落をゼロや無音に置換しない。重み/gate/履歴開始が異なる状態を共有しない |
| 現行の入口 | [source](../src/core/sound_level.py) |
| 参照検証 | [test](../tests/logic_verification/analysis/test_lufs_meter_logic.py) |

## P06

フィルタ・rate変換・true peak

利用機能: M01, M03, M04, M12, M17, M21, M23, M24, M26, M29, M30, M34, M37, M40, C01

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | FS系列/係数/入出力rate → FS系列と位置変換 |
| Timebase・状態・初期化 | SOS/zi、FIR tail、polyphase位相を維持。因果/非因果・端点・遅延を保存 |
| validity・精度・共有条件 | f64参照。欠落の影響をsupportへ拡張。係数・状態・開始位置の一致が必要。TruePeak oversamplingは別条件 |
| 現行の入口 | [source](../src/core/analysis.py) |
| 参照検証 | [test](../tests/logic_verification/analysis/test_resample.py) |
| 候補検証 | [006-Dの実装](../native/graph-core/src/filter.rs)。f64保存21ケースとpure graphのstate/phase/validity。実取得/Qt・f32・IIR gap回復は後続 |

## P07

位相・Lock-in・周波数推定

利用機能: M05, M06, M09, M12, M13, M15, M16, M17, M21, M31

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | 波形/参照 → complex振幅、Hz、rad/deg |
| Timebase・状態・初期化 | 参照位相原点、harmonic比、積分窓、LPF/追跡state |
| validity・精度・共有条件 | f64。低振幅時の位相/Hzを有効値にしない。参照とtimebase、stateが一致する部分のみ共有 |
| 現行の入口 | [source](../src/core/frequency_analysis.py) |
| 参照検証 | [test](../tests/logic_verification/analysis/test_lockin_comprehensive.py) |

## P08

手順測定・相関・遅延推定

利用機能: M05, M06, M08, M21, M28, M31, M36, M37, M38, M41

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | stimulus/record → IR、complex応答、sample遅延 |
| Timebase・状態・初期化 | play/record同期、settling、取得区間、cancel/失敗、推定遅延と補償を分離 |
| validity・精度・共有条件 | f64。未同期/不足区間は無効。固定入力の相関は共有可、進行中sweep sessionは独立 |
| 現行の入口 | [source](../src/core/transmission_logic.py) |
| 参照検証 | [test](../tests/logic_verification/gui/test_play_rec_session_cleanup.py) |

## P09

高調波・歪み・noise分離

利用機能: M06, M07, M08, M13, M14, M22, M36

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | FFT/波形/基本波 → THD/IMD/TDN等の比・dB |
| Timebase・状態・初期化 | 帯域、窓、harmonic数、noise床、平均法/reset |
| validity・精度・共有条件 | f64。基本波ゼロ/帯域外を無効として区別。定義と参照区間が一致した演算のみ共有 |
| 現行の入口 | [source](../src/core/analysis.py) |
| 参照検証 | [test](../tests/logic_verification/analysis/test_distortion.py) |

## P10

event・統計・stereo指標

利用機能: M02, M03, M04, M09, M11, M16, M17, M20, M22, M25, M28, M32, M33, M36

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | event/series → count、率、分布、相関、Allan等 |
| Timebase・状態・初期化 | event境界・histogram bin・gate・保持期間。restartで統計世代を更新 |
| validity・精度・共有条件 | 整数count/f64統計。欠落区間を率の分母に混ぜない。平均/分散/相関の零除算と有効数を保持 |
| 現行の入口 | [source](../src/core/event_statistics.py) |
| 参照検証 | [test](../tests/logic_verification/core/test_event_statistics.py) |

## P11

畳込み・空間音響

利用機能: M29, M34, M37, M38, M39, M40

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | source/HRIR/kernel → FS波形、IR/応答 |
| Timebase・状態・初期化 | overlap/tail・位置/HRIR切替・rate・kernel世代 |
| validity・精度・共有条件 | f64参照。欠落をkernel supportへ伝播。SOFA座標/rate/チャンネル対応を条件化。kernelだけの共有とstate共有を分離 |
| 現行の入口 | [source](../src/gui/widgets/hrtf_player.py) |
| 参照検証 | [test](../tests/logic_verification/gui/test_hrtf_player_resample.py) |

## P12

補間・最適化・非線形モデル

利用機能: M21, M29, M31, M36, M37, M38, M39, M40, M41, C04

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | 複素応答/行列/観測 → 係数、補間値、model |
| Timebase・状態・初期化 | 端点clamp、位相unwrap、regularization、rank、iteration/収束条件 |
| validity・精度・共有条件 | f64/complex128。rank不足/非収束/外挿を記録。入力hash・solver条件の一致でのみ共有。高度契約は個別タスク |
| 現行の入口 | [source](../src/core/nonlinear_response_analyzer_core.py) |
| 参照検証 | [test](../tests/logic_verification/core/test_nonlinear_response_analyzer.py) |

## P13

校正・単位変換

利用機能: M01, M02, M03, M06, M07, M08, M09, M10, M11, M12, M13, M14, M16, M17, M21, M22, M27, M30, M31, M32, C01, C03, C04, C05

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | FS/Hz/phaseとprofile → V、SPL、補正Hz/phase |
| Timebase・状態・初期化 | ChannelId・device対応・profile revision・適用位置をsnapshot化 |
| validity・精度・共有条件 | f64。未校正でもFSは保持、絶対単位は無効。profileや補正位置が変われば結果を分岐。過去結果を書換えない |
| 現行の入口 | [source](../src/core/calibration.py) |
| 参照検証 | [test](../tests/logic_verification/core/test_calibration_alignment.py) |
| 候補検証 | 006-Eの[ID校正/resultの実装](../native/graph-core/src/result.rs)。007-Aの[取得/両Qt接続の実装](../native/display-core/src/calibration.rs)でsession binding/実区間/絶対値/保持不変性を検査。[Qt編集・適用](../native/calibration-edit.md)で原子的置換/旧result不変性/共有rawを検査。SPL/mapは後続 |

## P14

file・保存・来歴

利用機能: M11, M15, M19, M21, M23, M24, M26, M29, M34, M38, M39, M40, C03, C04, C05, C09, C10

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | 元data/結果/軸/校正 → 版付きJSON/CSV/audio/model |
| Timebase・状態・初期化 | 不変snapshotをworkerで保存。atomicな完了/失敗、cancel、旧版の読取り |
| validity・精度・共有条件 | f64値を保持し表示間引きを保存しない。非有限値とvalidityを明示。同じdataでも保存要求の寿命は独立 |
| 現行の入口 | [source](../src/core/export/trace.py) |
| 参照検証 | [test](../tests/core/export/test_json_exporter.py) |
| 候補検証 | 006-Eの[実験用JSON/CSVの実装](../native/graph-core/src/result.rs)。007-Aの[校正済み取得結果の実装](../native/display-core/src/calibration.rs)でも全値/来歴の往復を検査。[非同期workerの実装](../native/graph-core/src/export.rs)でbounded受付/完了/失敗/pending cancel/寿命と全往復を検査。[製品互換adapter評価の実装](../scripts/migration_product_candidate.py)で旧JSON/CSVとunknown、carrier/sidecarの完全往復を検査。[両Qt保存操作](../native/qt-save.md)で表示済み通常/Trigger resultのpin、受付/実完了/失敗、GUI外の終了を検査。[native製品codec/共通保存worker](../native/product-codec.md)で実exporterとの双方向往復と部分pair失敗を検査。[既存の検証結果](status.md#再利用する証拠)を同じ保存workerへ接続。[native製品importの実装](../native/graph-core/src/product/import.rs)で旧トレースのunknownと完全snapshot、明示CSV descriptorを検査。Qt import操作、取得中の保存負荷は後続 |

## P15

測定制御・購読・状態

利用機能: M01, M05, M06, M07, M08, M11, M23, M24, M26, M29, M31, M34, M37, M38, M40, M41, C01, C02, C03, C06, C07, C09, C10

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | start/stop/config要求 → 実状態、確定result |
| Timebase・状態・初期化 | Idle/Preparing/Running/Stopping/Failed、request世代、bounded queue、最後の購読解除 |
| validity・精度・共有条件 | UIからの要求を成功扱いしない。失敗/破棄を一度通知。数値精度は非該当。結果nodeは共有、制御の所有者を明示 |
| 現行の入口 | [source](../src/gui/main_window.py) |
| 参照検証 | [test](../tests/logic_verification/gui/test_main_window_activity.py) |
| 候補検証 | 005の[単一取得workerの実装](../native/graph-core/src/acquisition.rs)。poll上限/世代fence/保存token/Failed/冪等stop。Qtと製品backend状態機械は後続 |

## P16

LTC・1PPS・clock推定

利用機能: M27, M32

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | edge/audio/LTC → frame時刻、sample間隔、clock係数 |
| Timebase・状態・初期化 | fps/drop frame/timezoneとsample timeを分離。jam・offset・校正の世代 |
| validity・精度・共有条件 | 整数sample/f64補正。独立clockを同期済みにしない。未知の精度はunknown。解析済みeventは共有可 |
| 現行の入口 | [source](../src/core/ltc.py) |
| 参照検証 | [test](../tests/logic_verification/core/test_timecode_calibration.py) |

## P17

wavelet・過渡解析

利用機能: M25

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | trigger波形 → CWT係数、scale/Hz、ringing/decay |
| Timebase・状態・初期化 | wavelet/scale/周波数対応、端点support、取得位置 |
| validity・精度・共有条件 | f64/complex128参照。端点/gapの影響範囲を保持。同じ波形hash/scaleのCWTは共有可。PyWavelets代替は未選定 |
| 現行の入口 | [source](../src/gui/widgets/transient_analyzer.py) |
| 参照検証 | [test](../tests/logic_verification/gui/test_transient_ringing_analysis.py) |

## P18

心理音響

利用機能: M26

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | file/time series → loudness、sharpness、roughness等 |
| Timebase・状態・初期化 | resample/filter、band、時間窓、左右/平均の定義を個別保持 |
| validity・精度・共有条件 | f64参照。現行近似式との一致と規格適合を混同しない。各指標の定義/閾値/単位は個別fixtureで追加 |
| 現行の入口 | [source](../src/gui/widgets/sound_quality_analyzer.py) |
| 参照検証 | [test](../tests/logic_verification/gui/test_sound_quality_analyzer.py) |

## P19

表示用snapshot・間引き・plot

利用機能: M02, M04, M09, M10, M15, M18, M20, M25, M26, M28, M33, M35, M39, C05, C06, C07, C08, C09

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | 結果/区間 → line、heatmap、軸、cursor値 |
| Timebase・状態・初期化 | 取得のsample時間とGUI更新時刻を分離。履歴・表示rate/zoomだけが表示state |
| validity・精度・共有条件 | 描画f32可、元値/cursor/exportは解析精度。描画省略をdata gapにしない。複数viewは同じresult IDを参照 |
| 現行の入口 | [source](../src/gui/widgets/instrument_plot.py) |
| 参照検証 | [test](../tests/logic_verification/gui/widgets/test_instrument_plot.py) |
| 候補検証 | 007-Aの[共有result表示の実装](../native/display-core/src/lib.rs)。保存replayと[BlackHole実入力](../native/live-display.md)/両Qt。[分離表示と9言語の実装](../native/qml/Display.qml)、[Trigger要求配送の実装](../native/display-core/src/trigger.rs)、[校正結果表示の実装](../native/display-core/src/calibration.rs)と[取得中のQt校正編集](../native/calibration-edit.md)を検査。実window manager/他OS・性能は後続 |

## P20

性能・反復速度の測定

利用機能: M35, C10

| 項目 | 契約・根拠 |
| --- | --- |
| 入出力・単位 | 同条件のworkload → wall time、CPU、RSS、遅延 |
| Timebase・状態・初期化 | warmup・cache・debug/release・thread数・開始/終了境界を記録 |
| validity・精度・共有条件 | 単調clock。失敗runを消さず測定精度/回数を保存。環境差のある結果は集計しない。製品機能の専用試験は未確認 |
| 現行の入口 | [source](../src/gui/widgets/processor_benchmark.py) |
| 参照検証 | [test](../tests/benchmarks/algorithms/benchmark_event_detector.py) |
