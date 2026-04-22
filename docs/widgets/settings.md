# Settings (設定)

## 概要

Settings（設定）ウィジェットでは、アプリケーション全体の動作に関わる設定を管理します。オーディオデバイスの選択、キャリブレーション（校正）、表示言語やテーマの変更などはここで行います。

## General (一般設定)

### Language (言語)

アプリケーションの表示言語を変更します。変更を適用するにはアプリケーションの再起動が必要です。

### Appearance (外観)

アプリケーションのテーマカラーを選択します。

* **System**: システムの設定に従います。
* **Light**: ライトテーマ（白基調）。
* **Dark**: ダークテーマ（黒基調）。

### Screenshots (スクリーンショット)

各測定ウィジェットでスクリーンショットを撮影した際の保存先フォルダを指定します。「Browse...」ボタンでフォルダを選択できます。

### FFT Optimization (FFT最適化)

FFT（高速フーリエ変換）の処理速度を向上させるための最適化を行います。

* **Regenerate Optimization**: 最適化処理を実行します。実行には数秒〜数分かかる場合があります。
* **Include Huge Sizes**: チェックを入れると、非常に大きなデータサイズ（最大4Mサンプル）の最適化も行います。処理に時間がかかりますが、巨大なFFTを行う場合に有利です。

## Audio (オーディオ設定)

### Audio Devices (オーディオデバイス)

使用する入出力デバイスを選択します。以前の設定項目がタブに分かれました。

* **Audio Devices タブ**:
    * **Host API**: オーディオバックエンド（API）を選択します（例: MME, WASAPI, ASIO, ALSA, JACKなど）。
    * **Input Device**: 測定用マイクなどを接続した入力デバイスを選択します。
    * **Output Device**: スピーカーなどを接続した出力デバイスを選択します。
    * **Refresh Devices**: デバイスリストを更新します。Linux環境でJACKが動作している場合は、安全のため無効化されます。
    * **Measure Bit Depth...**: オーディオデバイスの実効ビット深度（ENOB）と量子化ノイズの特性を測定・可視化するためのダイアログを開きます。「Start Analysis」ボタンで測定を開始します。実測に基づいたビット深度の確認に役立ちます。
        * **Effective Bit Depth History**: ENOB（有効ビット数）の時系列変化を表示します。
        * **Bit Activity (LSB to MSB)**: 各ビット（LSBからMSBまで）の活動状況をヒートマップで可視化します。スタックビット（常に0または1）の検出に役立ちます。
        * **Quantization Step (Delta) Distribution**: 隣接サンプル間の差分（量子化ステップ）の分布を表示します。
* **Virtual / Offline Mode タブ**:
    * **Virtual Audio (No Hardware)**: 仮想オーディオドライバを有効にします。物理的なインターフェースがない場合に使用します。
    * **Simulation Rate**: 仮想モード時のサンプリングレートを設定します。

### Audio Configuration (オーディオ構成)

* **PipeWire / JACK Mode (Resident)**: Linux 環境で PipeWire や JACK を使用する場合に有効にします。チェックを入れると、ウィジットをすべて閉じてもオーディオエンジンが動作し続け、外部接続が維持されます。
* **Sample Rate**: サンプリング周波数を選択します。
* **Buffer Optimization**: 用途に合わせたバッファサイズの最適化レベルを選択します。
* **Buffer Size**: 実際のオーディオバッファのサイズです。

💡 **ちょっと賢くなる知識：バッファサイズとディザリングって何？**

* **バッファサイズ（Buffer Size）**: これは音を運ぶ「バケツの大きさ」です。バケツが小さいと何度も水を運ぶので少しの遅れ（レイテンシ）ですみますが、パソコンが疲れて音切れしやすくなります。バケツが大きいとパソコンは楽ですが、少し音が遅れて聞こえます。MeasureLabは「測定」が目的なので、基本的には音が途切れない大きなバケツ（STABLE以上）をおすすめします。
* **ディザリング（Dithering）**: デジタルオーディオの世界では、音を「階段」のようにカクカクした数値で表現します。音がとても小さくなると、この階段を上り下りできなくなり、音が歪んだり消えたりしてしまいます。そこで、わざと「シャー」という微小なノイズ（ディザ）を足して階段の角を削り、滑らかなスロープにする魔法の技術がディザリングです。

* **Input/Output Channels**: チャンネルモードを選択します（Stereo, Left, Right）。
* **Enable Dithering (TPDF)**: 出力信号に量子化歪み軽減のためのディザを付加します。
* **Dithering Bit Depth**: ディザリングを適用するビット深度を選択します。

## Calibration (キャリブレーション)

測定精度を高めるための校正を行います。各項目の「Wizard」ボタンを押すと、対話形式で校正を行えます。

### Calibration Profiles (キャリブレーションプロファイル)

現在の日付や入出力設定などをプロファイルとして保存できます。

* **Select Profile**: 保存済みのプロファイルを選択します。
* **Delete**: 選択したプロファイルを削除します。
* **Duplicate Profile**: 現在の設定に新しい名前を付けて保存（複製）します。既存の名前を入力すると上書きされます。

### Current Settings

* **Input Sensitivity (入力感度)**: 入力信号の電圧レベルの設定です。「Wizard」で自動計算できます。
* **Output Gain (出力ゲイン)**: 出力信号の電圧レベルの設定です。「Wizard」で自動計算できます。
* **SPL Offset (音圧レベル補正)**: Sound Level Meterなどで表示されるdB SPL値の補正値です。「Wizard」で自動計算できます。

### Stored Calibration Values (内部校正値・拡張設定)

「Show stored calibration values」にチェックを入れると表示されます。

* **Frequency Calibration Source**: オーディオエンジンの周波数補正に使用する基準ソースを選択します（設定変更可能）。
    * **Frequency Counter**: Frequency Counter ウィジェットで校正された係数を使用します。
    * **1PPS Monitor**: 1PPS Monitor ウィジェットで校正（Calibrate from Current）された係数を使用します。1PPS 基準を利用可能な場合に、より高精度な校正を行えます。
* **Frequency Calibration**: 内部クロックの周波数偏差（ppm）。（参照用）
* **1PPS Frequency Calibration**: 1PPS信号に基づく外部基準との偏差（ppm）。（参照用）
* **Lock-in Gain Offset**: ロックインアンプ測定時の内部ゲイン補正値（mdB/dB）。（参照用）
