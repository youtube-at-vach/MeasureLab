# 用語集追加にともなう調査レポート

MeasureLab のドキュメントから、一般ユーザーにとって難解と思われる専門用語を抽出し、`docs/glossary.md` および `docs/glossary.en.md` に追加した作業のレポートです。

---

## 1. 今回調査を行い、用語を追加したドキュメント・ウィジェット

以下のドキュメントおよびウィジェットの解説文から用語を抽出し、日英両方の用語集にわかりやすい解説を追加しました。

| 対象ドキュメント / ウィジェット | 追加・同期した用語 |
| :--- | :--- |
| **共通キャリブレーション** (`calibration.md`) | キャリブレーション (Calibration), dBFS, dBV / dBu, dB SPL, TrueRMS (真の実効値) |
| **BNIM Meter** (`bnim_meter.md`) | ITD (両耳間時間差), ILD (両耳間レベル差) |
| **Boxcar Averager** (`boxcar_averager.md`) | インパルス応答, ステップ応答 |
| **Goniometer** (`goniometer.md`) | リサージュ図形 (Lissajous Curves), 位相キャンセル (Phase Cancellation) |
| **HRTF Player** (`hrtf_player.md`) | HRTF (頭部伝達関数), SOFAファイル |
| **Lock-in Amplifier** (`lock_in_amplifier.md`) | 同期検波 / デュアルフェーズ検波, 時定数 (Time Constant) |
| **LUFS Meter** (`lufs_meter.md`) | LUFS, トゥルーピーク (True Peak) |
| **1PPS Monitor** (`one_pps_monitor.md`) | PPM (Parts Per Million), クロックドリフト |
| **Spectrum Analyzer** (`spectrum_analyzer.md`) | FFT (高速フーリエ変換), PSD (パワースペクトル密度), 窓関数 (Window Function), スペクトル漏れ (Spectral Leakage), A特性 / C特性, ノイズフロア, ホワイトノイズ / ピンクノイズ, マルチテーパー (Multitaper) |
| **Advanced Distortion Meter** (`advanced_distortion_meter.md`) | 混変調歪 (Intermodulation Distortion / IMD), SPDR (Spurious Free Dynamic Range), ジッター (Jitter) |
| **Arbitrary Harmonic Generator** (`arbitrary_harmonic_generator.md`) | 高調波 (Harmonics), 基本周波数 (Fundamental Frequency) |
| **Distortion Analyzer** (`distortion_analyzer.md`) | ENOB (Effective Number of Bits / 有効ビット数) |
| **Frequency Counter** (`frequency_counter.md`) | アラン偏差 (Allan Deviation) |
| **Impedance Analyzer** (`impedance_analyzer.md`) | インピーダンス (Impedance) と リアクタンス (Reactance), Q値 (Quality Factor) と 損失係数 (Dissipation Factor) |
| **Inverse Filter** (`inverse_filter.md`) | FIRフィルター (FIR Filter) と FIRタップ数 (FIR Taps) |
| **Linearity Analyzer** (`linearity_analyzer.md`) | 直線性 (Linearity) と ヒステリシス (Hysteresis) |
| **Network Analyzer** (`network_analyzer.md`) | コヒーレンス (Coherence), 群遅延 (Group Delay) |
| **Noise Profiler** (`noise_profiler.md`) | 1/fノイズ (Flicker Noise) と ハムノイズ (Hum Noise), 熱雑音 (Thermal Noise), 入力換算ノイズ (Equivalent Input Noise / EIN) |
| **Nonlinear Response Analyzer** (`nonlinear_response_analyzer.md`) | (非線形モデリングや混変調歪に関連) |
| **Oscilloscope** (`oscilloscope.md`) | トリガー (Trigger), 立ち上がり時間 / 立ち下がり時間 (Rise Time / Fall Time), Vpp (Peak-to-Peak 電圧) |
| **Sound Level Meter** (`sound_level_meter.md`) | 等価騒音レベル (Leq), 時間重み付け (Time Weighting), Z特性 (Z-Weighting) |
| **Spectrogram** (`spectrogram.md`) | フォルマント (Formant), メル尺度 (Mel Scale), ウォーターフォール表示 (Waterfall Display) |
| **Transient Analyzer** (`transient_analyzer.md`) | ウェーブレット変換 (Wavelet Transform) |

---

## 2. 未調査のウィジェット一覧 (今後調査が必要なもの)

`docs/widgets/` 以下に配置されているドキュメントのうち、今回の用語抽出フェーズでは精査を行わなかったウィジェットの一覧です。今後、ユーザーからのフィードバックや必要性に応じて、難解な用語の追加調査を行うことができます。

1. **Detachable Wrapper** (`detachable_wrapper.md` / `*.en.md`)
2. **Lock-in Frequency Counter** (`lock_in_frequency_counter.md` / `*.en.md`)
3. **Lock-in Harmonic Analyzer** (`lockin_harmonic_analyzer.md` / `*.en.md`)
4. **Lock-in Spectrum Finder** (`lockin_spectrum_finder.md` / `*.en.md`)
5. **Log Viewer** (`log_viewer.md` / `*.en.md`)
6. **Loopback Finder** (`loopback_finder.md` / `*.en.md`)
7. **Nonlinear Analyzer** (`nonlinear_analyzer.md` / `*.en.md`)
8. **Plot Comparer** (`plot_comparer.md` / `*.en.md`)
9. **Processor Benchmark** (`processor_benchmark.md` / `*.en.md`)
10. **Raw Time Series** (`raw_time_series.md` / `*.en.md`)
11. **Recorder Player** (`recorder_player.md` / `*.en.md`)
12. **Response Viewer** (`response_viewer.md` / `*.en.md`)
13. **Settings** (`settings.md` / `*.en.md`)
14. **Signal Generator** (`signal_generator.md` / `*.en.md`)
15. **Sound Quality Analyzer** (`sound_quality_analyzer.md` / `*.en.md`)
16. **Spatial Binaural Mixer** (`spatial_binaural_mixer.md` / `*.en.md`)
17. **Stereo Alignment Monitor** (`stereo_alignment_monitor.md` / `*.en.md`)
18. **Timecode Monitor** (`timecode_monitor.md` / `*.en.md`)
19. **Transmission Analyzer** (`transmission_analyzer.md` / `*.en.md`)
20. **Ultrasound Modulator** (`ultrasound_modulator.md` / `*.en.md`)
21. **Waveform Loop Player** (`waveform_loop_player.md` / `*.en.md`)
22. **Welcome** (`welcome.md` / `*.en.md`)
