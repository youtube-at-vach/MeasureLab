# Changelog

## [v0.6.1] - 2026-04-03

### Added

* **Benchmark**: Added Processor Benchmark module for evaluating real-time FFT and rendering performance with system hardware info and clipboard export.
* **Analyzer**: Added Mel scale option to Spectrogram frequency display.

### Changed

* **Perf**: Vectorized goniometer color palette generation and band power accumulation.
* **Perf**: Removed `time.sleep(0)` in tight numerical loops in `LockInSpectrumFinder`.
* **Perf**: Replaced polling loop with `threading.Event.wait` in `ImpedanceSweepWorker`.
* **Refactor**: Reworked `ImpedanceAnalyzer`, `LockInSpectrumFinder`, and `ImpedanceSweepWorker` to use config dataclasses.

### Fixed

* **I18n**: Completed multilingual translation files for Processor Benchmark and other UI strings.

## [v0.6.0] - 2026-03-27

### Added

* **Analyzer**: Introduced `Stereo Alignment Monitor` module for assessing phase correlation and stereo width.
* **Analyzer**: Added Loudness Range (LRA) calculation and configurable Target LUFS display to the `LUFS Meter`.
* **Audio**: Added a seekable playback position slider to the `Recorder Player` and enhanced audio callback robustness.
* **CI/CD**: Added macOS Intel (x64) DMG build to the release workflow.
* **Docs**: Added repository navigation links and updated project documentation.

### Changed

* **Perf**: Optimized LTC zero-crossing array allocations in chunk processing.
* **Perf**: Optimized lock-in spectrum finder background loop by replacing blocking sleep with thread yield.
* **I18n**: Updated translations and expanded test coverage across various modules.

### Fixed

* **Core**: Removed unused imports in recorder player and sound quality analyzer tests.

## [v0.5.9] - 2026-03-21

### Added

* **Tests**: Extensive test coverage improvements across Core and GUI modules including Calibration, Analysis, AudioEngine, and Localization.

### Changed

* **Perf**: Optimized `RingBuffer.read()` to avoid `np.concatenate` for reduced object allocation.
* **Perf**: Optimized recorder by saving in 1MB chunked blocks.
* **Perf**: Optimized software LTC decoding using `collections.deque`.
* **Perf**: Pre-calculated `np.searchsorted` in spectrum analyzer for faster UI rendering.
* **Core**: Replaced `time.sleep` with threading `Event` in Audio Engine for more accurate virtual stream timing.
* **Core**: Replaced `urllib` with `requests` for robust TLS connections in `UpdateChecker`.
* **Refactor**: Cleaned up legacy configuration parameters and removed unused internal API functions.
* **Docs**: Added troubleshooting steps for ASIO stream start failures in Network Analyzer.

### Fixed

* **Audio**: Added robust error handling for ASIO stream initialization and callback processing, using dummy callbacks to maintain active engines during Network Analyzer sweeps.
* **Signal Generator**: Limited multitone width processing to prevent overlap with adjacent tones.
* **I18n**: Fixed missing translation entries.
* **Build**: Fixed PyInstaller concurrency conflict in Windows CI.

## [v0.5.8] - 2026-03-16

> [!IMPORTANT]
> **Notice regarding version v0.5.8 replacement (2026-03-17)**
> A calculation bug was discovered in the initial release of v0.5.8 (commit `44779df5827c452d6e35c9ebf4b2c0de8f86d2f2`). This version has been updated with a fix. Please ensure you are using the corrected version.

### Added

* **Analyzer**: Added percentage Y-axis option to Distortion Analyzer sweeps.
* **Analyzer**: Added support for dBV and Watt units in Distortion Analyzer amplitude sweeps, including a calibration warning for these units.
* **Analyzer**: Introduced 24-tone equal temperament (24TET) and Just Intonation musical scales to Lock-in Spectrum Finder.
* **Analyzer**: Added logarithmic X-axis option for "Scan List Only" mode in Lock-in Spectrum Finder.
* **Analyzer**: Added 32768 buffer size option for scan mode in Lock-in Spectrum Finder.
* **Docs**: Updated README files with information about the GPT-5.2 Codex AI model.
* **Docs**: Updated `PROPOSED_FEATURES.md` with categorized sections for better organization of future ideas.

### Changed

* **Perf**: Optimized GUI event loop during module preloading by throttling `QApplication.processEvents()`.
* **Perf**: Optimized `hum_components` calculation and LTC decoder array iterations.
* **Perf**: Optimized audio engine device queries to reduce redundant system calls.
* **Refactor**: Improved translation key extraction and centralized localization file sorting for better maintainability.

### Fixed

* **Security**: Enforced restrictive permissions on directory creation in Lock-in Spectrum Finder.
* **Audio**: Fixed potential `sosfilt` errors by ensuring atomic filter parameter updates and adding exception handling.
* **UI**: Fixed false-positive dead code warnings in Network Analyzer and Transient Analyzer.
* **I18n**: Fixed leftover English placeholders and translation leaks across multiple languages.

## [v0.5.7] - 2026-03-10

### Added

* **Analyzer**: Added Resolution Bandwidth (RBW) and step size display styling improvements to the Lock-in Spectrum Finder's zoom mode.
* **Analyzer**: Added Musical Scale target generator and mains harmonics target management to the Lock-in Spectrum Finder.
* **Analyzer**: Introduced Power Noise Sonification enhancements with volume controls (dB gain) and a watchdog timer to the Lock-in Spectrum Finder.
* **I18n**: Added comprehensive Japanese translation updates and synchronized translation keys across all languages for the Sonification feature.
* **Docs**: Updated README files with information about the GPT-5.4 AI model.

### Changed

* **Refactor**: Reworked sonifier volume control to use dB gain and unified the oscillator bank.
* **Tests**: Expanded test coverage for dBFS, dBV, and SPL conversions in CalibrationManager, as well as impedance analyzer and lock-in harmonic analyzer features.

### Fixed

* **Security**: Fixed TOCTOU (Time-Of-Check to Time-Of-Use) vulnerabilities in recording temp file creation (`RecorderPlayer`).
* **Core**: Removed unused `jam_capture_auto` method and unused annotations imports.

## [v0.5.6] - 2026-03-06

### Added

* **Analyzer**: Added phase calculation and display to Lock-in Spectrum Finder, including rich scatter plot tooltips.
* **Analyzer**: Added target management features to Lock-in Spectrum Finder, with octave spacing options, predefined targets, and a dedicated UI tab.
* **Analyzer**: Dynamically generate mains harmonic frequencies up to the 16th order in `DEFAULT_SCAN_LIST`.
* **I18n**: Added comprehensive localization strings for scan targets, octave bands, phase, magnitude, and average text across all languages.

### Changed

* **Refactor**: Replaced `QHBoxLayout` with `QGridLayout` for target control buttons to improve UI layout in Lock-in Spectrum Finder.

### Fixed

* **Core**: Fixed potential closure issue in `check_and_add` by explicitly capturing `mf`.
* **UI**: Changed marker frequency range to be exclusive of start and stop frequencies to prevent out-of-bounds errors.

## [v0.5.5] - 2026-03-05

### Added

* **Analyzer**: Introduced Lock-in Spectrum Finder module (promoted from experimental).
* **Analyzer**: Added configurable display units (dBFS, dBV, dB SPL) for Lock-in Spectrum Finder amplitude computation.
* **Analyzer**: Added Exponential Moving Average (EMA) to the Lock-in Spectrum Finder.
* **Analyzer**: Added Peak Tracking feature to Lock-in Spectrum Finder zoom mode.
* **Analyzer**: Added "Int x Sync" and "Integer" frequency spacing options for Lock-in Spectrum Finder.
* **Analyzer**: Added selectable window functions (Rectangular, Hanning, Blackman-Harris, Flat Top) to Lock-in Spectrum Finder.
* **UI**: Expanded available buffer size options for non-basic modes in Lock-in Spectrum Finder.

### Changed

* **Perf**: Improved multitone peak search performance using list comprehensions.
* **Perf**: Optimized loop in linearity analyzer with vectorized operations.
* **Perf**: Vectorized timecode monitor jam capture algorithm.
* **Perf**: Optimized A-weighting impulse noise calculation.
* **Perf**: Optimized coarse frequency search by vectorizing linear equation solves.
* **Perf**: Optimized frequency array slice `argmax` for Lock-in Spectrum Finder.
* **Perf**: Cached static filter computations in sound quality analyzer.
* **Refactor**: Replaced `lockin_spectrum_analyzer.py` with `lockin_spectrum_finder.py`.
* **Refactor**: Improved Lock-in Spectrum Finder calculation accuracy with multi-rate downsampling, float64 precision, and optimized basis matrix.
* **Docs**: Added comprehensive documentation for Lock-in Spectrum Finder widget.
* **Docs**: Added tests for logic verification elements like `next_power_of_two` and `RawTimeSeriesWidget`.

### Fixed

* **Core**: Fixed unused variable lint error in sound quality analyzer.
* **Core**: Initialized averaging arrays to prevent attribute errors in progress updates.
* **I18n**: Fixed missing and duplicated translation keys.

## [v0.5.4] - 2026-03-02

### Added

* **Lock-in Amplifier**: Added fractional harmonic support with separate numerator and denominator controls and exact phase tracking.
* **Lock-in Amplifier**: Added "Very Slow 4x (262144 samples)" buffer size option and a method to set gain offset.
* **Network Analyzer**: Added single-channel mode selection for display.
* **Docs**: Updated documentation for LoopbackFinder, TransientAnalyzer, Lock-in Amplifier, NetworkAnalyzer, and updated PROPOSED_FEATURES.md.
* **I18n**: Added missing translation strings across all language files ("Very Slow 4x", "Absolute", "Relative", "Single-Ch Mode:").

### Changed

* **Network Analyzer**: Enhanced normalization and latency compensation.
* **Perf**: Optimized coarse frequency search algorithm, spectrum analyzer octave smoothing with caching, and `optimize_frequency` by reusing thread-local buffers.
* **Refactor**: Major refactoring across UI widgets (SpectrumAnalyzer, SignalGenerator, SettingsWidget, DistortionAnalyzer, Oscilloscope) to reduce complexity and improve maintainability.
* **Refactor**: Refactored `AudioEngine._master_callback` for better readability.

### Fixed

* **Security**: Fixed insecure file permissions for calibration configuration.
* **UI**: Fixed a `ValueError` crash in the Oscilloscope when processing empty data.
* **Core**: Fixed a `RingBuffer` crash caused by channel mismatch.
* **Core**: Fixed an issue where test tones and measurements were not stopped immediately after calibration saves.
* **Tests**: Cleaned up the test suite, removed redundant tests, fixed thread leaks in OnePPSMonitor tests, and improved mocking in UpdateChecker tests.

## [v0.5.3] - 2026-02-25

### Major

* **Lock-in Harmonic Analyzer**: Introduced a new module for ultra-precision THD measurement using parallel reference-locked matrix projection. The analyzer supports dynamic harmonic order limits up to 200 and parallel IQ detection.
* **64-bit Audio Engine**: Added an option to enable 64-bit audio processing precision throughout the audio engine, including float64 FFT optimization.
* **Sound Quality Enhancements**: Added Fluctuation Strength, Articulation Index (AI), Coherence calculation, IR SNR, and CSV export functionality to the Sound Quality Analyzer.

### Added

* **Network Analyzer**: Implemented averaging for fast sweeps and time alignment for recorded data.
* **Signal Generator**: Added selectable frequency calibration source functionality to the UI.
* **Docs**: Added dedicated documentation for Oscilloscope, Signal Generator, and Lock-in Harmonic Analyzer.

### Changed

* **UI**: Applied dynamic monospace font family (`MONOSPACE_FONT_FAMILY`) uniformly across frequency displays and analyzer widgets.
* **Perf**: Optimized A-weighted noise calculation using `np.dot` and improved audio dither generation to reduce array allocations.
* **Config**: Deprecated the old THD analyzer, renaming it to "Lock-in Harmonic Analyzer" and hiding it under an `--experimental` flag to streamline the UI.
* **Test**: Cleaned up the pytest suite in logic verification and consolidated ConfigManager/MainWindow logic tests.

### Fixed

* **Analysis**: Fixed division by zero bug in frequency axis analysis.
* **Signal Generator**: Fixed a bug where parameter changes were not correctly updating the output buffer.
* **Audio**: Fixed swallowed exceptions in Impedance Analyzer and Lock-In Amplifier callbacks.
* **I18n**: Fixed translation leaks across multiple language files and updated `.json` assets.

## [v0.5.2] - 2026-02-19

### Major

* **Official Mac Support**: The "Experimental" warning has been removed. Universal Binary (arm64/x86_64) builds are now officially supported.
* **Platform Standards**: Configuration and data files now strictly follow platform conventions (XDG on Linux, `Application Support` on macOS).

### Added

* **Docs**: Added macOS (arm64) quickstart instructions and Gatekeeper bypass guide.
* **Core**: Implemented dynamic monospace font selection for consistent rendering across platforms.
* **Core**: Added `certifi` integration for robust SSL verification in Update Checker.

### Changed

* **Config**: Moved configuration and calibration data storage to standard user data directories.
    * macOS: `~/Library/Application Support/MeasureLab`
    * Linux: `~/.config/MeasureLab` (or `$XDG_CONFIG_HOME`)
* **Config**: Default screenshot directory now resolves to a platform-specific location.
    * macOS: `~/Pictures/MeasureLab` (Standard Pictures folder)
    * Windows/Linux: `AppRoot/screenshots` (Local to application root)
* **UI**: Updated application icon.
* **Theming**: Enforced `Fusion` style on macOS to ensure consistent visual appearance across light/dark themes.

### Fixed

* **Core**: Fixed potential path traversal and configuration loading issues.
* **UI**: Resolved font rendering warnings on macOS.
* **Net**: Fixed SSL certificate verification errors on some systems.

## [v0.5.1] - 2026-02-18

Starting from this version, the baseline Python version is officially Python 3.12.
As a result, older Linux systems such as Ubuntu 18.04 may no longer be supported.

### Major

* **Bit Depth Analyzer**: Introduced a new module for measuring bit depth and quantization levels, featuring dedicated GUI, core estimator logic, and comprehensive documentation.
* **1PPS Monitor Enhancement**: Significant update to the One PPS Monitor including triggered waveform visualization, pulse indicators, and input latency compensation.

### Added

* **Hardware Test Suite**: Introduced a new automated hardware verification suite using the `--hardware` pytest marker.
    * Added automated hardware metrics for THD+N and IMD SMPTE.
    * Added lock-in amplifier accuracy, signal stability, and phase stability tests.
    * Added multitone distortion (TD+N) measurement using the MIM method.
    * Added hardware linearity sweep and crosstalk tests with parameterized frequencies.
    * Automated generation of a simplified `report.json` for hardware test results.
* **Core**: Added fallback input latency estimation for audio streams reporting zero latency.
* **1PPS**: Added configurable target PPS support and improved glitch handling.
* **I18n**: Added internationalization for One PPS Monitor statistics and Bit Depth Analyzer terms.

### Changed

* **Core**: Downgrade NumPy to version 2.2.6 in constraints to resolve Windows DLL load failures.
* **Security**: Centralized hardcoded GitHub update URLs for improved maintainability.
* **Docs**: Added a new Development Guide and Glossary; updated Signal Generator manuals for MLS/PRBS parameters.
* **Test**: Consolidated the test suite into a logic verification structure and cleaned up obsolete functional tests.
* **Refactor**: Consolidated hardware test suite and cleaned up pytest configuration.
* **Refactor**: Migrated functional tests to logic verification.
* **Log**: Reduced log verbosity from INFO to DEBUG for smoother operation.

### Fixed

* **UI**: Fixed a bug in Signal Generator where waveform switching during playback could fail.
* **UI**: Fixed infinite loop and race condition in `RecorderPlayer`.
* **Core**: Fixed incorrect noise integration calculation for non-linear frequency axes.
* **Core**: Fixed race condition in AudioEngine stream startup.
* **I18n**: Fixed untranslated keys in multilingual files (Japanese, etc.) and improved resource safety.
* **CI**: Resolved unused import errors in hardware tests.

### Documentation

* **Docs**: Added "JAM Memories" section to Timecode Monitor documentation.

## [v0.5.0] - 2026-02-13

### Major

* **Python Build**: Upgraded project to Python 3.12 for improved performance and modern feature support
* **UI**: Major reorganization of the Settings Widget, introducing a tabbed interface for General, Audio, and Calibration settings

### Added

* **UI**: New "BIN Center" frequency snapping feature for Signal Generator and Distortion Analyzer
* **UI**: Added "Stored Calibration Values" section in Settings for persistent hardware correction factors
* **UI**: Interactive dithering options with support for multiple bit-depths and noise shaping
* **Docs**: Comprehensive update to README.md including detailed OS support status and tables

### Changed

* **UI**: Improved organization and visibility of audio device settings and host API selection
* **Log**: Optimized log verbosity by setting many repetitive INFO logs to DEBUG across GUI widgets
* **Core**: Improved Timecode Generator calibration stability and reliability

### Fixed

* **Core**: Fixed calibration factor wrap-around/overflow issue in Timecode Generator
* **UI**: Fixed broad exception handling in `main_gui.py` by implementing proper error logging
* **UI**: Fixed translation leaks in `OnePPSMonitor` and improved multi-language consistency
* **UI**: Fixed crash in Linearity Analyzer when operating in specific modes or with complex configurations

### Performance

* **Perf**: Optimized `TimecodeMonitor` by improving deque usage efficiency
* **Perf**: Enhanced frequency estimation algorithms for better real-time response

## [v0.4.4] - 2026-02-12

### Added

* UI: New update notification system on the Welcome screen
* UI: Advanced Calibration section in Settings (ppm for frequency, mdB/dB for gain offset)
* UI: Interactive LPF and HPF tabs in Signal Generator for precise band-limiting
* I18n: Complete translation updates for Chinese, Korean, Portuguese, and Russian

### Changed

* UI: Renamed "Save As..." profile button to "Duplicate Profile" for clarity
* Core: Improved reciprocity and consistency of calibration factors across modules

### Fixed

* Core: Fixed major calibration persistence issue (ensured profile independence)
* Core: Fixed 1PPS calibration factor being overwritten when loading old profiles
* UI: Fixed crash in Linearity Analyzer when using Hysteresis mode
* UI: Suppressed GNOME portal noise in logs via QT_LOGGING_RULES

### Performance

* Perf: Optimized Tone/Noise generation algorithms in Signal Generator
* Perf: Implemented buffered I/O for high-speed audio recording
* Perf: Optimized buffer memory allocation for Linearity Analyzer
* Perf: Capped frequency measurement update intervals for high stability

## [v0.4.3] - 2026-02-09

### Added

* Core: 1PPS Monitor module with pulse detection, drift calculation, and outlier rejection
* Core: Online least squares regression for cumulative PPM and refined outlier rejection
* UI: Dynamic precision formatting for THDN and distortion values
* UI: Selectable output channel for loopback reference mode
* Security: Secured wisdom persistence (JSON/Base64) and added SECURITY.md

### Changed

* Perf: Optimized A-Weighting curve calculation with content-based caching
* Perf: Optimized frequency allocations and audio callback error handling
* Perf: Offloaded NoiseProfiler analysis to QThreadPool (non-blocking)
* Core: Improved frequency estimation accuracy with two-pass MSE minimization
* Core: Rename `_nco_phase` to `_nco_phase_rad` for smooth frequency transitions

### Fixed

* Security: Fix path traversal vulnerabilities in ConfigManager and CalibrationManager
* Core: Fix missing error signal in NoiseAnalysisWorker
* Core: Fix potentially unsafe pickle usage for wisdom files
* UI: Fix translation keys overlap and missing keys for output channels
* UI: Disable mode combo box during active measurements to prevent invalid states

## [v0.4.2] - 2026-02-05

Note: The Mac version is still unsupported and is being distributed for testing purposes only. The developer does not own a Mac, so no guarantees can be made regarding its functionality.

### Added

* Core: HRTF Player now resamples HRIR data to match the audio engine sample rate
* Docs: Added GitHub Sponsors funding configuration

### Changed

* Core: Improved Ultrasound Modulator phase synchronization and sideband logic

### Fixed

* Core: Fix crash in `AudioCalc.optimize_frequency` when signal is empty
* Core: Fix clicks in Ultrasound Modulator when changing LPF parameters
* UI: Fix theme application logic in LockInAmplifierWidget
* Core: Fix Overall SPL weighting calculation in Spectrum Analyzer

## [v0.4.1] - 2026-02-01

> [!WARNING]
> **Mac版の試験リリースについて / About Mac Experimental Release**
>
> * 今回のリリースには macOS 版 (Universal Binary) の試験的なビルドが含まれています。
> * **動作保証はありません (No operation guarantee)**: 開発チームは Mac 実機を所持していないため、動作確認は行われていません。
> * **未署名です (Unsigned)**: Apple の開発者署名は行われていません。実行するには Gatekeeper の設定変更や「右クリックして開く」等の操作が必要になる場合があります。
> * 不具合報告は歓迎しますが、対応できない場合があります。ご了承ください。
>
> * This release includes an experimental build for macOS (Universal Binary).
> * **Unverified**: We do not verify this build as we do not own Mac hardware.
> * **Unsigned**: This application is not signed with an Apple Developer ID. You may need to bypass Gatekeeper to run it.

### Added

* UI: `Linearity Analyzer` に Y 軸ズーム設定（+/- 1dB 許容線表示など）を追加
* UI: `Lock-in Frequency Counter` に PID 制御、FLL (Frequency Locked Loop)、および統計表示機能を追加
* UI: `Lock-in Frequency Counter` にプロット平滑化（Smoothing）機能を追加
* Core: `Ultrasound Modulator` のヒルベルトフィルタ設計にフォールバック処理を追加
* Core: `Frequency Counter` にセグメント長の自動最適化およびブラックマン窓を導入し、精度を向上
* Core: `Audio Engine` において、Audio Host API (WASAPI/ASIO等) 情報を保存・利用し、デバイス特定精度を向上
* Tool: Pytest 実行用のエージェントワークフローおよび `tool_usage.md` を追加

### Changed

* Perf: `HRTF` 指標計算（ITD/ILD/Energy/GD）をベクトル化により高速化
* Perf: `Linearity Analyzer` のコールバックバッファを最適化
* Perf: `SoundLevelMeter` の統計およびヒストグラムの GUI 更新レートを最適化
* Perf: `Lock-in` 計算において、参照信号のキャッシュ化と配列の書き込み可能性を確保し最適化
* Core: `Linearity Analyzer` のループバック参照時に FLL ロックを無効化するよう改善
* Core: `Frequency Counter` の表示精度（小数点以下桁数）を標準偏差に基づき動的に調整
* Core: システム言語の自動検出ロジックを向上（Windows ロケールマッピングの追加）
* UI: `Lock-in Frequency Counter` の UI をタブ構成に整理し、操作性を改善
* Docs: `README.md` およびプロジェクト紹介動画、コントリビューター情報を更新
* Docs: ロックイン周波数カウンターの NCO 周波数に関する注記を追加
* Docs: `PROPOSED_FEATURES.md` に新規提案を追加
* Docs: オシロスコープのマニュアルに A/B 数学モードの記述を追加
* Docs: `tool_usage.md` を追加し、テスト・リンターの実行手順を整備

### Fixed

* Fix: `Oscilloscope` および `Spectrum Analyzer` のオーディオコールバックにおけるレースコンディションを `queue` の導入により修正
* Fix: `Linearity Analyzer` において無音信号時の SNR 計算が不安定になる不具合を修正
* Fix: `Advanced Distortion Meter` の PIM 解析でビンにスナップした周波数を使用するよう修正
* Fix: `Frequency Counter` のモード切替時のリセット処理およびタイミングループを修正
* Fix: `Ultrasound Modulator` および `Linearity Analyzer` における翻訳キーの漏れ（Translation leaks）を修正
* Fix: `ConfigManager` における不要な空行の削除
* CI: `test_frequency_counter_reset.py` におけるリンターエラーを修正
* Build: `pyqt6-qt6` 等の依存関係をアップデート
* Refactor: テストコードの構成を `functional`, `logic_verification`, `benchmarks` に再編し可読性を向上
* CI/CD: Mac 版ビルドワークフロー (試験的) を追加

## [v0.4.0] - 2026-01-29

### Added

* UI: `Linearity Analyzer` ウィジェットを追加。SNR 測定、ノイズフロアの可視化、ゲイン精度や線形範囲の統計表示に対応
* Core: `Ultrasound Modulator` にヒルベルト変換を用いた単側波帯 (SSB) 変調モードを追加
* Docs: オシロスコープの英語マニュアルに残光表示 (Persistence) 設定の詳細を追加

### Changed

* Perf: `Noise Profiler` のウィンドウ生成および周波数検索を最適化
* Perf: `Oscilloscope.estimate_frequency_hz` をベクトル化により高速化
* Perf: `AudioCalc.optimize_frequency` の時間軸生成をキャッシュ化
* Perf: `calculate_lockin_measurement` をドット演算により高速化
* Core: `Frequency Counter` のサインフィッティング処理をワーカースレッドへ移行

### Fixed

* Fix: `drawContents` メソッドにおける `None` ペインターのハンドリングを改善
* Fix: オーディオコールバック内のブロッキングな `print` 文を削除
* I18n: 「Carrier Mode」などの欠落していた翻訳キーを追加
* Refactor: 変数名の改善 (単一文字 `l`, `r` から `left`, `right` へ)
* CI: `ruff` によるリンティング対象を全リポジトリに拡大し、`main_gui.py` を `mypy` チェック対象に追加

## [v0.3.9] - 2026-01-26

### Added

* Docs: `CONTRIBUTING.md` を追加し、開発ガイドラインを整備
* UI: Oscilloscope に校正済み RMS および Vpp 測定表示を追加
* UI: Lock-in Amplifier のスピンボックス表示桁数を 4 桁に拡張

### Changed

* Docs: Lock-in Amplifier にキャリブレーション手順を追加

### Fixed

* UI: Oscilloscope の Vrms および Vpp 表示の計算不具合（重大なバグ）を修正
* Core: Oscilloscope のオーディオコールバックにおけるメモリ割り当ての問題をリングバッファ導入により修正
* Core: Signal Generator で波形ごとのクレストファクターを考慮し、RMS 振幅計算の精度を向上
* UI: Oscilloscope の Y 軸ラベル（0, 0.5, 1）を非表示にし、混乱を防止

## [v0.3.8] - 2026-01-25

### Added

* UI: オシロスコープの残光表示（`Persistence / Eye Pattern`）機能を追加（減衰・強度設定付き）
* Core: `AllanWorker` を導入し、Allan Deviation の非同期計算に対応

### Changed

* Perf: `AudioCalc` の A-weighting 計算を `lru_cache` で最適化
* Perf: スペクトル平滑化のビン探索をバイナリサーチにより最適化
* I18n: 初回起動時のシステム言語自動検出機能を実装
* Docs: `PROPOSED_FEATURES.md` を信号計測フォーカスへリファクタリングし、全体を整理

### Fixed

* Core: Oscilloscope および Spectrogram ウィジェットにおけるオーディオコールバック等のリソースリークを修正
* I18n: 翻訳キーの不足と重複、および他言語への漏れを修正
* Chore: Allan Deviation 関連の不要なテスト・再現スクリプトを削除

## [v0.3.7] - 2026-01-24

### Changed

* Perf: `resample` パフォーマンスをインポート最適化により改善
* Perf: インピーダンス校正（`Impedance calibration`）をバイナリサーチとキャッシングで最適化
* Perf: サイン波フィッティング（`Sine fitting`）を正規方程式（Normal Equations）の使用により最適化
* Perf: マルチトーンのビン探索（`Multitone Bin Search`）をバイナリサーチにより最適化
* Core: `np.blackman` を `scipy.signal.get_window('blackmanharris')` に置き換え（distortion tests）

### Fixed

* Test: `test_mim` の期待 PIM 値を -80dBc から -77dBc に修正（信号合成のRMS反映）
* I18n: 翻訳キーの欠落を修正し、チェッカースクリプトを更新

## [v0.3.6] - 2026-01-20

### Added

* UI: Sound Quality Analyzer のグラフを Loudness, Sharpness, Roughness, Tonality の個別タブに再構成
* UI: 再生中のプロット自動追従機能およびクリック操作の改善
* Core: 高品質な2段階ポリフェーズリサンプリングによる解析用データの標準化 (48kHz)
* Core: Timecode Generator 有効化時に Timecode Monitor を自動開始する機能を追加
* Core: BNIM Meter のニューラルマップ対称性テストを追加
* CI/CD: 翻訳キーの整合性チェック (`check_trn_keys.py`) および Markdown リントをワークフローに追加

### Changed

* Perf: FFT パイプラインとウィンドウ生成を float32 向けに最適化
* Perf: フィルタ係数計算のキャッシュ加（`lru_cache`）とリアルタイムコールバックのバッファ割り当てを最適化
* Perf: `LTCDecoder` のリセット処理を最適化
* Docs: Markdown のリストインデント形式を標準化し、全体的な読みやすさを向上
* Build: `ruff` および GitHub Actions の依存関係をアップデート

### Fixed

* Core: SoundLevelMeter における LE 積分器の冗長なロジックを修正
* UI: Distortion Analyzer のプロット更新およびテーブル項目の再利用を改善
* Docs: クイックスタートガイドの GitHub リリース URL を修正
* Config: `.gitignore` 内のパスの大文字小文字設定を修正

## [v0.3.5] - 2026-01-17

### Added

* UI: Impedance Analyzer にスピーカー配線図を表示するボタンを追加
* Docs: スピーカーインピーダンス測定のレシピと SVG 配線図を追加
* Docs: インピーダンス測定ガイドに「測定範囲と限界」セクションを追加

### Changed

* Docs: ドキュメント全体のリスト形式を標準化し、整理を強化
* Docs: 英語ドキュメントのヘッダーを整理し、翻訳管理を改善

### Fixed

* Core: サンプルレートの入力値を整数型にキャストするよう修正
* CI/CD: リリースワークフローに `mini-racer` の依存関係を追加

## [v0.3.4] - 2026-01-16

### Added

* Docs: ドキュメント（PDF/HTML）の数式レンダリングに KaTeX を導入し、PDF 生成フローを確立
* Docs: オーディオインターフェースおよび SPL キャリブレーション手順のドキュメントを追加
* UI: スプラッシュスクリーンのメッセージ表示を改善（テキスト折り返し、ウィンドウサイズ拡大、FFT最適化時のガイダンス詳細化）

### Changed

* CI/CD: リリースアセットに PDF マニュアル（日本語/英語）を含めるようワークフローを構築
* Docs: マークダウンのアラート記法を `!!! type` (Admonition) 形式に統一し、PDF レンダリングを修正
* Docs: ドキュメントビルド依存関係を `py-mini-racer` から `mini-racer` へ移行し、互換性を向上

### Fixed

* CI/CD: ワークフローの権限設定（`permissions`）を修正し、セキュリティ警告を解消
* Docs: PDF 生成時の数式レンダリング不具合および依存関係（qrcode等）の不足を修正

## [v0.3.3] - 2026-01-15

### Added

* Buffer Optimization 設定（Aggressive / Huge）を追加し、サンプルレートに基づいたバッファサイズ動的計算を実装
* CI/CD ワークフローに PDF ドラフト生成 (mkdocs-with-pdf) を追加
* AppImage および Windows ビルドワークフローに GUI セルフテスト（起動確認）を追加
* PyFFTW の wisdom ファイルを XDG 準拠のユーザーデータディレクトリ (`~/.local/share/MeasureLab` 等) に保存するように変更

### Changed

* MkDocs のプライマリナビゲーションを日本語化し、翻訳マッピングを反転（ja -> en）
* サイト名を「MeasureLab オペレーションマニュアル」に変更
* ドキュメントの構成を大幅に拡充（Widget Guide, Quickstart, Measurement Recipes の日本語・英語対応を完了）

### Fixed

* Linux AppImage 環境で不足していた `libportaudio2`, `libxcb-*`, `libegl1` 等の依存関係を追加し、起動安定性を向上
* ドキュメントの 404 リンク切れや画像参照エラーを修正

### Documentation

* Widget Guide, Quickstart, Measurement Recipes, Appendix を含むほぼ全てのドキュメントを日本語・英語のバイリンガル対応完了
* README にプロジェクトバナー画像と歓迎メッセージを追加

## [v0.3.2] - 2026-01-13

### Added

* HRTF Player モジュールを追加（音源の読み込み、回転制御、多言語対応）
* FFTManager をコアモジュールに追加し、FFT 計算の最適化と共通化を実装
* Spectrum Analyzer に Ultra Large Window（超巨大ウィンドウサイズ）オプションを追加
* BNIM Meter にクリックでのテスト信号再生機能とプロット・ドラッグ操作の改善を追加

### Changed

* 全モジュール（Network Analyzer, Distortion Analyzer, BNIM Meter, Spectrogram 等）の FFT 計算を FFTManager に移行し、UI のフリーズ防止とパフォーマンスを向上
* 日本語翻訳のカタカナ末尾長音（「ー」）を標準ガイドラインに従い統一（アナライザー、カウンター等）
* Frequency Counter から 1 秒以上の測定オプションを削除
* FFT 最適化設定に巨大サイズ（Huge sizes）のオプションを追加
* GitHub リリースワークフローを FFTManager および pyfftw のパッケージングに対応するよう更新

### Fixed

* FFT 最適化ダイアログが処理完了前に閉じて UI がロックされる不具合を修正
* Spectrogram におけるオーディオバッファのオーバーフロー処理を改善
* 多数のファイルにわたる Ruff 警告（Lint エラー）およびコードスタイルを修正

### Localization

* HRTF Player、BNIM Meter の新機能、およびメニュー項目の翻訳を全 9 言語に追加・更新

### CI/CD

* 依存関係に `pyfftw` を追加
* Python 依存関係のアップデート (Dependabot)

## [v0.3.1] - 2026-01-06

### Added

* Signal Generator に AM（振幅変調）を追加し、深さ設定付き UI を実装
* Signal Generator に FM（周波数変調）を追加し、UI コントロールを拡充
* Signal Generator にバーストウィンドウとチャネル別ディレイ／ディレイ設定 UI を追加
* Signal Generator にディレイドコピー機能を追加し、UI 操作を実装

### Changed

* SignalGeneratorWidget の波形選択と動的 UI 更新を改善
* FractionalDelayLine を削除し、ディレイ実装を整理

### Fixed

* SignalGenerator のバッファインデックス計算を調整し、浮動小数の端境値を避けるよう改善

### Localization

* AM 変調と深さ設定、FM やディレイ関連の新機能を多言語翻訳に追加

## [v0.3.0] - 2026-01-05

### Changed

* Loopback Finder が PipeWire/JACK 常駐モード中は使用不可である旨を UI に明示し、開始/停止ボタンを自動で無効化するように変更
* Frequency Counter の更新間隔に上限を設け、極端な遅延やリフレッシュ停滞を防止

### Fixed

* Timecode Monitor の start/stop サイクルでコールバック登録を確実に解除し、ID=0 や失われた ID を含めてクリーンアップできるように改善
* Timecode Monitor の開始時に残存コールバックを検出して安全に停止してから再登録するディフェンシブ処理を追加
* エラーハンドリングで例外型を明示し、ログ/メッセージの診断精度を向上

### Localization

* Loopback Finder の利用可否メッセージを各言語の翻訳に追加・更新

### Tests

* Timecode Monitor の LTC 表示オフセット計算とコールバック解除に関するユニットテストを追加し、pytest から `src` を直接 import できるよう tests/conftest を追加

### CI/CD

* GitHub Actions ワークフローを最新の actions バージョンと権限設定に更新

### Documentation

* README から不要な文言を削除

## [v0.2.9] - 2026-01-03

### Added

* BNIM Meter モジュールを追加（ステレオ入力から ITD/ILD のニューラルマップを可視化）
* BNIM Meter に ILD（両耳間レベル差）重み付けオプションを追加
* スクリーンショット保存機能を追加（出力先ディレクトリを Settings から指定可能）
* Timecode Monitor に監視の Start/Stop トグルを追加

### Changed

* ThemeManager のテーマ検出と適用を改善し、環境互換性を向上
* `src` をパッケージとして明示し、起動/テスト時の import 安定性を改善（CI で `PYTHONPATH` を設定）
* スタンドアロンスクリプト実行時の `sys.path` 調整を改善

### Fixed

* CI 上での PyQt6/Qt6 ランタイム設定と依存関係インストールを修正し、リンク不具合を解消
* インストールログ `pip_install.out` が追跡されないよう `.gitignore` を更新

### Tests

* BNIM Meter のユニットテストを追加

### Documentation

* AGENT.md を更新（セットアップ手順、ローカライズガイド、環境情報）

## [v0.2.8] - 2026-01-01

### Added

* Timecode Monitor & Generator モジュールを追加 (LTC エンコーディング / デコーディング、JAM メモリ機能)
* TimecodeMonitor にフレームベース計算、ドロップフレーム率対応、複数チャネル FPS 表示、タイムゾーン機能を追加
* 信号生成器に PRBS ウェーブフォーム生成を追加 (Order / Seed UI制御)
* Timecode Monitor 関連の多言語翻訳キーを拡充

### Changed

* TimecodeMonitor のタイムゾーン処理を UTC ベースへ改善し、内部時間基準の一貫性を強化
* TimecodeMonitor と LTCDecoder のフレーム時間追跡とエポック管理を改善
* Lock-in Frequency Counter の応答性とジッター解析を強化

### Fixed

* TimecodeMonitor のジェネレーター状態管理をキャリブレーション中に改善
* 入力オフセットフレームの総フレーム計算への適用を修正
* LTC 生成のタイムゾーン処理とジェネレーター状態リセットを修正
* TimecodeMonitor の入力オフセット処理を改善
* 複数言語のテキスト翻訳を更新

### Tests

* LTC エンコーダー / デコーダーのユニットテストと TimecodeMonitor 入力遅延処理テストを追加
* 複数チャネル Timecode Monitor テストを追加

## [v0.2.7] - 2025-12-28

### Added

* Sound Quality Analyzer モジュールを追加 (Loudness, Sharpness, Roughness, Tonality)
* Lock-in Frequency Counter モジュールを追加 (信号検出, ゲート制御, チャネル選択)
* Frequency Counter にジッターヒストグラムおよび解析機能を追加
* 測定メーターの詳細表示切り替え機能を追加 (ENOB 等の高度なメトリクス表示に対応)
* 翻訳管理スクリプト (`check_trn_keys.py`) を追加

### Changed

* アプリケーション名を「MeasureLab」へ変更しブランディングを統一
* Lock-in Frequency Counter の応答性改善と UI 整理を強化
* 起動時スプラッシュスクリーンのメッセージ多言語化とフィードバック表示を強化
* GUI 描画のチラつき（フラッシュ）防止を改善
* AGENT.md の開発環境手順を更新 (グローバル Python 環境の推奨)

### Removed

* Lock-in Frequency Counter の位相ドリフトインジケーターを削除 (安定性向上のため)
* 未使用または重複した翻訳キーを整理

### Documentation

* README および関連ドキュメントのブランディングを「MeasureLab」へ更新

## [v0.2.6] - 2025-12-21

### Changed

* オーディオデバイス一覧にホスト API 名を併記し、入力・出力先の選択時にホスト環境を判別しやすく改善
* PyInstaller の onefile / onedir ビルド手順を整理し、Windows と Linux 向けパッケージ生成フローを強化

## [v0.2.5] - 2025-12-20

### Added

* アプリ起動時のスプラッシュスクリーンを追加し、初期化メッセージの多言語対応とプライマリディスプレイ中央表示を実装
* Impedance Analyzer に手動タイムシリーズ取得とプロット機能を追加し、関連用語の翻訳を拡充
* Lock-in Amplifier ウィジェットにナイキスト周波数に応じた動的周波数制限を追加

### Fixed

* Windows のダークテーマが正しく適用されるようテーマ管理をプラットフォーム別に調整し、背景やコントロールの配色崩れを解消

## [v0.2.4] - 2025-12-17

### Added

* Transient Analyzer モジュールを追加し、メインウィンドウ統合、録音時間の自動停止、トリガ、対数周波数軸、ローカライズされたコントロールを実装
* PipeWire/JACK 常駐モードを AudioEngine / ConfigManager に追加し、関連する翻訳と使用ノートを追加
* Boxcar Averager に内部インパルス／PRBS/MLS／パルスゲートを追加し、絶対サンプル追跡とリセット、モード別ゲート表示切替、関連テストを追加
* GoniometerWidget にグロー／スムーズライン、マッピングオプション、軸反転を追加
* Raw Time Series ウィジェットを追加し、多言語化と CH1/CH2 プロット領域の均一化を実装
* Lock-in Amplifier に動的リザーブ後段 IIR LPF と Very Slow バッファ設定を追加し、動的リザーブテストと run_sweep のバッファ指定を追加
* Impedance Analyzer に動的バッファリングとスレッドセーフ入力処理、動的有効桁／位相表示を追加
* バッファ関連や LPF 設定、常駐モードなどの翻訳キーを追加

### Changed

* Lock-in Amplifier の harmonic_order プロパティと復調ロジックをリファクタし、バッファ指定時の出力整形を改善
* Boxcar Averager ウィジェットをグリッドレイアウト化し、コンボボックスの itemData 利用と初期選択、ゲート操作の視認性を改善
* Distortion Analyzer / Lock-in 周辺の不要インポートを削除
* .gitignore を更新し、ログファイル除外を追加

### Documentation

* README に Transient Analyzer と Detachable Wrapper を追記し、ウィジェット概要セクションを拡充
* Linux で PortAudio と JACK/PipeWire を併用する際のノートを追加

## [v0.2.3] - 2025-12-15

### Added

* モジュールウィジェットを新規 `DetachableWidgetWrapper` で包み、別ウィンドウへ切り離せる機能と対応する多言語翻訳を追加
* LUFS Meter に統計／グラフのタブ構成、チャネル別 K-weighting、統合ラウドネスのゲーティングとスレッドセーフな更新を追加
* Generator / Sweep 制御をタブ化した設定 UI を追加
* Lock-in Amplifier に標準偏差ベースの自動表示桁調整とソフトウェアループバックを使った性能テストを追加
* Impedance Analyzer にアドミタンスの SI 接頭辞フォーマットと単体テストを追加
* Sound Level Meter に LN 統計計算／リセット、ヒストグラム表示、長時間測定プリセット、翻訳キーを追加
* SPL キャリブレーションダイアログに測定帯域幅設定を追加
* Recorder & Player に再生ゲイン調整を追加
* pytest 設定を追加し、ハードウェア依存テストをスキップする統合を追加

### Changed

* Sound Level Meter の設定 UI をタブ分割し、レイアウトとアクセシビリティを改善
* Lock-in Amplifier と Impedance Analyzer のコヒーレンス計算／復調処理をリファクタし、位相安定性とスカロッピング補正を改善
* コードベース全体の未使用インポートと変数を整理
* SPL キャリブレーションテストの不要パラメータを削除し、pytest 設定を整理

### Fixed

* リリースワークフローの権限設定を修正

### Documentation

* README タイトルを更新し、概要文をわかりやすく修正

## [v0.2.2] - 2025-12-13

### Added

* Sound Level Meter モジュールを追加し、A/C/Z ウェイティング、IEC 時定数、チャネル選択、ターゲット時間／サンプリング周期／帯域幅モード設定、ラベル整理、翻訳を含む SPL 測定系を拡充
* LUFS Meter に統合ラウドネス計算とセッション統計、C ウェイティング対応を追加し、SPL キャリブレーション用途を強化
* CalibrationManager／SettingsWidget に電圧ベースの単位へ対応した SPL キャリブレーションと出力ゲインキャリブレーションフラグを実装
* FrequencyCounter に周波数／周期の表示モード切替とエラーハンドリング改善、ConfigManager にレガシーデバイス管理を追加
* オシロスコープに波形計測・単発トリガー・チャネル別縦スケール・タブ分割 UI を追加し、関連翻訳を更新
* Spectrum Analyzer にチャネル選択と PSD/スペクトラム処理の統合を追加
* 多言語翻訳（pt/ru/zh など）とキャリブレーションダイアログのガイダンスを更新

### Changed

* レベル単位設定を dBFS / dBV / dB SPL から選べる形式に変更し、SPL オフセット表記を dB SPL/FS に統一
* Settings UI を General / Audio / Calibration のタブ構成に再編成
* Network Analyzer のデフォルト掃引を Fast Chirp に変更
* README を最新モジュールに合わせて更新し、.gitignore でログファイルを除外

### Fixed

* キャリブレーション設定の適用漏れを修正

### Documentation

* AGENT.md の開発環境手順を更新

## [v0.2.1] - 2025-12-11

### Added

* Inverse Filter の GUI／処理パイプラインを追加し、デフォルトのキャリブレーションマップと単体テストを同梱
* インバースフィルター出力に入力RMSへ合わせる正規化オプションを追加（デフォルト有効）
* MainWindow／RecorderPlayerWidget／SignalGeneratorWidget で出力先選択・同期・ミュートを追加し、ルーティングを統一
* DistortionAnalyzer に IMD 平均化を追加し、分析メソッドを拡張
* SpectrumAnalyzer の FFT サイズ選択肢を拡大し高分解能モードに対応

### Changed

* NetworkAnalyzer の平滑化を Savitzky–Golay フィルタに置き換え、プロット処理を改善
* Group delay 表示単位を ms から s に変更し計算を調整
* Inverse Filter の位相アンラップとログ周波数ハンドリング、進捗表示を改善
* SpectrumAnalyzer のモード／平滑化の初期状態処理を改善
* .gitignore を更新（map_mic.json やログファイルを除外）

### Fixed

* 各言語ファイルの翻訳修正を反映

## [v0.2.0] - 2025-12-09

### Added

* Lock-in THD+N アナライザーとウィジェットを追加し、整数周期ウィンドウ・平均化・残差履歴・残差プロットを強化
* Lock-in/Advanced Distortion 計測に出力チャネル選択と振幅単位変換を追加、調和成分の指数移動平均を実装
* Impedance Analyzer にキャリブレーションデータと補間オプション、平均化回数設定、共振検出および Nyquist プロットモードを追加
* Network Analyzer ウィジェットに設定/表示/キャリブレーションのタブ構成を導入し、チェックボックス表記を簡素化
* 設定ウィジェットに大きめのバッファ選択肢を追加
* 多数の新規翻訳キーを追加（Lock-in THD+N、Time Domain / Waveform / Residual、キャリブレーション関連 など）

### Changed

* Lock-in THD アナライザー／ウィジェットのロジックを整理し、残差の履歴保持とプロットを拡張
* Impedance Analyzer の UI をタブ分割し、Q Factor 表示を D (Tan δ) に置き換え、Nyquist 周波数に基づき入力範囲を動的制限
* Network Analyzer のレイアウトを再構成し、固定幅タブを廃止して構造を簡素化
* GUI 全体で tr 化と翻訳を拡充し、各種ラベルやタイトルを多言語化

### Removed

* Distortion Analyzer からマルチトーン生成機能と関連 UI を削除

### Documentation

* README や walkthrough を更新し、Windows 向けリリースアーカイブ名の整理と不要スクリプトの削除

## [v0.1.7] - 2025-12-04

### Added

* Recorder & Player 機能を追加し、ソフトウェアループバックに対応
* 非同期オーディオ読み込み（リサンプリング＋進捗表示）を追加
* Noise Profiler に平均化モードを追加
* Phosphor（残光）表示モードおよびカラーパレット設定を追加
* Signal Generator に鋸歯状波の上昇／下降タイプ選択機能を追加
* Frequency Counter ウィジェットを追加
* 多数のUIコンポーネント（Spectrum Analyzer / Spectrogram / Network Analyzer / Lock-in / Distortion Analyzer / Impedance Analyzer など）に新しい表示・制御機能を追加
* 各ウィジェットの新機能に対応する翻訳キーを追加

### Changed

* 多数のUI文字列を `tr()` 化し、多言語化を大規模に強化
* プロットの周波数制限機能を追加し、表示・計算処理を改善
* Distortion Analyzer・Lock-in・Network Analyzer 等でコンボボックスの値処理を index / itemData ベースに変更
* Spectrogram・Noise Profiler・Network Analyzer などの翻訳ファイルを更新

### Fixed

* グループディレイの x 軸スケーリングを修正（ログ周波数に対応）
* 不必要な ViewBox 追加による描画問題を修正
* 1/f ノイズ解析のハム除外帯域を 5 Hz に拡大し判定精度を改善
* その他、細かな UI 表記や計算ロジックの修正

### Removed

* Noise Profiler の 1/f コーナー周波数手動指定機能を削除
* PyInstaller ワークフローでの不要な scipy サブモジュール除外設定を削除
* 不要な再現テストスクリプト（pyqtgraph legend など）を削除

### Documentation

* GEMINI.md を更新
* CHANGELOG エントリを整理

## [v0.1.6] - 2025-12-03

### 新機能

* ロックインアンプのキャリブレーションシステムを追加 (周波数応答マッピングと絶対ゲイン補正)

* ヒルベルト変換に基づく参照周波数とコヒーレンスの推定を実装
* インピーダンス解析のための動的プロットモードと凡例の更新
* Windows Nuitkaビルド用のGitHub Actionsワークフローを追加

### 改善・変更

* PyInstallerビルドサイズを削減 (未使用のscipyサブモジュールを除外)

* 不要なデータファイルの削除と.gitignoreの更新

## [v0.1.5] - 2025-11-29

Windows10対応のためのテストリリース

## [v0.1.4] - 2025-11-26

...
