# Changelog

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
