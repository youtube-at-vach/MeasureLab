# MeasureLab GUI Design Guideline 対応状況マトリクス

## 概要

更新日: 2026-08-27
基準文書: [`guide/MEASUREMENT_INSTRUMENT_DESIGN_GUIDELINES.md`](../guide/MEASUREMENT_INSTRUMENT_DESIGN_GUIDELINES.md)  
対象コード: `src/gui/`、`src/measurement_modules/`、関連テスト

この文書は、MeasureLab GUI Design Guideline v2.1 に対する現在の実装状況を、ウィジェットごとに記録する監査台帳です。実装を直すための設計書ではなく、対応している点、対応していない点、コード上の根拠、未検証の点を明文化することを目的とします。

> [!IMPORTANT]
> 「未対応／要確認」は、その機能を各モジュールへ追加する実装指示ではありません。特にクリッピング、I/O 異常、入力品質などは、必要性、既存の共通状態、リアルタイム負荷をガイドライン 1.5 節に従って評価してください。同じ監視を各 callback へ追加することは禁止され、共通監視も実利用先と性能予算が確認できるまでは導入しません。

このタスクの完了条件は、次のすべてです。

- `MODULE_REGISTRY` に登録された42モジュールを一件ずつ記録する。
- 各モジュールについて、ガイドラインに対応している点を記録する。
- 各モジュールについて、未対応、部分対応、または要手動確認の点を記録する。
- `Welcome`、`Settings`、共通ラッパー、計測コンソールなど、登録モジュール外の主要GUIも別枠で記録する。
- 「対象外」と「未実装」を混同しない。能力宣言上の対象外理由も記録する。

## 結論

42モジュールの共通ラッパー、能力宣言、分離・撮影・ログの共通経路、サイズ上限、翻訳キー整合は、現在のコードと検証で確認できます。一方、ガイドライン全体への適合は完了していません。特に、次の項目は全モジュールで一貫して完了したとは言えません。

- 主要コントロールと読み出し値の accessible name / description、フォーカス順、キーボード操作。
- テーマの意味トークンを使った色管理。ウィジェット内に直接色指定が残っています。
- 無効値、暫定値、保持値、クリッピング、I/O エラー、測定条件不整合を結果へ結び付ける表示契約。
- 取得条件、校正、単位、品質フラグを一体にした不変スナップショット。
- 各ウィジェットの Start 成功／失敗、Stop、Cancel、再開、タブ移動、分離、終了を固定する受け入れテスト。

したがって、各行の「対応」は機能または設計要素の実装根拠を示し、「未対応／要確認」はガイドラインの完了条件を満たしていない、またはコードだけでは満たしたと判定できない点を示します。

## 判定記号

| 記号 | 意味 |
| --- | --- |
| ✓ | コード上の実装と、該当する自動テストまたは共通契約を確認できる |
| △ | 一部実装、条件付き実装、または手動確認・専用テストが不足している |
| ✗ | 必須要件を満たす実装がない、またはガイドラインに反する実装を確認できる |
| — | そのモジュールの用途には適用しない。対象外理由を別途記録する |

`△` は「問題なし」という意味ではありません。今回の監査では、実装の存在と、測定器として安全・再現可能であることを分けて判定しています。

## 監査項目

| ID | 対応するガイドライン | 判定対象 |
| --- | --- | --- |
| `COMMON-01` | 5.5、11.2、12.3 | `DetachableWidgetWrapper`、`WidgetCapabilities`、インターフェース契約の一致 |
| `COMMON-02` | 2.1、4.2、5.1、6.4 | MainWindow の実状態、出力先、I/O エラー、共通ログへの導線 |
| `SIZE-01` | 5.4 | 全言語・Qt既定フォントでのサイズ上限と主要操作の収まり |
| `I18N-01` | 8.7、14 | `tr()`、翻訳キー、内部IDと表示文字列の分離 |
| `A11Y-01` | 8.5、10.3、10.4、14 | accessible name / description、ラベル関連付け、キーボード、フォーカス |
| `THEME-01` | 10.1、10.2 | 意味トークン、テーマ切替、色以外の状態表現、固定フォント |
| `STATE-01` | 4.1、4.2、6.1、6.4、7.1 | 無効値、警告、クリップ、I/O異常、実状態、保持・古い値 |
| `STATE-02` | 6.2、6.3、12.2 | Start / Stop / Hold / Cancel、進捗、ワーカー・タイマー寿命 |
| `UNIT-01` | 4.6、7.2、7.3 | 単位、dB基準、校正の有効性、表示桁、判定値との一致 |
| `DATA-01` | 4.6、7.4、7.5、12.4 | 不変スナップショット、取得条件、校正、品質フラグ、比較来歴 |
| `DATA-02` | 7.6 | CSV、JSON、WAV、モデル保存時の単位・軸・条件・品質情報 |
| `PLOT-01` | 9.1–9.7 | 軸、単位、スケール、トレース識別、カーソル、間引き、状態表示 |
| `CONTROL-01` | 3、8.1–8.6 | 数値入力、1-2-5調整、Auto Scale / Auto Set、直接操作、ヘルプ |
| `TEST-01` | 4.8、13.1–13.4 | ガイドライン固有の自動テスト、手動確認、完了記録 |

## 全体サマリー

| 観点 | 現状 | 判定 | 根拠 |
| --- | --- | :---: | --- |
| 登録モジュールの網羅 | 42 / 42を個別記録 | ✓ | `src/core/module_constants.py`、`src/gui/module_registry.py` |
| 共通ラッパーと能力宣言 | 42 / 42で宣言・契約検証 | ✓ | `src/gui/widgets/detachable_wrapper.py`、`tests/logic_verification/gui/test_widget_capabilities.py` |
| 共通状態・I/Oエラー・出力先 | MainWindowで実装。I/Oエラーはラッチ表示 | ✓ | `src/gui/main_window.py`、`src/core/audio_engine.py` |
| 全言語のサイズ上限 | 今回の実行で成功 | ✓ | `scripts/check_ui_size_limits.py` |
| 翻訳キー整合 | 2270キー、全言語整合を確認 | ✓ | `scripts/check_trn_keys.py` |
| 表示文字列の完全な`tr()`管理 | 単位・数式以外にリテラルが残る | △ | `I18N-01`、HRTF／Response Viewer等の個別所見 |
| 主要コントロールのアクセシビリティ属性 | 包括的な設定なし。部分設定は4モジュール | ✗ | `A11Y-01` |
| 意味トークンによる色・テーマ管理 | 多数のウィジェットで直接色指定 | ✗ | 36モジュールに16進色、その他にも名前色・RGB指定 |
| 無効値・品質フラグの一貫した表示 | モジュールごとの差が大きい | △ | `STATE-01` |
| 取得条件付き不変スナップショット | 比較対応5モジュール等に部分実装。全体契約なし | △ | `DATA-01` |
| ガイドライン全項目の専用受け入れテスト | 未整備 | ✗ | `TEST-01` |

## 共通して対応している点

### 共通ウィンドウ契約

全42モジュールは `src/gui/main_window.py` から `DetachableWidgetWrapper` で包まれます。State A（通常表示）、State B（独立ウィンドウ）、対応モジュールのState C（表示／操作分割）、スクリーンショット、共通ログビューアへの導線を共通経路で提供しています。`WidgetCapabilities` と各インターフェースの不一致は、実行時と契約テストで検出されます。

これはガイドラインの「共通機能を各ウィジェットへ重複実装しない」「能力を明示的に宣言する」に対応しています。対象外の能力も `NO_INDEPENDENT_DISPLAY`、`NON_TRACE_COMPARISON`、`COMPARISON_DEFERRED` などの理由を持ち、暗黙の `hasattr()` 判定には依存していません。

### 実状態とI/Oエラーの共通表示

MainWindow は AudioEngine の入出力状態、サンプルレート、CPU、クライアント数、出力先を共通領域へ表示します。入力／出力の overflow、underflow、callback例外は集約され、I/Oエラーはユーザーの確認までラッチされます。これはモジュールが個別に要求状態を推測しないための基盤です。

### サイズと言語

`scripts/check_ui_size_limits.py` を全言語・既定フォントで実行し、MainWindow 1400×740 px、モジュールコンテンツ 1180×690 px の上限内で `Verification Passed!` を確認しました。`scripts/check_trn_keys.py` も成功し、`en.json` の2270キーと他言語の整合を確認しました。

ただし、サイズ検証に成功したことは、フォント拡大、高DPI、複数モニター、実機、色覚シミュレーションまで確認したことを意味しません。

## 横断的な未対応・要確認点

### `A11Y-01`: アクセシビリティ属性とキーボード

`src/gui/widgets/detachable_wrapper.py` の共通ヘッダーボタンには accessible name とツールチップがあります。一方、モジュール側で `setAccessibleName()` または `setAccessibleDescription()` を確認できるのは Event Detector、Goniometer、Spectrogram、Response Viewerの一部だけです。主要なStart／Stop、数値入力、主要読み出し、カスタム描画値を全体としてカバーしていません。

アイコンだけの `▶`、`■`、`X`、`‹`、`›` などは、accessible name、説明、フォーカス時の理由が不足しています。フォーカス順、キーボードだけで完了できる基本操作、ライブ値を連続通知しない読み上げ方針も、全モジュール共通の自動検証がありません。

### `THEME-01`: 色とテーマ

ウィジェットごとに `setStyleSheet()`、`pg.mkPen()`、`pg.mkBrush()`、`setBackground()`、`QColor()` へ直接色を渡す実装が残っています。36モジュールには16進色リテラルがあり、残りにも名前色、RGBタプル、テーマ別の個別色指定があります。テーママネージャー自体は存在しますが、意味トークンを全ウィジェットへ適用する契約はありません。

そのため、警告を赤／黄／緑だけで表現しないこと、Light／Dark／High Contrastで意味を保つこと、トレースを線種・マーカー・ラベルでも区別すること、コントラスト比を検証することは未完了です。

### `STATE-01` と `UNIT-01`: 無効値、警告、単位、校正

一部のウィジェットはクリッピング、データ欠落、校正なし、非有限値、開始失敗を扱います。しかし、その警告が「どの結果をいつから無効にしたか」「停止後の値は最終値か保持値か」「暫定値か」を同じ契約で表現していません。`0`、`-`、`--`、`N/A`、`—` の意味もウィジェットにより異なります。

CalibrationManager と ComparisonTrace は校正情報を持ちますが、全表示値・全エクスポート・全モジュールがこの情報へ結び付いているわけではありません。特に `dB`、`dBFS`、`dBV`、`V`、`SPL` の選択可否、RMS／Peakの意味、校正失効時の相対単位への安全な復帰をモジュール単位で再確認する必要があります。

### `DATA-01` と `DATA-02`: 来歴とエクスポート

比較対応は Spectrum Analyzer、Oscilloscope、Distortion Analyzer、Network Analyzer、Lock-in Amplifierの5モジュールです。これらは軸、表示単位、校正、日時などの一部を `ComparisonTrace` へ格納しますが、サンプルレート、デバイス、ルーティング、トリガ、窓、品質フラグなどの完全な取得条件はモジュールごとに不足があります。

Event Detector、Goniometer、Lock-in Spectrum Finderなどにはスナップショット相当のメソッドがありますが、全モジュールで「取得データと条件を不変に固定して保存・比較できる」という共通契約にはなっていません。個別CSV、JSON、WAV、モデル出力も、正式な測定記録に必要な条件サイドカーを一律には提供していません。

### `CONTROL-01` と `TEST-01`: 操作と検証

Qtの標準入力、スピンボックス、コンボボックス、ワーカー、タイマーは広く使われています。しかし、直接入力とホイール／キー操作の同値性、1-2-5系列、Auto ScaleとAuto Setの意味、フォーカス順、Escapeによるキャンセル、無効理由の読み上げを全モジュールで固定するテストはありません。

今回確認した86件の関連テストは共通能力、分離、コンソール、比較器、主要ウィジェットのロジックを対象にしていますが、ガイドラインの12項目すべてを42モジュールで満たすことを示すものではありません。実機オーディオ、OS別フォント、高DPI、色覚、長時間動作、複数モニターは手動確認が必要です。

## モジュール別マトリクス

以下の各項目では、共通基盤を繰り返し省略せず、モジュール固有の対応点と未対応点を記録します。全行に共通して `COMMON-01`、`COMMON-02`、`SIZE-01` の根拠があります。アクセシビリティ、テーマ、ガイドライン専用テストについては、個別に例外を記載しない限り `A11Y-01`、`THEME-01`、`TEST-01` が残っています。

### 1. Signal Generator

- **対応:** 信号種別、周波数、レベル、左右チャンネル、出力モード、ルーティングをまとめ、チェック可能な `toggle_btn` で出力を開始／停止します。Compactを宣言し、出力バッファ生成、非有限値の防止、出力遷移処理、校正条件バッジを実装しています。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。危険出力について、実際に音が出ている状態、最終段の過負荷、無効な出力値を主要表示へ一貫してラッチする契約が未確認です（`STATE-01`）。生成条件を不変スナップショットとして保存する経路もありません（`DATA-01`）。
- **対象外:** SplitとComparisonは独立した表示部を持たないため対象外です。根拠は `MODULE_REGISTRY` の `NO_INDEPENDENT_DISPLAY` です。
- **根拠:** `src/gui/widgets/signal_generator.py`、`MODULE_SIGNAL_GENERATOR`、`tests/logic_verification/gui/widgets/test_signal_generator.py`、`tests/regression/test_signal_generator_switch.py`

### 2. Spectrum Analyzer

- **対応:** FFT／PSD、チャンネル、重み付け、平均化、ピーク、カーソル、総合値を表示し、Run／Stop、Compact、Split、Comparisonを能力宣言しています。比較送信は周波数軸、表示単位、校正、チャンネル、FFTサイズを含むスナップショットを生成します。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。比較メタデータにデバイス、ルーティング、サンプルレート、窓、分解能、クリッピング等が不足します（`DATA-01`）。プロットのカーソルをキーボードで微調整できること、ライブ／保持／無効値を完全に区別することは専用テストがありません（`PLOT-01`、`CONTROL-01`、`TEST-01`）。
- **対象外:** なし。宣言されたCompact、Split、Comparisonは実装済みですが、実装済み能力がガイドライン全体への適合を意味するものではありません。
- **根拠:** `src/gui/widgets/spectrum_analyzer.py`、`MODULE_SPECTRUM_ANALYZER`、`tests/logic_verification/gui/test_spectrum_analyzer_split.py`、`tests/logic_verification/gui/test_widget_capabilities.py`

### 3. Sound Level Meter

- **対応:** 周波数重み付け、時間重み付け、チャンネル、積分時間、統計、リセット、SPL校正警告を備えたメーターです。主要値を大きく表示し、Compact、Split、コンソール主操作を宣言しています。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。単位ラベルに一般的な `dB` が残り、dBFS／dB SPL、RMS／Peak、校正状態の表示を主要値と一体にする必要があります（`UNIT-01`）。保持値、測定値の古さ、クリッピング、品質フラグを結果へ固定するスナップショット／エクスポートがありません（`STATE-01`、`DATA-01`、`DATA-02`）。
- **対象外／保留:** Comparisonは `COMPARISON_DEFERRED` で、比較送信は未実装です。メーター値を比較する必要性を決めた上で能力を宣言します。
- **根拠:** `src/gui/widgets/sound_level_meter.py`、`MODULE_SOUND_LEVEL_METER`、`tests/logic_verification/gui/test_sound_level_meter.py`

### 4. LUFS Meter

- **対応:** Momentary、Short-Term、Integrated、LRA、ピーク、ターゲット差、積分時間をカード形式で表示し、リセットと測定トグル、Compact、Splitを提供します。BS.1770系の状態を常時表示へまとめています。
- **未対応／要確認:** `A11Y-01`。多数の固定サイズと直接色指定があり、`THEME-01` と `SIZE-01` の高DPI／フォント拡大確認が必要です。Hold、値の古さ、クリッピング、無効値、測定条件の保存が明示されず（`STATE-01`、`DATA-01`）、ターゲットと単位の来歴をエクスポートする経路もありません（`DATA-02`）。
- **対象外／保留:** Comparisonは `COMPARISON_DEFERRED` です。LUFSの時間特性とターゲット条件を含めた比較仕様が未定義です。
- **根拠:** `src/gui/widgets/lufs_meter.py`、`MODULE_LUFS_METER`、`tests/logic_verification/gui/test_lufs_meter.py`、`tests/logic_verification/gui/test_lufs_meter_compact.py`

### 5. Loopback Finder

- **対応:** 出力／入力ペアの走査をワーカーで実行し、候補、信頼度、結果状態を表へ表示します。走査条件と終端状態を持ち、キャンセル可能なワーカー構造があります。
- **未対応／要確認:** 独立した結果表示の状態保持、スクリーンショットへの条件サマリー、結果のエクスポートがありません（`DATA-01`、`DATA-02`）。走査中、キャンセル中、部分結果、無効ペアの表示を専用受け入れテストで固定していません（`STATE-01`、`STATE-02`、`TEST-01`）。`A11Y-01`、`THEME-01` も残ります。
- **対象外:** SplitとCompactは `SPLIT_DEFERRED`／`COMPACT_DEFERRED`、Comparisonは表形式の結果であり1D／XYトレースではないため `NON_TRACE_COMPARISON`、コンソール主操作は単一の開始／停止トグルへ集約しないため対象外です。
- **根拠:** `src/gui/widgets/loopback_finder.py`、`MODULE_LOOPBACK_FINDER`、`tests/logic_verification/gui/test_loopback_finder.py`、`tests/logic_verification/gui/test_loopback_finder_ui_stop.py`

### 6. Distortion Analyzer

- **対応:** 周波数／振幅スイープ、THD、THD+N、SINAD、IMD、平均化、校正、比較送信を実装し、ワーカーとStart／Stopを持ちます。ComparisonTraceにはスイープ種別、X／Y単位、フィルター、校正、取得時刻を格納します。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。比較Traceにサンプルレート、出力レベル、入力／出力ルーティング、窓、クリッピング、部分結果の有効性が不足します（`DATA-01`）。StopとCancel、失敗したスイープの部分結果を保存するか破棄するかの境界を明示していません（`STATE-02`）。
- **対象外／保留:** CompactとSplitは `COMPACT_DEFERRED`／`SPLIT_DEFERRED` です。比較送信は実装済みですが、比較可能性とメタデータの完全性は別途残課題です。
- **根拠:** `src/gui/widgets/distortion_analyzer.py`、`MODULE_DISTORTION_ANALYZER`、`tests/logic_verification/gui/widgets/test_distortion_analyzer_widget.py`

### 7. Advanced Distortion Meter

- **対応:** MIM、PIM、マルチトーン、J-test系の測定を切り替え、主要歪み指標とプロットを表示します。分析処理をワーカーへ移し、Start／Stop／Resetを提供します。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。クリッピング、非有限値、測定失敗、収束前の値を正常な歪み値と区別する結果状態が不足します（`STATE-01`）。取得条件、校正、品質フラグを含む保存／比較スナップショットもありません（`DATA-01`、`DATA-02`）。
- **対象外／保留:** Compact、Split、Comparisonは各々 `COMPACT_DEFERRED`、`SPLIT_DEFERRED`、`COMPARISON_DEFERRED` です。実用度と比較形式をレビューしてから宣言を見直します。
- **根拠:** `src/gui/widgets/advanced_distortion_meter.py`、`MODULE_ADVANCED_DISTORTION_METER`、`tests/logic_verification/gui/widgets/test_advanced_distortion_meter.py`

### 8. Network Analyzer

- **対応:** 周波数特性のMagnitude／Phase、Group Delay、Coherence、ハーモニクス、RIAA、レイテンシ、リファレンス保存／読込を実装し、進捗付きワーカーとComparisonTraceを持ちます。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。ComparisonTraceのメタデータが入力モードと平滑化中心で、デバイス、サンプルレート、出力振幅、ルーティング、品質フラグ、窓、位相処理等を十分に固定しません（`DATA-01`）。絶対モードで `dBV` と線形電圧データの対応が読み手に曖昧になる経路があり、単位表示とデータ表現を再確認する必要があります（`UNIT-01`）。長いスイープのCancelと部分結果の意味も未固定です（`STATE-02`）。
- **対象外／保留:** CompactとSplitは `COMPACT_DEFERRED`／`SPLIT_DEFERRED`。Comparisonは実装済みです。
- **根拠:** `src/gui/widgets/network_analyzer.py`、`MODULE_NETWORK_ANALYZER`、`tests/logic_verification/gui/test_network_analyzer.py`

### 9. Oscilloscope

- **対応:** 時系列波形、トリガ、自動測定、左右チャンネル、Persistence、Auto Scale、クリッピングラッチ、校正表示を実装し、Compact、Split、Comparisonを宣言しています。比較Traceに時間軸、チャンネル、timebase、校正を格納し、関連テストが多くあります。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。比較Traceにサンプルレート、トリガ位置／条件、表示間引き、クリップや欠損の品質フラグが不足します（`DATA-01`）。Holdと取得停止、表示用データと解析用データ、カーソルのキーボード微調整の全経路をガイドライン用テストで網羅していません（`STATE-01`、`PLOT-01`、`CONTROL-01`）。
- **対象外:** なし。宣言されたCompact、Split、Comparisonは実装済みです。
- **根拠:** `src/gui/widgets/oscilloscope.py`、`MODULE_OSCILLOSCOPE`、`tests/logic_verification/gui/test_oscilloscope_features.py`、`tests/logic_verification/gui/test_oscilloscope_calibration_display.py`、`tests/logic_verification/gui/test_oscilloscope_compact_mode.py`

### 10. Raw Time Series

- **対応:** 長時間の左右波形とDC値をリングバッファから表示し、開始／停止、Compact、Splitを提供します。入力データと表示更新を分ける構造があります。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。`CH1: -`／`CH2: -` の初期表示とデータ欠落、保持値、クリッピングの意味が明示されません（`STATE-01`）。長時間記録のサンプルレート、入力、校正、欠損、取得時刻を固定するスナップショット／エクスポートがありません（`DATA-01`、`DATA-02`）。
- **対象外／保留:** Comparisonは `COMPARISON_DEFERRED` です。長時間データをどの範囲で比較するか未定義です。
- **根拠:** `src/gui/widgets/raw_time_series.py`、`MODULE_RAW_TIME_SERIES`、`tests/logic_verification/gui/test_raw_time_series_formatting.py`

### 11. Event Detector

- **対応:** イベント数、レート、持続時間、間隔、ヒストグラムを表示し、クリッピング、データギャップ、設定変更、記録上限を個別状態として示します。実行メタデータ、校正状態、イベントJSON／CSVエクスポート、Compact、Splitがあります。イベントインジケータには部分的な accessible name が設定されています。
- **未対応／要確認:** 主要Start／Stop、設定入力、全読み出しへのアクセシビリティ属性は不足します（`A11Y-01`）。警告色やヒストグラム色が直接指定され、色以外の識別とテーマトークン化が未完了です（`THEME-01`）。比較送信はなく、長時間通知の集約、古い値、部分実行の保存可否を全経路で固定していません（`STATE-01`、`DATA-01`、`TEST-01`）。
- **対象外／保留:** Comparisonは `COMPARISON_DEFERRED`。イベント列を1Dトレースとして比較する仕様が未決定です。
- **根拠:** `src/gui/widgets/event_detector.py`、`MODULE_EVENT_DETECTOR`、`tests/logic_verification/gui/test_event_detector_widget.py`

### 12. Lock-in Amplifier

- **対応:** 同期検波のMagnitude、Phase、X／Y、FRAスイープ、積分、平均化、周波数校正を表示し、FRAの比較Traceとキャンセル可能なワーカーを実装しています。Reference Lock状態と校正操作があります。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。比較Traceは積分と平均化、校正の一部を持つ一方、入力／出力、サンプルレート、参照信号、品質フラグ、ロック状態の不変記録が不足します（`DATA-01`）。Magnitude／Phase、dBFS／dBV、ロック不成立時の無効値を正常表示から分離する専用テストがありません（`UNIT-01`、`STATE-01`、`TEST-01`）。
- **対象外／保留:** CompactとSplitは `COMPACT_DEFERRED`／`SPLIT_DEFERRED`。Comparisonは実装済みです。
- **根拠:** `src/gui/widgets/lock_in_amplifier.py`、`MODULE_LOCK_IN_AMPLIFIER`、`tests/logic_verification/measurement_modules/test_lockin_vs_realtime_sss.py`

### 13. Lock-in Harmonic Analyzer

- **対応:** 基本波と高調波を同時にIQ検波し、THD、校正、補償バッファ、補償データのエクスポートを提供します。Start／Stop、校正開始／停止、バッファクリアを実装しています。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。校正不成立、ロック不安定、非有限値、高調波次数の範囲外を結果へラッチする状態契約が不十分です（`STATE-01`）。補償データのエクスポートはありますが、取得条件、校正プロファイル、品質フラグを正式なスナップショットとして扱いません（`DATA-01`、`DATA-02`）。長時間処理のCancel境界も未固定です（`STATE-02`）。
- **対象外／保留:** Compact、Split、Comparisonは各々 `COMPACT_DEFERRED`、`SPLIT_DEFERRED`、`COMPARISON_DEFERRED` です。
- **根拠:** `src/gui/widgets/lockin_harmonic_analyzer.py`、`MODULE_LOCK_IN_HARMONIC_ANALYZER`、`tests/logic_verification/gui/widgets/test_lockin_harmonic_analyzer.py`

### 14. Arbitrary Harmonic Generator

- **対応:** 基本周波数、高調波次数ごとの振幅／位相、補償データ、周波数不一致確認を扱い、チェック可能な生成トグルと入力検証を持ちます。補償データの読込失敗や不一致をダイアログで通知します。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。危険出力、実出力状態、非有限値、出力制限、校正条件を主要状態として一貫して表示することが未確認です（`STATE-01`、`UNIT-01`）。生成パラメータの再現可能なPreset／Snapshot、出力条件付きエクスポートがありません（`DATA-01`、`DATA-02`）。
- **対象外／保留:** Compact、Split、Comparisonは未実装の `COMPACT_DEFERRED`、`SPLIT_DEFERRED`、`COMPARISON_DEFERRED` です。
- **根拠:** `src/gui/widgets/arbitrary_harmonic_generator.py`、`MODULE_ARBITRARY_HARMONIC_GENERATOR`、`tests/logic_verification/gui/widgets/test_arbitrary_harmonic_generator.py`、`tests/security/test_arbitrary_harmonic_generator_security.py`

### 15. Lock-in Spectrum Finder

- **対応:** 狭帯域の対象周波数を走査し、解像度、ターゲット、ズーム、音声確認、ユーザーターゲットのJSON保存／読込、Compact、Splitを提供します。`get_data_snapshot()` により計算結果を固定的に取り出せる経路があります。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。スナップショットの取得条件、校正、対象ターゲット、品質、計算未完了を正式な `ComparisonTrace` または取得記録へ結び付けません（`DATA-01`、`DATA-02`）。スキャン中のCancel、部分結果、対象周波数と実周波数のずれを無効／暫定として示す契約が不足します（`STATE-01`、`STATE-02`）。
- **対象外／保留:** Comparisonは `COMPARISON_DEFERRED` です。狭帯域のポイント列を比較基盤へ渡す仕様が未決定です。
- **根拠:** `src/gui/widgets/lockin_spectrum_finder.py`、`MODULE_LOCKIN_SPECTRUM_FINDER`、`tests/logic_verification/gui/test_lockin_spectrum_finder_split.py`

### 16. Frequency Counter

- **対応:** 周波数、振幅、標準偏差、Allan、ジッター、更新間隔を表示し、Reset、校正ダイアログ、Compact、コンソール主操作を実装しています。周波数校正の確認ダイアログと専用テストがあります。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。信号なし、低レベル、非周期、外れ値、古い値を `0` や通常値と混同しない状態表示が不十分です（`STATE-01`、`UNIT-01`）。校正条件と測定区間、サンプルレート、品質フラグを結果として保存／比較する経路がありません（`DATA-01`）。長時間Allan計算のCancelと世代管理を専用テストで固定していません（`STATE-02`、`TEST-01`）。
- **対象外／保留:** SplitとComparisonは `SPLIT_DEFERRED`／`COMPARISON_DEFERRED` です。
- **根拠:** `src/gui/widgets/frequency_counter.py`、`MODULE_FREQUENCY_COUNTER`、`tests/logic_verification/gui/test_frequency_counter_reset.py`、`tests/logic_verification/gui/test_measurement_console.py`

### 17. Lock-in Frequency Counter

- **対応:** NCOとの周波数偏差、位相、Kalman推定、分布統計を表示し、Run／Stop、パラメータ更新、分布クリアを持ちます。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。NCO基準、校正、推定中／安定／無効、保持値、統計のサンプル数を主要値と結び付けるスナップショットがありません（`STATE-01`、`UNIT-01`、`DATA-01`）。単位と精度表示、長時間通知、キーボード操作をガイドライン専用テストで確認していません（`CONTROL-01`、`TEST-01`）。
- **対象外／保留:** Compact、Split、Comparisonは `COMPACT_DEFERRED`、`SPLIT_DEFERRED`、`COMPARISON_DEFERRED` です。
- **根拠:** `src/gui/widgets/lock_in_frequency_counter.py`、`MODULE_LOCK_IN_FREQUENCY_COUNTER`、`tests/logic_verification/gui/widgets/test_kalman_filter_1d.py`

### 18. Spectrogram

- **対応:** 時間、周波数、強度をヒートマップとして表示し、FFTサイズ、方向、リセット、Run／Stop、Compact、Splitを実装しています。既定カラーマップに `viridis` を使用し、描画処理をワーカーへ分離しています。方向コンボには accessible name があります。
- **未対応／要確認:** `A11Y-01`。カラーマップ、レンジ飽和、欠損、クリッピング、保持／ライブ、時間原点、FFT条件を表示または保存する契約が不十分です（`PLOT-01`、`STATE-01`、`DATA-01`）。Comparisonはヒートマップであり1D／XYトレースではないため対象外ですが、色覚・High Contrast・カラーバーの閾値表現は手動確認が必要です（`THEME-01`、`TEST-01`）。
- **対象外:** Comparisonは `NON_TRACE_COMPARISON` です。
- **根拠:** `src/gui/widgets/spectrogram.py`、`MODULE_SPECTROGRAM`、`tests/logic_verification/gui/test_spectrogram.py`、`tests/logic_verification/gui/test_spectrogram_split.py`

### 19. Boxcar Averager

- **対応:** 周期信号の内部／外部同期平均、ゲート、リセット、結果波形、ファイルエクスポートを提供します。開始／停止と平均化バッファの管理があります。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。平均回数、収束前、部分平均、ゲート不成立、入力欠損を暫定／無効として表示する契約が不足します（`STATE-01`）。エクスポートへサンプルレート、周期、ゲート、平均回数、校正、品質フラグを十分に含めません（`DATA-02`）。長い平均処理のCancel、平均結果の不変Snapshotも未整備です（`STATE-02`、`DATA-01`）。
- **対象外／保留:** Compact、Split、Comparisonは各々 `COMPACT_DEFERRED`、`SPLIT_DEFERRED`、`COMPARISON_DEFERRED` です。
- **根拠:** `src/gui/widgets/boxcar_averager.py`、`MODULE_BOXCAR_AVERAGER`、`tests/logic_verification/gui/widgets/test_measurement_control_layouts.py`

### 20. Goniometer

- **対応:** L/RのXY表示、相関係数、M/S、平滑化、Hold、クリア、Compact、Splitを実装し、相関ウィジェットの accessible name／description と状態ラベルがあります。`GoniometerSnapshot` に品質状態を持つ経路があります。
- **再評価:** v0.8.5 後に module callback 内へ追加された入力 overflow／underflow 判定は、AudioEngine と MainWindow の既存の集約・ラッチ経路と重複します。L/R peak／clip 判定は相関値の無効化に利用されていますが、他モジュールへ展開せず、callback コストとユーザー価値を測ってから維持、削除、共通化を判断します。
- **未対応／要確認:** `A11Y-01` は主要コントロール全体では未完了です。直接指定色によるL/R・相関・Holdの識別があり、線種・マーカー・ラベルとテーマトークンが不足します（`THEME-01`、`PLOT-01`）。Snapshotは存在しますが、標準エクスポート／比較基盤へ取得条件、サンプルレート、校正を一体で渡していません（`DATA-01`、`DATA-02`）。
- **対象外／保留:** Comparisonは `COMPARISON_DEFERRED` です。XYデータを比較送信する仕様は未決定です。
- **根拠:** `src/gui/widgets/goniometer.py`、`MODULE_GONIOMETER`、`tests/logic_verification/gui/test_goniometer_widget.py`

### 21. Impedance Analyzer

- **対応:** 周波数スイープ、ZのMagnitude／Phase、LCR推定、共振、Open／Short／Load校正、動的バッファ、キャンセル可能なワーカーを実装します。結果表示と校正ファイル保存／読込、Stopがあります。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。校正不成立、DUT未接続、バッファ不足、共振推定失敗を正常値と区別する表示と品質フラグが不十分です（`STATE-01`、`UNIT-01`）。校正情報は保存しますが、測定結果のサンプルレート、励振条件、ルーティング、品質、掃引範囲を不変Snapshot／エクスポートへ結び付けません（`DATA-01`、`DATA-02`）。
- **対象外／保留:** Compact、Split、Comparisonは各々 `COMPACT_DEFERRED`、`SPLIT_DEFERRED`、`COMPARISON_DEFERRED` です。
- **根拠:** `src/gui/widgets/impedance_analyzer.py`、`MODULE_IMPEDANCE_ANALYZER`、`tests/logic_verification/gui/widgets/test_impedance_analyzer.py`、`tests/logic_verification/gui/test_impedance_analyzer_details.py`

### 22. Noise Profiler

- **対応:** ノイズ平均、1/fフィット、ホワイトフロア、統計レポートをワーカーで処理し、リセット、Start／Stop、Compact、Splitを提供します。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。ノイズフロア、収束状態、平均回数、入力欠損、校正、単位を不変結果へ保存する経路がなく（`STATE-01`、`UNIT-01`、`DATA-01`）、エクスポート／比較もありません（`DATA-02`）。ワーカー失敗後に前回値を主要結果として残さないこと、Cancelと世代管理を専用テストで固定していません（`STATE-02`、`TEST-01`）。
- **対象外／保留:** Comparisonは `COMPARISON_DEFERRED` です。
- **根拠:** `src/gui/widgets/noise_profiler.py`、`MODULE_NOISE_PROFILER`、`tests/logic_verification/gui/test_noise_profiler_gui_logic.py`、`tests/logic_verification/gui/test_noise_profiler_widget_logic.py`

### 23. Recorder / Player

- **対応:** 録音、再生、ファイル読込／保存を別ワーカーとキューで扱い、再生／録音のStop、未保存録音の置換確認、開始失敗時のロールバック、レース条件のテストがあります。通常表示は再生／録音カードへ整理し、状態、時間、I/O条件、数値入力付き再生ゲインを示します。実行状態と停止操作を残すCompact、主要コントロールのaccessible name／description、ラベルbuddy、フォーカス順を実装しています。出力を一つのトグルへ無理に集約していません。
- **未対応／要確認:** Save workerは保存途中のCancelを提供していません（`STATE-02`）。録音ファイルへサンプルレート、入力デバイス、ルーティング、校正、欠損、実行時刻を正式な測定メタデータとして付加しません（`DATA-01`、`DATA-02`）。OS High Contrastを含む支援技術の実機確認は継続課題です。
- **対象外:** SplitとComparisonは独立した測定結果表示部を持たないため `NO_INDEPENDENT_DISPLAY`。コンソール主操作は録音と再生を一つへ安全に集約できないため対象外です。
- **根拠:** `src/gui/widgets/recorder_player.py`、`MODULE_RECORDER_PLAYER`、`tests/logic_verification/gui/test_recorder_player_logic.py`、`tests/logic_verification/gui/test_recorder_player_compact.py`、`tests/logic_verification/gui/test_recorder_player_race.py`、`tests/logic_verification/gui/test_recorder_save_optimization.py`

### 24. Waveform Loop Player

- **対応:** 音声ファイル読込、波形表示、区間選択、シーク、ループ再生、Pause／Stopを提供し、ファイル読込ワーカーのキャンセルがあります。サンプルレート不一致を確認ダイアログで知らせます。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。波形の選択範囲、再生位置、停止後の保持値、ファイル破損、サンプルレート変換結果を取得条件付きデータとして保存しません（`STATE-01`、`DATA-01`、`DATA-02`）。再生は複数操作でありコンソール主操作なしですが、フォーカス順、キーボードシーク、キャンセル中と完了の表示が未固定です（`CONTROL-01`、`STATE-02`）。
- **対象外／保留:** Compact、Split、Comparisonは `COMPACT_DEFERRED`、`SPLIT_DEFERRED`、`COMPARISON_DEFERRED`。コンソール主操作は単一トグルへ集約しないため対象外です。
- **根拠:** `src/gui/widgets/waveform_loop_player.py`、`MODULE_WAVEFORM_LOOP_PLAYER`、`tests/logic_verification/gui/test_waveform_loop_player.py`

### 25. Transient Analyzer

- **対応:** 録音、トリガ、CWT解析、過渡波形、リンギング指標をワーカーで処理し、Record／Stopと失敗ダイアログを提供します。解析結果に主表示があります。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。録音データ、トリガ条件、時間原点、CWT条件、部分結果、リンギング警告を不変Snapshot／エクスポートへ保存しません（`DATA-01`、`DATA-02`）。録音停止と解析ワーカーのCancel、処理中表示、失敗後の前回値の扱いが未固定です（`STATE-01`、`STATE-02`）。
- **対象外／保留:** Compact、Split、Comparisonは各々 `COMPACT_DEFERRED`、`SPLIT_DEFERRED`、`COMPARISON_DEFERRED`。コンソール主操作は `rec_btn` で宣言されています。
- **根拠:** `src/gui/widgets/transient_analyzer.py`、`MODULE_TRANSIENT_ANALYZER`、`tests/logic_verification/gui/test_transient_analyzer.py`、`tests/logic_verification/gui/test_transient_ringing_analysis.py`

### 26. Sound Quality Analyzer

- **対応:** 音声ファイルを読み込み、心理音響指標を計算し、再生／停止／一時停止とCSV出力を提供します。分析ワーカー、入力ファイル、主要指標のカード表示があります。
- **未対応／要確認:** アイコンだけの再生／停止ボタンに accessible name がなく、`A11Y-01` が明確です。直接色指定、テーマ別意味、結果の単位・推定中・失敗状態が不足します（`THEME-01`、`STATE-01`、`UNIT-01`）。CSVへファイル条件、サンプルレート、モデル／重み付け、品質フラグを十分に含めず（`DATA-02`）、長い処理のCancelもありません（`STATE-02`）。
- **対象外／保留:** Compact、Split、Comparisonは `COMPACT_DEFERRED`、`SPLIT_DEFERRED`、`COMPARISON_DEFERRED`。コンソール主操作は複数の再生／分析操作を一つへ集約しないため対象外です。
- **根拠:** `src/gui/widgets/sound_quality_analyzer.py`、`MODULE_SOUND_QUALITY_ANALYZER`、`tests/logic_verification/gui/test_sound_quality_analyzer.py`

### 27. Timecode Monitor & Generator

- **対応:** LTCのデコード、左右入力、FPS、タイムゾーン、ジェネレータ、Jam、周波数校正、Compact、コンソール主操作を提供します。モニターとジェネレータの状態を内部状態として管理します。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。`--:--:--:--`、`-- dB`、同期LEDの意味、入力なし／同期外れ／古いタイムコードを非色表現とともに明示する契約が不足します（`STATE-01`、`UNIT-01`）。Jam／生成条件、チャンネル、FPS、オフセット、校正をSnapshot／エクスポートへ保存しません（`DATA-01`、`DATA-02`）。
- **対象外／保留:** Splitは `SPLIT_DEFERRED`、Comparisonはタイムコード表示で1D／XYトレースではないため `NON_TRACE_COMPARISON` です。Compactは大型表示として宣言済みです。
- **根拠:** `src/gui/widgets/timecode_monitor.py`、`MODULE_TIMECODE_MONITOR`、`tests/logic_verification/gui/test_timecode_monitor.py`

### 28. BNIM Meter

- **対応:** 両耳信号からBNIM指標を計算し、音像定位グラフ、クリックテスト、再生更新、Compact、Splitを提供します。入力バッファと再生処理を分離しています。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。指標の暫定／無効、入力不足、クリッピング、テスト信号と実測信号の区別、単位・平滑化条件が結果近傍へ十分に出ません（`STATE-01`、`UNIT-01`、`PLOT-01`）。BNIM結果の取得条件、校正、品質、時刻を保存／比較するSnapshotがありません（`DATA-01`、`DATA-02`）。
- **対象外／保留:** Comparisonは `COMPARISON_DEFERRED` です。
- **根拠:** `src/gui/widgets/bnim_meter.py`、`MODULE_BNIM_METER`、`tests/logic_verification/gui/test_bnim_meter.py`

### 29. HRTF Player

- **対応:** SOFAファイル読込、HRTF位置プロット、クリック／ホワイトノイズ／帯域ノイズの試聴、回転再生を提供します。ファイル不正や未読込時のエラーを通知します。
- **未対応／要確認:** `A11Y-01`。再生／停止、位置、ファイル選択、カスタムプロット値への accessible name がなく、色と点だけで位置・状態を表現します（`THEME-01`、`PLOT-01`）。`QMessageBox` の一部タイトルや音種ラベルが直接文字列で、`I18N-01` に反します。SOFAの測定条件、選択位置、再生条件、補間法をSnapshot／エクスポートしません（`DATA-01`、`DATA-02`）。
- **対象外:** Compact、Splitは `COMPACT_DEFERRED`／`SPLIT_DEFERRED`、Comparisonは2D位置／試聴状態であり `NON_TRACE_COMPARISON`、コンソール主操作は単一トグルへ集約しないため対象外です。
- **根拠:** `src/gui/widgets/hrtf_player.py`、`MODULE_HRTF_PLAYER`、`tests/logic_verification/gui/test_hrtf_dos.py`、`tests/logic_verification/gui/test_hrtf_player_resample.py`

### 30. Ultrasound AM Modulator

- **対応:** 入力信号をAM変調し、搬送周波数、変調度、入力／出力条件、開始／停止を制御します。開始時の確認ダイアログとフィルター状態を持ち、コンソール主操作を宣言しています。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。超音波出力という危険性の高い操作について、実出力先、実出力レベル、過負荷、非有限値、停止完了を主要状態としてラッチする契約が不足します（`STATE-01`）。搬送波、変調度、校正、ルーティング、開始時刻をSnapshot／エクスポートしません（`DATA-01`、`DATA-02`）。
- **対象外:** 独立した表示部を持たないためSplit、Compact、Comparisonは `NO_INDEPENDENT_DISPLAY` です。
- **根拠:** `src/gui/widgets/ultrasound_modulator.py`、`MODULE_ULTRASOUND_MODULATOR`、`tests/logic_verification/gui/test_ultrasound_modulator.py`

### 31. Linearity Analyzer

- **対応:** レベルスイープ、入出力直線性、誤差プロット、ワーカー、校正、Start／Stopを実装します。スイープ失敗時にエラーを表示し、測定用の基本操作があります。
- **未対応／要確認:** `A11Y-01`。プロットの線と基準線に直接RGB色を使用し、High Contrast、色以外の誤差判定、軸・単位・基準の明示が不十分です（`THEME-01`、`PLOT-01`）。スイープ条件、出力レベル、校正、入力欠損、品質をSnapshot／エクスポートへ保存せず（`DATA-01`、`DATA-02`）、長い処理のCancelと部分結果の意味も未固定です（`STATE-02`）。
- **対象外／保留:** Compact、Split、Comparisonは各々 `COMPACT_DEFERRED`、`SPLIT_DEFERRED`、`COMPARISON_DEFERRED` です。
- **根拠:** `src/gui/widgets/linearity_analyzer.py`、`MODULE_LINEARITY_ANALYZER`、`tests/logic_verification/gui/test_linearity_analyzer_error.py`

### 32. 1PPS Monitor

- **対応:** 1PPS波形、パルス数、サンプルクロック偏差、履歴、ウォームアップ、校正確認を表示し、Start／Stopを実装します。履歴配列を取得し、校正値を保存する確認フローがあります。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。パルス欠落、ウォームアップ中、同期外れ、履歴不足、推定中／無効を主要値と明確に分離しません（`STATE-01`）。履歴、基準時刻、サンプルレート、補正値、品質を不変Snapshot／エクスポートへ保存しません（`DATA-01`、`DATA-02`）。校正後にどの取得へ適用されたかの境界も専用テストがありません（`UNIT-01`、`TEST-01`）。
- **対象外／保留:** Compact、Split、Comparisonは各々 `COMPACT_DEFERRED`、`SPLIT_DEFERRED`、`COMPARISON_DEFERRED` です。
- **根拠:** `src/gui/widgets/one_pps_monitor.py`、`MODULE_1PPS_MONITOR`、`tests/logic_verification/gui/test_one_pps_monitor.py`

### 33. Stereo Alignment Monitor

- **対応:** L/Rレベル、バランス、位相、相関、FFT、判定、履歴を表示し、Compact、Start／Stop、CSV出力を提供します。CSV出力の基本操作と整合性ロジックのテストがあります。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。合否を緑／黄／赤の色へ強く依存し、判定理由・閾値・状態をテキストと形で一貫表示しません（`STATE-01`、`THEME-01`）。CSVにサンプルレート、窓、チャンネル、校正、測定時刻、品質フラグ、単位・軸を十分に含めません（`DATA-02`）。
- **対象外／保留:** Splitは `SPLIT_DEFERRED`、Comparisonは `COMPARISON_DEFERRED` です。Compactは宣言済みです。
- **根拠:** `src/gui/widgets/stereo_alignment_monitor.py`、`MODULE_STEREO_ALIGNMENT_MONITOR`、`tests/logic_verification/gui/test_stereo_alignment_monitor.py`

### 34. Spatial Binaural Mixer

- **対応:** 複数トラック、SOFA、空間配置、レンダリングワーカー、WAVエクスポートを扱います。長いトラックリストにはスクロール領域を使用し、レンダリング結果の失敗を通知します。動的トラック行の方位角、仰角、ゲインはラベルと入力を関連付け、`X`、`◀`、`▶` を含む操作には翻訳済みの accessible name とキーボード順序があります。
- **未対応／要確認:** SOFA、トラック設定、ゲイン、位置、サンプルレート、レンダリング条件をWAVへ添付するsidecar／レポートがありません（`DATA-02`）。レンダリング中のCancel、処理中と完了、出力先と危険出力の状態が未固定です（`STATE-01`、`STATE-02`、`THEME-01`）。ライブ状態の読み上げとフォント拡大時の操作は手動確認が残ります（`A11Y-01`）。
- **対象外:** 独立した測定結果表示部を持たないためSplit、Compact、Comparisonは `NO_INDEPENDENT_DISPLAY`。複数トラック操作を単一コンソール主操作へ集約しないため対象外です。
- **根拠:** `src/gui/widgets/spatial_binaural_mixer.py`、`MODULE_SPATIAL_BINAURAL_MIXER`、`tests/logic_verification/gui/widgets/test_spatial_binaural_mixer.py`

### 35. Processor Benchmark

- **対応:** FFT処理とUI描画のベンチマーク結果、状態、コピー可能なレポートを表示し、測定用途に応じた開始処理があります。共通ラッパーの撮影・ログを利用できます。
- **未対応／要確認:** モジュール固有の直接ウィジェットテストが確認できず、`TEST-01` が明確です。ベンチマーク条件、OS、CPU、FFTサイズ、描画負荷、測定時刻を不変結果として保存しません（`DATA-01`）。処理中／キャンセル／失敗、AudioEngine callback欠落と描画フレーム欠落の区別も未固定です（`STATE-01`、`STATE-02`）。`A11Y-01`、`THEME-01` も残ります。
- **対象外／保留:** Compact、Split、Comparisonは `COMPACT_DEFERRED`、`SPLIT_DEFERRED`、`COMPARISON_DEFERRED`、コンソール主操作は単一の測定トグルへ集約しないため対象外です。
- **根拠:** `src/gui/widgets/processor_benchmark.py`、`MODULE_PROCESSOR_BENCHMARK`

### 36. Plot Comparer

- **対応:** `ComparisonManager` のトレースを受信し、ドメインフィルタ、表示／非表示、色、Y軸割当、ゲインオフセット、時間シフト、カーソル、複数軸、CSV／JSONエクスポートを提供します。比較器自身を送信元にしない能力宣言はガイドラインに適合します。
- **未対応／要確認:** トレース色、軸線、ステータス色へ直接色指定があり、`THEME-01`。カスタム読出し、折りたたみボタン、色選択、軸割当の accessible name とキーボード操作が不足します（`A11Y-01`、`CONTROL-01`）。比較不能な単位、校正、品質フラグ、変換をUIで常に理由付き除外する契約と、エクスポートの品質情報が不十分です（`DATA-01`、`DATA-02`、`PLOT-01`）。
- **対象外:** SplitとCompactは `*_DEFERRED`、Comparisonは受信・表示側のため `COMPARISON_RECEIVER`、コンソール主操作は対象外です。
- **根拠:** `src/gui/widgets/plot_comparer.py`、`src/core/comparison_manager.py`、`MODULE_PLOT_COMPARER`、`tests/logic_verification/gui/test_plot_comparer.py`

### 37. Transmission Analyzer

- **対応:** PRBS伝送、遅延、同期、ドリフト、統計、モード切替をリアルタイムに処理し、Compact、Start／Stop、統計リセットを提供します。バッファの読み書きと無効状態の処理があります。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。デジタル整合性、遅延、レベル、ドリフト、PRBS条件の単位と品質フラグを一体化した不変Snapshot／エクスポートがありません（`UNIT-01`、`DATA-01`、`DATA-02`）。表示更新と取得、欠損、クリッピング、校正失効、Reset後の値の意味を専用テストで固定していません（`STATE-01`、`TEST-01`）。
- **対象外／保留:** Splitは `SPLIT_DEFERRED`、Comparisonは `COMPARISON_DEFERRED`。Compactは宣言済みです。
- **根拠:** `src/gui/widgets/transmission_analyzer.py`、`MODULE_TRANSMISSION_ANALYZER`、`tests/logic_verification/gui/test_missing_widget_capability_paths.py`

### 38. Nonlinear Analyzer

- **対応:** SSS測定、レイテンシ校正、線形／高調波カーネル、測定ワーカー、停止、モデル出力を実装します。測定失敗とワーカー終了を通知する経路があります。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。手順の現在段階、残り、出力中、部分結果、キャンセル後の結果有効性を一つのProcedure状態として表示しません（`STATE-01`、`STATE-02`）。モデル／応答のエクスポートはありますが、DUT、サンプルレート、ルーティング、校正、スイープ条件、品質フラグを一体にした取得Snapshotではありません（`DATA-01`、`DATA-02`）。
- **対象外／保留:** Compact、Split、Comparisonは各々 `COMPACT_DEFERRED`、`SPLIT_DEFERRED`、`COMPARISON_DEFERRED`、コンソール主操作は対象外です。
- **根拠:** `src/gui/widgets/nonlinear_analyzer.py`、`MODULE_NONLINEAR_ANALYZER`、`tests/logic_verification/gui/test_nonlinear_analyzer_gui.py`

### 39. Lock-in Modeler

- **対応:** SSS、レイテンシ校正、周波数応答、Hammersteinモデル同定、進捗、モデルの読込／保存、スクロール可能な設定領域を提供します。計算を専用スレッドへ分離します。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。長いProcedureに対するStart／Stop／Cancel、再実行、部分結果、失敗後の安全状態、古いワーカー結果の世代管理を専用テストで固定していません（`STATE-02`、`LIFE-01`）。モデルエクスポートに取得条件、校正、品質、DUT構成を完全な来歴として含める契約がありません（`DATA-01`、`DATA-02`）。
- **対象外／保留:** Compact、Split、Comparisonは各々 `COMPACT_DEFERRED`、`SPLIT_DEFERRED`、`COMPARISON_DEFERRED`。コンソール主操作は `btn_toggle` で宣言済みです。
- **根拠:** `src/gui/widgets/lock_in_modeler.py`、`MODULE_LOCKIN_MODELER`、`tests/logic_verification/gui/widgets/test_lock_in_modeler.py`

### 40. Response Viewer

- **対応:** Hammersteinモデルの線形／高調波応答、Bode、2Dマップ、ノイズ、Wiener、参照トーンを表示し、モデル読込、キャッシュ利用、カーソル、構造表示を提供します。設定グループには部分的な accessible name があります。
- **未対応／要確認:** `H2 Map`等の表示ラベル、`N/A`、一部のエラーダイアログは完全な翻訳単位へ整理されていません（`I18N-01`）。曲線、マーカー、警告の直接色、マップの閾値・補間・カラーバー、カーソルのキーボード操作が未完了です（`THEME-01`、`PLOT-01`、`A11Y-01`）。モデルの出典、測定条件、校正、品質フラグを表示・保存する契約が不足します（`DATA-01`、`DATA-02`）。
- **対象外／保留:** Compact、Split、Comparisonは `COMPACT_DEFERRED`、`SPLIT_DEFERRED`、`COMPARISON_DEFERRED`。これはレビュー用ビューアであり、単一のコンソール主操作は対象外です。
- **根拠:** `src/gui/widgets/response_viewer.py`、`MODULE_RESPONSE_VIEWER`、`tests/logic_verification/gui/widgets/test_response_viewer_contours.py`、`tests/logic_verification/gui/widgets/test_response_viewer_noise_floor.py`、`tests/logic_verification/gui/widgets/test_response_viewer_wiener.py`

### 41. Feedforward Compensator

- **対応:** モデル読込、線形／非線形補償、オンライン／オフライン処理、進捗、Cancel、結果出力、モデル方向の警告を実装します。重い処理はワーカーへ分離し、close時にキャンセルします。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。補償を有効にした実出力、バイパス、レベル、遅延、過負荷、非有限出力の状態を主要表示へ一貫して結び付けません（`STATE-01`）。読み込んだモデルの測定条件、校正、原本、補償パラメータ、処理結果の品質を不変Snapshot／比較形式へ保存しません（`DATA-01`、`DATA-02`）。
- **対象外／保留:** Compact、Split、Comparisonは各々 `COMPACT_DEFERRED`、`SPLIT_DEFERRED`、`COMPARISON_DEFERRED`、コンソール主操作は対象外です。
- **根拠:** `src/gui/widgets/feedforward_compensator.py`、`MODULE_FEEDFORWARD_COMPENSATOR`、`tests/logic_verification/gui/widgets/test_feedforward_compensator.py`

### 42. Nonlinear Response Analyzer

- **対応:** ノイズ刺激、レイテンシ校正、Wiener系の線形／非線形応答、残差、測定ワーカー、失敗表示を実装します。測定処理とGUI更新を信号経由で分離し、開始／停止を提供します。
- **未対応／要確認:** `A11Y-01`、`THEME-01`。測定条件、校正、刺激、入力／出力、推定の収束、残差品質、部分結果を不変Snapshot／エクスポートへ保存しません（`STATE-01`、`UNIT-01`、`DATA-01`、`DATA-02`）。長い処理のCancel、再実行、古いワーカー結果の上書き防止を専用受け入れテストで固定していません（`STATE-02`、`LIFE-01`、`TEST-01`）。
- **対象外／保留:** Compact、Split、Comparisonは各々 `COMPACT_DEFERRED`、`SPLIT_DEFERRED`、`COMPARISON_DEFERRED`、コンソール主操作は対象外です。
- **根拠:** `src/gui/widgets/nonlinear_response_analyzer.py`、`MODULE_NONLINEAR_RESPONSE_ANALYZER`、`tests/logic_verification/gui/test_nonlinear_analyzer_gui.py`

## 補助ウィジェットと共通GUI

登録42モジュール以外も、ガイドラインの適用対象に含まれるため、ここで記録します。

### Settings

- **対応:** Config／Sessionに属するアプリ設定、デバイス、テーマ、言語、CalibrationManager、SPL／入力／出力校正ウィザードをまとめています。危険な校正変更には確認を挟み、校正データをプロファイルとして保存します。
- **未対応／要確認:** `A11Y-01`。多数の入力、校正フィールド、プロファイル選択、説明ラベルへ accessible name／description、フォーカス順、キーボード完了条件がありません。単位コンボ、校正失効、既定値へのReset、Config／Preset／Sessionの境界を全て自動検証していません（`UNIT-01`、`CONTROL-01`、`TEST-01`）。直接色指定と固定レイアウトも残ります（`THEME-01`）。
- **根拠:** `src/gui/widgets/settings.py`、`docs/widgets/settings.md`、`tests/logic_verification/gui/test_settings_structure.py`、`tests/logic_verification/gui/widgets/test_settings_calibration_profiles.py`

### Welcome

- **対応:** モジュールの目的と起動導線を示す案内画面で、測定値や危険出力を持ちません。サイドバー選択へ誘導します。
- **未対応／要確認:** 画像、案内ラベル、主要導線の accessible description、キーボードでの発見性、テーマトークンによる直接色の統一が未確認です（`A11Y-01`、`THEME-01`）。測定ウィジェットの状態・結果を扱わないため、`STATE-01`、`DATA-01` は適用外です。
- **根拠:** `src/gui/widgets/welcome.py`、`docs/widgets/welcome.md`、`tests/logic_verification/gui/widgets/test_welcome.py`

### DetachableWidgetWrapper

- **対応:** ヘッダー操作の accessible name／ツールチップ、State A／B／C、再接続、Compact、スクリーンショット、共通ログ、Comparison送信、分離中の再表示を共通化しています。能力宣言とインターフェースを実行時検証します。
- **未対応／要確認:** スクリーンショットは視覚記録であり、取得条件・単位・校正・品質フラグのsidecarやレポートを自動添付しません（`DATA-02`）。ヘッダー以外のモジュール内部コントロールは保証しません（`A11Y-01`）。ヘッダーの固定サイズ、直接QSS、OS別ウィンドウマネージャー、高DPI、複数モニターは手動確認が必要です（`THEME-01`、`TEST-01`）。
- **根拠:** `src/gui/widgets/detachable_wrapper.py`、`tests/logic_verification/gui/test_detachable_wrapper_split_actions.py`、`tests/logic_verification/gui/test_main_window_activity.py`

### Measurement Console

- **対応:** 既存のウィジェットインスタンスをドックへ移動し、タイトルバーへ主操作を再掲します。元ボタンとのラベル、チェック状態、有効状態を同期し、4計器のグリッド／タブ化と狭い画面へのレスポンシブ切替を実装しています。
- **未対応／要確認:** ドック内で各モジュールの重要状態、警告、値の古さ、単位、品質を常時見失わないことを、全42モジュールで確認するテストはありません（`STATE-01`、`A11Y-01`）。Consoleのワークスペース保存と測定結果Snapshotを混同しないこと、複数モニター・高DPI・長時間通知は手動確認が必要です（`DATA-01`、`TEST-01`）。
- **根拠:** `src/gui/measurement_console.py`、`docs/widgets/measurement_console.md`、`tests/logic_verification/gui/test_measurement_console.py`

### Log Viewer

- **対応:** 共通ログビューアとして情報、警告、エラー、例外の診断導線を提供します。各ウィジェットが個別ログ画面を再実装せず、Moreメニューから開けます。
- **未対応／要確認:** ログ表示だけで測定結果の無効フラグや主要状態が置き換わらないこと、同一原因の通知集約、長時間のログ量、検索・フィルタのキーボード操作を全モジュールの利用文脈で検証していません（`STATE-01`、`A11Y-01`、`TEST-01`）。
- **根拠:** `src/gui/widgets/log_viewer.py`、`tests/logic_verification/gui/test_log_viewer_logic.py`

### ExportSettingsDialog と ComparisonManager

- **対応:** `ComparisonTrace` は軸、単位、対数フラグ、校正、日時、元モジュール、任意メタデータを保持します。CSVのmerged／independent、ヘッダー、メタデータ、JSONの保存／読込、CSVインジェクション対策があります。
- **未対応／要確認:** 全モジュールが同じ粒度のメタデータを生成する契約になっていません。CSVヘッダーやメタデータが、クリッピング、欠損、暫定／無効、窓補正、平滑化、変換の全てを自動表現するわけではありません（`DATA-01`、`DATA-02`）。エクスポート設定のアクセシビリティ、フォーカス順、無効理由を専用に固定していません（`A11Y-01`、`CONTROL-01`）。
- **根拠:** `src/core/comparison_manager.py`、`src/core/export/csv_exporter.py`、`src/gui/widgets/export_dialog.py`、`tests/logic_verification/core/test_comparison_manager.py`、`tests/core/export/test_csv_exporter.py`

## 能力宣言上の対象外一覧

対象外はガイドライン上の欠陥とは限りません。ただし、`*_DEFERRED` は「不要」と確定した意味ではなく、実用度・安全性・データ形式をレビューしていない未実装候補です。

| 対象外理由 | 該当する主なモジュール | 意味 |
| --- | --- | --- |
| `NO_INDEPENDENT_DISPLAY` | Signal Generator、Recorder / Player、Ultrasound AM Modulator、Spatial Binaural Mixer | 表示部と操作部を安全に分ける独立表示領域がない |
| `NON_TRACE_COMPARISON` | Loopback Finder、Spectrogram、Timecode Monitor & Generator、HRTF Player | 表・単一値・状態・2D位置／画像で、現在の比較基盤の1D／XYトレースではない |
| `COMPARISON_RECEIVER` | Plot Comparer | 比較データの受信・表示側であり、送信元ではない |
| `COMPARISON_DEFERRED` | Sound Level Meter、LUFS Meter、Advanced Distortion Meter、Lock-in Harmonic Analyzer、Arbitrary Harmonic Generatorなど | 比較仕様または実用性を未確定のまま送信を保留 |
| `COMPACT_DEFERRED` | Loopback Finder、Distortion Analyzer、Advanced Distortion Meter、Network Analyzerなど | 最小表示で残す値・警告・単位を未定義のまま保留 |
| `SPLIT_DEFERRED` | Loopback Finder、Distortion Analyzer、Advanced Distortion Meter、Network Analyzerなど | 表示／操作を二窓へ分ける状態所有・フォーカス・安全条件を未定義のまま保留 |

## 検証記録

2026-08-26に次を実行しました。

| コマンド | 結果 |
| --- | --- |
| `./.venv/bin/python scripts/check_ui_size_limits.py` | `Verification Passed!`。全言語の表示レイアウトがサイズ・スクロール契約に適合 |
| `./.venv/bin/python scripts/check_trn_keys.py` | `TEST PASSED`。2270キー、全言語整合 |
| `./.venv/bin/pytest -q tests/logic_verification/gui/test_widget_capabilities.py tests/logic_verification/gui/test_measurement_console.py tests/logic_verification/gui/test_detachable_wrapper_split_actions.py tests/logic_verification/gui/test_plot_comparer.py` | `86 passed, 1 warning` |
| `./.venv/bin/pytest -q` | `1321 passed, 6 skipped, 29 subtests passed`。スキップは実機オーディオハードウェア依存 |
| `./.venv/bin/ruff check .` | `All checks passed!` |
| `./.venv/bin/ruff format --check .` | `494 files already formatted` |
| `npx markdownlint-cli2 "**/*.md" "#node_modules"` | `0 issues in 0 files` |

今回の自動検証で確認できない範囲は次のとおりです。

- 実機オーディオでの開始／停止、ルーティング、過負荷、校正。
- Windows、macOS、Linuxのフォントメトリクスとネイティブ操作。
- 高DPI、フォント拡大、狭い画面、複数モニター、ウィンドウマネージャー。
- 色覚シミュレーション、High Contrast、長時間利用時の通知疲れ。
- すべてのモジュールのフォーカス順、スクリーンリーダー、キーボードのみの完了。

## 主な根拠コード

- モジュール一覧: `src/core/module_constants.py`
- モジュール登録・能力宣言: `src/gui/module_registry.py`
- メインウィンドウ・共通状態・I/O表示: `src/gui/main_window.py`
- 分離、分割、撮影、ログ、比較送信: `src/gui/widgets/detachable_wrapper.py`
- 計測コンソール: `src/gui/measurement_console.py`
- 比較データ契約: `src/core/comparison_manager.py`、`src/gui/widgets/comparable_interface.py`
- 校正: `src/core/calibration.py`、`src/gui/widgets/settings.py`
- 翻訳: `src/core/localization.py`、`src/assets/lang/*.json`
- テーマ: `src/core/theme_manager.py`、`src/gui/styles.py`
- サイズ検証: `scripts/check_ui_size_limits.py`
- 翻訳検証: `scripts/check_trn_keys.py`
