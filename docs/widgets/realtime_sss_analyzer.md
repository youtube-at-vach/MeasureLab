# Realtime SSS Lockin Analyzer

## 概要

Realtime SSS Lockin Analyzerは、Synchronized Swept Sine (SSS) 信号とデジタルロックイン方式を使用して、リアルタイムに周波数特性と歪みのスイープ測定を行うツールです。指定した周波数範囲での振幅特性と位相特性、さらに高調波の追跡が可能です。

## 操作方法

### 測定の開始と停止

* **Start Sweep / Stop Sweep ボタン**: SSS測定スイープを開始および停止します。測定中は進捗が表示され、完了時は非同期処理が終わるまで一時的にボタンが無効になります。

### レイテンシのキャリブレーション

* **Calibrate Latency**: スイープを実行する前（特に2ch相対測定モード時）に、入出力のタイミングを合わせることが重要です。このボタンを押すとテスト信号が送信され、システムのレイテンシ（遅延）を測定して補正し、ラベルに結果を表示します。

## 設定項目

### Settings タブ

* **Start Freq / End Freq (Hz)**: スイープの開始および終了周波数を設定します。
* **Duration (s)**: 1回のスイープにかかる時間を設定します。
* **Amplitude (dBFS)**: 出力信号のレベルを設定します。
* **Max Harmonic**: 基本波と同時に解析する最大高調波の次数を設定します。
* **Averages**: スイープのアベレージング（平均化）回数を設定します。増やすとSNRが向上します。
* **Mode**: 測定モードを選択します。標準スイープ（Standard Sweep）とHammerstein Modelが選択可能です。
* **Unwrap Phase**: 有効にすると、位相特性の不連続性を防ぐためにアンラップ処理を行います。
* **Relative Mag Mode**: 有効にすると、基本波や基準レベルに対する相対的な振幅を表示します。

### Routing タブ

* **Output Ch**: スイープ信号を出力するチャンネル（Left、Right、またはStereo）を選択します。
* **Input Mode**: 入力のリファレンス（基準）と測定チャンネルを設定します。
    * **Single Ch (Left / Right Input)**: 単一チャンネルでの測定です。
    * **2-Ch Relative (Ref=Left, Meas=Right / Ref=Right, Meas=Left)**: 2チャンネルを使用した伝達特性（XFER）モードです。

### Advanced タブ

* **Analysis Cycles**: デジタルロックイン解析において、各周波数ビンで解析するサイクル数を設定します。
* **Min Analysis Window (ms)**: 最小解析ウィンドウ時間をミリ秒単位で設定します。この設定に基づき、リアルタイムのENBW（等価雑音帯域幅）分解能が動的に表示されます。
* **Meas Points**: スイープ全体で測定する周波数ポイントの総数を設定します。
* **Prevent Buffer Underrun**: 有効にすると、CPU負荷が高い場合にデータ処理を一時停止し、音声の途切れ（バッファアンダーラン）を防ぎます。
* **Asynchronous Calculation**: 重いSSS計算をバックグラウンドのスレッドで実行し、UIの応答性を保ちます。

### Kernel タブ

* Hammerstein Modelモードで動作している場合、再構築された時間領域のカーネルを表示します。このタブでは、非線形システムの特性を持続的に確認することができます。
