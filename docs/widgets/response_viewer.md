# Response Viewer (応答ビューア)

![Response Viewer](../assets/widgets/response_viewer.png)

## 概要

Response Viewerは、[Nonlinear Analyzer](nonlinear_analyzer.md) によって抽出された線形および高調波応答特性（最大5次）を可視化、重ね合わせ比較、および解析する高度なビューアです。測定されたハマーシュタインモデルの周波数応答や、任意の周波数・振幅におけるシステムの出力挙動（ゲインコンプレッションなど）をシミュレーションによって詳細に評価することができます。

## 主な機能と操作方法

### モデルの読み込み (Model Source)

* **Load Live Cache**: 直近で Nonlinear Analyzer によって測定・抽出されたモデルを直接読み込みます。
* **Import Model JSON...**: 保存されたハマーシュタインモデルのJSONファイルを読み込みます。

### 2Dマップ (2D Map)

* **Map Type**: 表示するマップの種類を選択します。
  * **THD Map**: 基本波に対する全高調波歪みのマップ。
  * **Distortion Map (nth)**: 2次〜5次の各高調波成分の個別マップ。
* **Harmonic Unit**: マップ上のレベルの単位を相対値（dBr）または絶対値（dBFS）から選択します。
* **Resolution**: マップの計算解像度を調整します（Overview, Standard, Detail）。
* **Min/Max Level**: 入力振幅（Y軸）の表示範囲を設定します。
* **Color Map**: マップのカラーパレットを変更します。
* **Show Contours**: マップ上に等高線を描画します。
* **Enable Noise Floor**: 測定されたノイズフロアまたは手動設定したノイズフロアを加味してプロットします。

### 歪みカーブ (Dist. Curves)

* **Reference Tone Settings**: 評価の基準となる「入力周波数」および「入力振幅」を設定します。
* 上段のプロットは基準振幅における周波数スイープの歪み特性を、下段のプロットは基準周波数における振幅スイープの歪み特性を表示します。

### シミュレータ (Simulator)

* 設定された基準周波数・振幅を入力したと仮定した際の、出力の予測スペクトルを棒グラフ形式でシミュレーション表示します。
* 各高調波の予測振幅と位相のリストもあわせて確認できます。

### 入出力特性と圧縮 (I/O & Comp)

* **Input-Output Transfer Curve**: 基準周波数における入出力の伝達特性（リニア成分と実際の出力）を可視化し、システムの1dBコンプレッションポイント（P1dB）を推定します。
* **Gain Compression**: リニアゲインからのずれ（圧縮誤差）をプロットします。
