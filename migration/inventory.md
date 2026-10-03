# 機能・互換性台帳（MIG-002）

2026-10-04: この台帳は将来の対象範囲の参照。MIG-008の工程は[現在の計画](../guide/RUST_QML_MIGRATION_PLAN.md)を優先し、全項目の実装を先行条件にしない。

基準: `9fd79958f6a8bbae6808813d3704617612e6d26c`（0.9.0）。2026-09-29に現行コードと既存テストを棚卸し。
IDは表示順で初回採番し、今後の並替えでも変えない。[進捗](status.md)・[プリミティブ](primitives.md)・[検証条件](contracts/acceptance.md)を参照。

ここでの状態は次期実装の到達度であり、現行版の品質や実装有無ではない。全行を「未着手」で登録する。
状態遷移は未着手 → 契約作成済み → 実装中 → 比較合格 → 実機・UI待ち → 移行完了。P0共通契約の作成だけで各機能を進めない。
プリミティブ対応は分解先の候補を含む。現行コードがすでに共通ノードを使うという意味ではない。
テスト列は入口となる代表例で、網羅性・今回の実行・新版との一致は保証しない。個別着手時に全サブ機能と停止/失敗/保存を追加する。

## 41モジュール

群は評価計画の順序（A: 基本、B: 監視、C: 同期、D: 手順、E: 高度）。すべての行で
[能力宣言](../src/gui/module_registry.py)のsplit/compact/console actionと、[設計境界](../guide/MEASUREMENT_INSTRUMENT_DESIGN_GUIDELINES.md#15-理想的な測定器と実装要件の境界)を引き継ぐ。

| ID | module key / source | 群 | 棚卸ししたサブ機能 | プリミティブ | 参照テスト・不足 | 状態 |
| --- | --- | --- | --- | --- | --- | --- |
| M01 | `Signal Generator` / [source](../src/gui/widgets/signal_generator.py) | A | 周期波・noise・multitone・MLS/Golay/PRBS・burst/sweep・AM・filter・左右設定・出力遷移 | [P01](primitives.md#p01), [P02](primitives.md#p02), [P06](primitives.md#p06), [P13](primitives.md#p13), [P15](primitives.md#p15) | [test](../tests/logic_verification/generators/test_signal_generator_logic.py) | 未着手 |
| M02 | `Spectrum Analyzer` / [source](../src/gui/widgets/spectrum_analyzer.py) | A | Spectrum/PSD/cross・窓/DPSS・平均・重み付け・octave平滑化・peak・RMS・単位 | [P03](primitives.md#p03), [P04](primitives.md#p04), [P05](primitives.md#p05), [P10](primitives.md#p10), [P13](primitives.md#p13), [P19](primitives.md#p19) | [test](../tests/logic_verification/instruments/test_spectrum_analyzer.py) | 未着手 |
| M03 | `Sound Level Meter` / [source](../src/gui/widgets/sound_level_meter.py) | B | 周波数/時間重み・積算・目標時間・Ln履歴/ヒストグラム・校正 | [P02](primitives.md#p02), [P05](primitives.md#p05), [P06](primitives.md#p06), [P10](primitives.md#p10), [P13](primitives.md#p13) | [test](../tests/logic_verification/gui/test_sound_level_meter.py) | 未着手 |
| M04 | `LUFS Meter` / [source](../src/gui/widgets/lufs_meter.py) | B | momentary/short/integrated・gate・履歴・true peak・peak profile・reset | [P02](primitives.md#p02), [P05](primitives.md#p05), [P06](primitives.md#p06), [P10](primitives.md#p10), [P19](primitives.md#p19) | [test](../tests/logic_verification/analysis/test_lufs_meter_logic.py) | 未着手 |
| M05 | `Loopback Finder` / [source](../src/gui/widgets/loopback_finder.py) | A | 入出力ペア探索・coherent振幅・キャンセル・機器解決 | [P01](primitives.md#p01), [P02](primitives.md#p02), [P07](primitives.md#p07), [P08](primitives.md#p08), [P15](primitives.md#p15) | [test](../tests/logic_verification/gui/test_loopback_finder_ui_stop.py) | 未着手 |
| M06 | `Distortion Analyzer` / [source](../src/gui/widgets/distortion_analyzer.py) | D | THD/THD+N/SINAD・IMD・FFT/fit・平均・capture・sweep | [P01](primitives.md#p01), [P04](primitives.md#p04), [P07](primitives.md#p07), [P08](primitives.md#p08), [P09](primitives.md#p09), [P13](primitives.md#p13), [P15](primitives.md#p15) | [test](../tests/logic_verification/instruments/test_distortion_analyzer_worker.py) | 未着手 |
| M07 | `Advanced Distortion Meter` / [source](../src/gui/widgets/advanced_distortion_meter.py) | D | MIM/PIM/J-test・tone生成・残差・reset・worker停止 | [P01](primitives.md#p01), [P04](primitives.md#p04), [P09](primitives.md#p09), [P13](primitives.md#p13), [P15](primitives.md#p15) | [test](../tests/logic_verification/instruments/test_advanced_distortion_worker.py) | 未着手 |
| M08 | `Network Analyzer` / [source](../src/gui/widgets/network_analyzer.py) | D | 同期play/record・latency校正・chirp/sweep・応答/高調波・窓再計算 | [P01](primitives.md#p01), [P04](primitives.md#p04), [P08](primitives.md#p08), [P09](primitives.md#p09), [P13](primitives.md#p13), [P15](primitives.md#p15) | [test](../tests/logic_verification/gui/test_network_analyzer.py) | 未着手 |
| M09 | `Oscilloscope` / [source](../src/gui/widgets/oscilloscope.py) | A | trigger・pre/post履歴・math・persistence/heatmap・自動scale・周波数/立上り・校正 | [P03](primitives.md#p03), [P07](primitives.md#p07), [P10](primitives.md#p10), [P13](primitives.md#p13), [P19](primitives.md#p19) | [test](../tests/logic_verification/instruments/test_oscilloscope_logic.py) | 未着手 |
| M10 | `Raw Time Series` / [source](../src/gui/widgets/raw_time_series.py) | A | 長時間の間引き履歴・時刻/振幅表示・容量制限 | [P03](primitives.md#p03), [P13](primitives.md#p13), [P19](primitives.md#p19) | [test](../tests/logic_verification/gui/test_raw_time_series_formatting.py) | 未着手 |
| M11 | `Event Detector` / [source](../src/gui/widgets/event_detector.py) | B | sample位置付きevent・polarity/processing mode・目標時間・gap・統計・CSV | [P02](primitives.md#p02), [P03](primitives.md#p03), [P10](primitives.md#p10), [P13](primitives.md#p13), [P14](primitives.md#p14), [P15](primitives.md#p15) | [test](../tests/logic_verification/gui/test_event_detector_widget.py) | 未着手 |
| M12 | `Lock-in Amplifier` / [source](../src/gui/widgets/lock_in_amplifier.py) | C | 内部/外部参照・調波比・位相/振幅・postmix LPF・校正 | [P01](primitives.md#p01), [P03](primitives.md#p03), [P06](primitives.md#p06), [P07](primitives.md#p07), [P13](primitives.md#p13) | [test](../tests/logic_verification/instruments/test_lockin_amplifier_logic.py) | 未着手 |
| M13 | `Lock-in Harmonic Analyzer` / [source](../src/gui/widgets/lockin_harmonic_analyzer.py) | C | 参照位相推定・coherent区間・複素高調波・補償/校正 | [P03](primitives.md#p03), [P07](primitives.md#p07), [P09](primitives.md#p09), [P13](primitives.md#p13) | [test](../tests/logic_verification/instruments/test_lockin_harmonic_analyzer.py) | 未着手 |
| M14 | `Arbitrary Harmonic Generator` / [source](../src/gui/widgets/arbitrary_harmonic_generator.py) | C | 高調波振幅/位相・補償係数・出力・停止 | [P01](primitives.md#p01), [P02](primitives.md#p02), [P09](primitives.md#p09), [P13](primitives.md#p13) | [test](../tests/logic_verification/gui/widgets/test_arbitrary_harmonic_generator.py) | 未着手 |
| M15 | `Lock-in Spectrum Finder` / [source](../src/gui/widgets/lockin_spectrum_finder.py) | C | zoom/scan・周波数候補・ユーザーtarget・sonification | [P01](primitives.md#p01), [P03](primitives.md#p03), [P07](primitives.md#p07), [P14](primitives.md#p14), [P19](primitives.md#p19) | [test](../tests/logic_verification/instruments/test_lockin_spectrum_finder_sonification.py) | 未着手 |
| M16 | `Frequency Counter` / [source](../src/gui/widgets/frequency_counter.py) | A | 周波数推定・統計・Allan deviation・校正・reset | [P03](primitives.md#p03), [P07](primitives.md#p07), [P10](primitives.md#p10), [P13](primitives.md#p13) | [test](../tests/logic_verification/instruments/test_frequency_counter_logic.py) | 未着手 |
| M17 | `Lock-in Frequency Counter` / [source](../src/gui/widgets/lock_in_frequency_counter.py) | C | 位相追跡・Kalman/PID・分布統計・校正・精密表示 | [P03](primitives.md#p03), [P06](primitives.md#p06), [P07](primitives.md#p07), [P10](primitives.md#p10), [P13](primitives.md#p13) | [test](../tests/logic_verification/instruments/test_lockin_counter.py) | 未着手 |
| M18 | `Spectrogram` / [source](../src/gui/widgets/spectrogram.py) | B | FFT窓/hop・spectrum履歴・色/軸・split | [P03](primitives.md#p03), [P04](primitives.md#p04), [P19](primitives.md#p19) | [test](../tests/logic_verification/gui/test_spectrogram.py) | 未着手 |
| M19 | `Boxcar Averager` / [source](../src/gui/widgets/boxcar_averager.py) | B | 内部/外部gate・周期平均・MLS・reset・export | [P01](primitives.md#p01), [P03](primitives.md#p03), [P05](primitives.md#p05), [P14](primitives.md#p14) | [test](../tests/logic_verification/analysis/test_boxcar_logic.py) | 未着手 |
| M20 | `Goniometer` / [source](../src/gui/widgets/goniometer.py) | B | stereo XY/M-S・decay/heatmap・履歴snapshot・gap/停止 | [P02](primitives.md#p02), [P03](primitives.md#p03), [P10](primitives.md#p10), [P19](primitives.md#p19) | [test](../tests/logic_verification/analysis/test_goniometer_logic.py) | 未着手 |
| M21 | `Impedance Analyzer` / [source](../src/gui/widgets/impedance_analyzer.py) | D | 複素Z・動的取得長・LPF・sweep・open/short/load校正・補間・保存 | [P01](primitives.md#p01), [P03](primitives.md#p03), [P06](primitives.md#p06), [P07](primitives.md#p07), [P08](primitives.md#p08), [P12](primitives.md#p12), [P13](primitives.md#p13), [P14](primitives.md#p14) | [test](../tests/logic_verification/instruments/test_impedance_calibration.py) | 未着手 |
| M22 | `Noise Profiler` / [source](../src/gui/widgets/noise_profiler.py) | B | FFT平均・white/1/f/hum・密度/積分・peak・単位 | [P03](primitives.md#p03), [P04](primitives.md#p04), [P05](primitives.md#p05), [P09](primitives.md#p09), [P10](primitives.md#p10), [P13](primitives.md#p13) | [test](../tests/logic_verification/analysis/test_noise_profile_logic.py) | 未着手 |
| M23 | `Recorder / Player` / [source](../src/gui/widgets/recorder_player.py) | A | file読書き・record/play・一時file・writer停止・resample・経路 | [P02](primitives.md#p02), [P06](primitives.md#p06), [P14](primitives.md#p14), [P15](primitives.md#p15) | [test](../tests/logic_verification/gui/test_recorder_player_logic.py) | 未着手 |
| M24 | `Waveform Loop Player` / [source](../src/gui/widgets/waveform_loop_player.py) | A | 選択区間loop・seek/pause/stop・resample・出力mix | [P02](primitives.md#p02), [P06](primitives.md#p06), [P14](primitives.md#p14), [P15](primitives.md#p15) | [test](../tests/logic_verification/gui/test_waveform_loop_player.py) | 未着手 |
| M25 | `Transient Analyzer` / [source](../src/gui/widgets/transient_analyzer.py) | E | trigger録音・CWT/wavelet・ringing/decay・worker停止 | [P03](primitives.md#p03), [P10](primitives.md#p10), [P17](primitives.md#p17), [P19](primitives.md#p19) | [test](../tests/logic_verification/gui/test_transient_ringing_analysis.py) | 未着手 |
| M26 | `Sound Quality Analyzer` / [source](../src/gui/widgets/sound_quality_analyzer.py) | E | file解析・loudness/sharpness/roughness/tonality/fluctuation/articulation・再生/CSV | [P05](primitives.md#p05), [P06](primitives.md#p06), [P14](primitives.md#p14), [P15](primitives.md#p15), [P18](primitives.md#p18), [P19](primitives.md#p19) | [test](../tests/logic_verification/gui/test_sound_quality_analyzer.py) | 未着手 |
| M27 | `Timecode Monitor & Generator` / [source](../src/gui/widgets/timecode_monitor.py) | C | LTC decode/encode・fps・jam/offset/timezone・時刻校正 | [P01](primitives.md#p01), [P03](primitives.md#p03), [P13](primitives.md#p13), [P16](primitives.md#p16) | [test](../tests/logic_verification/instruments/test_timecode_monitor_ltc.py) | 未着手 |
| M28 | `BNIM Meter` / [source](../src/gui/widgets/bnim_meter.py) | B | binaural指標・相互相関・click試験/分数遅延・heatmap | [P01](primitives.md#p01), [P04](primitives.md#p04), [P08](primitives.md#p08), [P10](primitives.md#p10), [P19](primitives.md#p19) | [test](../tests/logic_verification/gui/test_bnim_meter.py) | 未着手 |
| M29 | `HRTF Player` / [source](../src/gui/widgets/hrtf_player.py) | E | SOFA/netCDF・HRIR選択/補間・rate補正・畳込みtail・回転/再生 | [P02](primitives.md#p02), [P06](primitives.md#p06), [P11](primitives.md#p11), [P12](primitives.md#p12), [P14](primitives.md#p14), [P15](primitives.md#p15) | [test](../tests/logic_verification/gui/test_hrtf_player_resample.py) | 未着手 |
| M30 | `Ultrasound AM Modulator` / [source](../src/gui/widgets/ultrasound_modulator.py) | E | AM/sideband filter・搬送波条件・入力meter・出力制限 | [P01](primitives.md#p01), [P02](primitives.md#p02), [P06](primitives.md#p06), [P13](primitives.md#p13) | [test](../tests/logic_verification/gui/test_ultrasound_modulator.py) | 未着手 |
| M31 | `Linearity Analyzer` / [source](../src/gui/widgets/linearity_analyzer.py) | D | 振幅sweep・応答fit・buffer管理・cancel/失敗 | [P01](primitives.md#p01), [P03](primitives.md#p03), [P07](primitives.md#p07), [P08](primitives.md#p08), [P12](primitives.md#p12), [P13](primitives.md#p13), [P15](primitives.md#p15) | [test](../tests/logic_verification/instruments/test_linearity_analyzer_logic.py) | 未着手 |
| M32 | `1PPS Monitor` / [source](../src/gui/widgets/one_pps_monitor.py) | C | pulse検出・sample間隔・波形履歴・clock校正 | [P03](primitives.md#p03), [P10](primitives.md#p10), [P13](primitives.md#p13), [P16](primitives.md#p16) | [test](../tests/logic_verification/gui/test_one_pps_monitor.py) | 未着手 |
| M33 | `Stereo Alignment Monitor` / [source](../src/gui/widgets/stereo_alignment_monitor.py) | B | balance・cross spectra・相関/M-S・phase・gang error履歴 | [P04](primitives.md#p04), [P05](primitives.md#p05), [P10](primitives.md#p10), [P19](primitives.md#p19) | [test](../tests/gui/test_stereo_alignment_regression.py) | 未着手 |
| M34 | `Spatial Binaural Mixer` / [source](../src/gui/widgets/spatial_binaural_mixer.py) | E | 複数source・位置/HRIR・binaural mix・play/stop | [P02](primitives.md#p02), [P06](primitives.md#p06), [P11](primitives.md#p11), [P14](primitives.md#p14), [P15](primitives.md#p15) | [test](../tests/logic_verification/gui/widgets/test_spatial_binaural_mixer.py) | 未着手 |
| M35 | `Processor Benchmark` / [source](../src/gui/widgets/processor_benchmark.py) | 基盤 | FFTサイズ/rate・極大FFT・描画込み測定・結果copy | [P04](primitives.md#p04), [P19](primitives.md#p19), [P20](primitives.md#p20) | 専用テスト未確認。FFT/UIの計測値とcancelを新設 | 未着手 |
| M36 | `Transmission Analyzer` / [source](../src/gui/widgets/transmission_analyzer.py) | E | PRBS同期・IR/応答・EVM・bit perfection・fractional delay/jitter・step | [P01](primitives.md#p01), [P03](primitives.md#p03), [P04](primitives.md#p04), [P08](primitives.md#p08), [P09](primitives.md#p09), [P10](primitives.md#p10), [P12](primitives.md#p12) | [test](../tests/logic_verification/core/test_transmission.py) | 未着手 |
| M37 | `Nonlinear Analyzer` / [source](../src/gui/widgets/nonlinear_analyzer.py) | E | SSS/inverse・latency・非線形kernel・drift/分数遅延・cancel | [P01](primitives.md#p01), [P06](primitives.md#p06), [P08](primitives.md#p08), [P11](primitives.md#p11), [P12](primitives.md#p12), [P15](primitives.md#p15) | [test](../tests/logic_verification/measurement_modules/test_nonlinear_analyzer.py) | 未着手 |
| M38 | `Lock-in Modeler` / [source](../src/gui/widgets/lock_in_modeler.py) | E | realtime SSS・weighted fit・Hammerstein保存・predistortion連携 | [P01](primitives.md#p01), [P08](primitives.md#p08), [P11](primitives.md#p11), [P12](primitives.md#p12), [P14](primitives.md#p14), [P15](primitives.md#p15) | [test](../tests/logic_verification/gui/widgets/test_lock_in_modeler.py) | 未着手 |
| M39 | `Response Viewer` / [source](../src/gui/widgets/response_viewer.py) | D | model読込・周波数応答・contour・Wiener/noise floor・圧縮特性 | [P04](primitives.md#p04), [P11](primitives.md#p11), [P12](primitives.md#p12), [P14](primitives.md#p14), [P19](primitives.md#p19) | [test](../tests/logic_verification/gui/widgets/test_response_viewer_wiener.py) | 未着手 |
| M40 | `Feedforward Compensator` / [source](../src/gui/widgets/feedforward_compensator.py) | E | model補償・inverse/平滑化・file処理・true peak ceiling・export | [P06](primitives.md#p06), [P11](primitives.md#p11), [P12](primitives.md#p12), [P14](primitives.md#p14), [P15](primitives.md#p15) | [test](../tests/logic_verification/gui/widgets/test_feedforward_compensator.py) | 未着手 |
| M41 | `Nonlinear Response Analyzer` / [source](../src/gui/widgets/nonlinear_response_analyzer.py) | E | 実験機能・multisine/noise・Bussgang/BLA LS/TSA SVD・latency/cancel | [P01](primitives.md#p01), [P04](primitives.md#p04), [P08](primitives.md#p08), [P12](primitives.md#p12), [P15](primitives.md#p15) | [test](../tests/logic_verification/core/test_nonlinear_response_analyzer.py) | 未着手 |

## 共通・外部連携（41外）

| ID | 機能 | サブ機能・互換性境界 | プリミティブ | ソース / 参照テスト | 状態 |
| --- | --- | --- | --- | --- | --- |
| C01 | Audio I/O・Remote Audio I/O | 物理/仮想・入力/出力mode・mix/mute/dither・排他・XRUN・再接続・v2の最大2ch/再送/期限 | [P02](primitives.md#p02), [P03](primitives.md#p03), [P06](primitives.md#p06), [P13](primitives.md#p13), [P15](primitives.md#p15) | [source](../src/core/audio_engine.py) / [test](../tests/logic_verification/core/test_audio_engine.py) | 未着手 |
| C02 | VST3 DUT | 別process host・discover・editor・reset・timeout・終了回収 | [P02](primitives.md#p02), [P15](primitives.md#p15) | [source](../src/core/vst_dut.py) / [test](../tests/logic_verification/core/test_vst_dut.py) | 未着手 |
| C03 | Settings・設定互換 | device識別・rate/block・profile選択・offline・保存失敗と復元 | [P02](primitives.md#p02), [P13](primitives.md#p13), [P14](primitives.md#p14), [P15](primitives.md#p15) | [source](../src/gui/widgets/settings.py) / [test](../tests/logic_verification/gui/widgets/test_settings.py) | 未着手 |
| C04 | 校正profile・単位 | V/FS・SPL・周波数/位相補正・1PPS/lock-in・校正済み状態・profile CRUD | [P12](primitives.md#p12), [P13](primitives.md#p13), [P14](primitives.md#p14) | [source](../src/core/calibration.py) / [test](../tests/logic_verification/core/test_calibration_profiles.py) | 未着手 |
| C05 | 比較・CSV/JSON・file形式 | ExportTrace・軸/単位・校正・metadata・比較・format選択 | [P13](primitives.md#p13), [P14](primitives.md#p14), [P19](primitives.md#p19) | [source](../src/core/export/trace.py) / [test](../tests/core/export/test_json_exporter.py) | 未着手 |
| C06 | MainWindow・Welcome・遅延load | 開始/停止・実状態・sidebar・offline起動・閉じる際の回収 | [P15](primitives.md#p15), [P19](primitives.md#p19) | [source](../src/gui/main_window.py) / [test](../tests/logic_verification/gui/test_main_window_activity.py) | 未着手 |
| C07 | Measurement Console・分離/split/compact | 能力宣言・primary action・同時表示・window再生成・サイズ | [P15](primitives.md#p15), [P19](primitives.md#p19) | [source](../src/gui/module_registry.py) / [test](../tests/logic_verification/gui/test_widget_capabilities.py) | 未着手 |
| C08 | 翻訳・theme・plot・操作 | 9言語・trキー・既定font・カーソル/zoom・線/heatmap・キー操作 | [P19](primitives.md#p19) | [source](../src/core/localization.py) / [test](../tests/logic_verification/core/test_localization_logic.py) | 未着手 |
| C09 | ログ・画像保存 | 例外log・log viewer・screenshot・既定保存先・失敗表示 | [P14](primitives.md#p14), [P15](primitives.md#p15), [P19](primitives.md#p19) | [source](../src/core/config_manager.py) / [test](../tests/logic_verification/gui/test_log_viewer_logic.py) | 未着手 |
| C10 | 配布・更新・起動 | Windows/macOS ARM/Intel/Linux・依存同梱・update通知・設定分離 | [P14](primitives.md#p14), [P15](primitives.md#p15), [P20](primitives.md#p20) | [source](../src/core/update_checker.py) / [test](../tests/logic_verification/core/test_update_checker.py) | 未着手 |

## 現行の制約と追加する能力

- `RingBuffer`は任意chだが、一つの消費read位置を持つ。mono複製、余剰ch切捨て、不足chのゼロ埋めも行う。次期の購読者別履歴・明示的対応表とは同一でない。
- `AudioEngine`の論理modeとnetwork v2は1/2ch。仮想4/8chの期待値を現行エンジンの実績と呼ばない。network拡張はC01の別契約。
- FFTManagerはplan/bufferを再利用するが、複数測定器の解析結果共有ではない。SpectrumとSpectrogramの窓や前処理が同じかを比較前に確認する。
- ExportTraceは軸・校正・metadataを持つが、Stream世代・Timebase・区間validityは必須項目でない。次期形式は版を分ける。
- 現行校正は全体の感度/profileを持つ。N-channelのChannelId別校正へ自動で複製して「確認済み」としない。
- Processor Benchmarkの専用テストは今回の検索では見つからない。全言語UI検証や共通registry検証を数値テストの代替にしない。

## 台帳の更新

```bash
./.venv/bin/python scripts/check_migration_inventory.py
```

キー/登録sourceとの一致、ID・状態、ローカルリンク、プリミティブとの双方向対応を検査する。
これは意味・数値の正しさやサブ機能の網羅性を判定しない。main同期時は差分の関数/テストも読み、両台帳とfixtureを更新する。
