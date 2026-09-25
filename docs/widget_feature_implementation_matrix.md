# ウィジェット共通機能 実装状況マトリクス

更新日: 2026-09-25

`ALL_MODULE_KEYS` と `MODULE_REGISTRY` に登録された 41 モジュールの共通機能を示します。
Welcome と Settings は通常のモジュール用ラッパーを使わないため、表に含めません。

| 記号 | 意味 |
| --- | --- |
| 共✓ | 共通ラッパーで提供 |
| 個✓ | ウィジェットで個別に提供 |
| 外A | 独立した表示部がない |
| 外E | コンパクトモードの対象外 |
| 外F | 2 窓分割の対象外 |
| 外G | 単一の開始／停止主操作の対象外 |

## 全体サマリー

<!-- BEGIN GENERATED: SUMMARY -->

|機能|実装数 / 判断対象|実装率|要判断|対象外|直接テスト済み|提供方法|
|---|---:|---:|---:|---:|---:|---|
|単一ウィンドウ分離（State B）|41 / 41|100.0%|0|0|共通経路を確認|共通ラッパー|
|スクリーンショット|41 / 41|100.0%|0|0|共通経路を確認|共通ラッパー|
|ログビューア表示|41 / 41|100.0%|0|0|共通経路を確認|共通ラッパー|
|コンソール主操作（開始／停止）|30 / 30|100.0%|0|11|共通経路＋Frequency Counter|共通ラッパー＋個別宣言|
|コンパクトモード|17 / 17|100.0%|0|24|17 / 17|ウィジェット個別|
|表示／操作の 2 窓分割（State C）|11 / 11|100.0%|0|30|11 / 11|ウィジェット個別|

<!-- END GENERATED: SUMMARY -->

## モジュール別マトリクス

<!-- BEGIN GENERATED: MODULES -->

|完了|ウィジェット|単一窓分離|2 窓分割|コンパクト|コンソール主操作|撮影|ログ|備考|
|:---:|---|:---:|:---:|:---:|:---:|:---:|:---:|---|
|✓|Signal Generator|共✓|外A|個✓|共✓|共✓|共✓|独立表示部なし|
|✓|Spectrum Analyzer|共✓|個✓|個✓|共✓|共✓|共✓||
|✓|Sound Level Meter|共✓|個✓|個✓|共✓|共✓|共✓||
|✓|LUFS Meter|共✓|個✓|個✓|共✓|共✓|共✓||
|✓|Loopback Finder|共✓|外F|外E|外G|共✓|共✓|コンパクトは未実装、2 窓分割は未実装、単一の開始／停止主操作なし|
|✓|Distortion Analyzer|共✓|外F|外E|共✓|共✓|共✓|コンパクトは未実装、2 窓分割は未実装|
|✓|Advanced Distortion Meter|共✓|外F|外E|共✓|共✓|共✓|コンパクトは未実装、2 窓分割は未実装|
|✓|Network Analyzer|共✓|外F|外E|共✓|共✓|共✓|コンパクトは未実装、2 窓分割は未実装|
|✓|Oscilloscope|共✓|個✓|個✓|共✓|共✓|共✓||
|✓|Raw Time Series|共✓|個✓|個✓|共✓|共✓|共✓||
|✓|Event Detector|共✓|個✓|個✓|共✓|共✓|共✓||
|✓|Lock-in Amplifier|共✓|外F|外E|共✓|共✓|共✓|コンパクトは未実装、2 窓分割は未実装|
|✓|Lock-in Harmonic Analyzer|共✓|外F|外E|共✓|共✓|共✓|コンパクトは未実装、2 窓分割は未実装|
|✓|Arbitrary Harmonic Generator|共✓|外F|外E|共✓|共✓|共✓|コンパクトは未実装、2 窓分割は未実装|
|✓|Lock-in Spectrum Finder|共✓|個✓|個✓|共✓|共✓|共✓||
|✓|Frequency Counter|共✓|外F|個✓|共✓|共✓|共✓|2 窓分割は未実装|
|✓|Lock-in Frequency Counter|共✓|外F|外E|共✓|共✓|共✓|コンパクトは未実装、2 窓分割は未実装|
|✓|Spectrogram|共✓|個✓|個✓|共✓|共✓|共✓||
|✓|Boxcar Averager|共✓|外F|外E|共✓|共✓|共✓|コンパクトは未実装、2 窓分割は未実装|
|✓|Goniometer|共✓|個✓|個✓|共✓|共✓|共✓||
|✓|Impedance Analyzer|共✓|外F|外E|共✓|共✓|共✓|コンパクトは未実装、2 窓分割は未実装|
|✓|Noise Profiler|共✓|個✓|個✓|共✓|共✓|共✓||
|✓|Recorder / Player|共✓|外A|個✓|外G|共✓|共✓|独立表示部なし、単一の開始／停止主操作なし|
|✓|Waveform Loop Player|共✓|外F|外E|外G|共✓|共✓|コンパクトは未実装、2 窓分割は未実装、単一の開始／停止主操作なし|
|✓|Transient Analyzer|共✓|外F|外E|共✓|共✓|共✓|コンパクトは未実装、2 窓分割は未実装|
|✓|Sound Quality Analyzer|共✓|外F|外E|外G|共✓|共✓|コンパクトは未実装、2 窓分割は未実装、単一の開始／停止主操作なし|
|✓|Timecode Monitor & Generator|共✓|外F|個✓|共✓|共✓|共✓|2 窓分割は未実装|
|✓|BNIM Meter|共✓|個✓|個✓|共✓|共✓|共✓||
|✓|HRTF Player|共✓|外F|外E|外G|共✓|共✓|コンパクトは未実装、2 窓分割は未実装、単一の開始／停止主操作なし|
|✓|Ultrasound AM Modulator|共✓|外A|外A|共✓|共✓|共✓|独立表示部なし|
|✓|Linearity Analyzer|共✓|外F|外E|共✓|共✓|共✓|コンパクトは未実装、2 窓分割は未実装|
|✓|1PPS Monitor|共✓|外F|外E|共✓|共✓|共✓|コンパクトは未実装、2 窓分割は未実装|
|✓|Stereo Alignment Monitor|共✓|外F|個✓|共✓|共✓|共✓|2 窓分割は未実装|
|✓|Spatial Binaural Mixer|共✓|外A|外A|外G|共✓|共✓|独立表示部なし、単一の開始／停止主操作なし|
|✓|Processor Benchmark|共✓|外F|外E|外G|共✓|共✓|コンパクトは未実装、2 窓分割は未実装、単一の開始／停止主操作なし|
|✓|Transmission Analyzer|共✓|外F|個✓|共✓|共✓|共✓|2 窓分割は未実装|
|✓|Nonlinear Analyzer|共✓|外F|外E|外G|共✓|共✓|コンパクトは未実装、2 窓分割は未実装、単一の開始／停止主操作なし|
|✓|Lock-in Modeler|共✓|外F|外E|共✓|共✓|共✓|コンパクトは未実装、2 窓分割は未実装|
|✓|Response Viewer|共✓|外F|外E|外G|共✓|共✓|コンパクトは未実装、2 窓分割は未実装、単一の開始／停止主操作なし|
|✓|Feedforward Compensator|共✓|外F|外E|外G|共✓|共✓|コンパクトは未実装、2 窓分割は未実装、単一の開始／停止主操作なし|
|✓|Nonlinear Response Analyzer|共✓|外F|外E|外G|共✓|共✓|コンパクトは未実装、2 窓分割は未実装、単一の開始／停止主操作なし|

<!-- END GENERATED: MODULES -->

## 根拠と更新方法

* モジュール名: `src/core/module_constants.py`
* 登録と能力宣言: `src/gui/module_registry.py`
* 共通ラッパー: `src/gui/widgets/detachable_wrapper.py`
* コンソール: `src/gui/measurement_console.py`
* 全モジュールの能力検証: `tests/logic_verification/gui/test_widget_capabilities.py`

表は `./.venv/bin/python scripts/generate_widget_feature_matrix.py` で更新し、
`--check` でコードとのずれを確認できます。
