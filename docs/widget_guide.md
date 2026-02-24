# 用途別ガイド

MeasureLab に搭載されている多数のウィジットを、用途ごとに分類して紹介します。

---

## 🔍 クイック検索ガイド {: #quick-search-guide }

「やりたいこと」から最適なツールをすぐに見つけるための早見表です。

| あなたがやりたいこと | おすすめのウィジット |
| :--- | :--- |
| **まず音を出したい / 信号源がほしい** | [Signal Generator](widgets/signal_generator.md) |
| **周波数成分（スペクトル）を見たい** | [Spectrum Analyzer](widgets/spectrum_analyzer.md) |
| **波形の形をそのまま見たい** | [Oscilloscope](widgets/oscilloscope.md) |
| **アンプや部品の歪み(THD)を測りたい** | [Distortion Analyzer](widgets/distortion_analyzer.md) |
| **アンプ等の周波数特性(F特)を測りたい** | [Network Analyzer](widgets/network_analyzer.md) |
| **スピーカーのインピーダンスを測りたい** | [Impedance Analyzer](widgets/impedance_analyzer.md) |
| **音の大きさ(LUFS)を管理したい** | [LUFS Meter](widgets/lufs_meter.md) |
| **周囲の騒音レベル(SPL)を知りたい** | [Sound Level Meter](widgets/sound_level_meter.md) |
| **ノイズの種類(1/f等)を分析したい** | [Noise Profiler](widgets/noise_profiler.md) |

---

## 📡 信号生成

信号を出力したり、基準信号を生成するツールです。

* **[Signal Generator](widgets/signal_generator.md)**
    * 正弦波、ノイズ、スイープ信号などを生成します。測定の基本となる信号源です。

* **[Timecode Monitor & Generator](widgets/timecode_monitor.md)**
    * LTC (Linear Timecode) の生成と監視を行います。映像機器との同期確認などに使用します。

* **[1PPS Monitor](widgets/one_pps_monitor.md)**
    * GPSなどからの1PPS信号を監視し、サンプリングレートの偏差(PPM)を測定します。

* **[Ultrasound AM Modulator](widgets/ultrasound_modulator.md)**
    * オーディオ信号を超音波(40kHz)で振幅変調して出力します。パラメトリックスピーカーの実験に使用します。

---

## 📊 基本解析

オーディオ信号の基本的な特性（スペクトル、レベル、周波数）を測定します。

* **[Spectrum Analyzer](widgets/spectrum_analyzer.md)**
    * FFTを用いて周波数成分（スペクトル）をリアルタイムに表示します。

* **[Sound Level Meter](widgets/sound_level_meter.md)**
    * 騒音計です。音圧レベル (SPL) や等価騒音レベル (Leq) を測定します。

* **[LUFS Meter](widgets/lufs_meter.md)**
    * ラウドネスレベル (LUFS) を測定します。放送や配信向けのレベル管理に適しています。

* **[Frequency Counter](widgets/frequency_counter.md)**
    * 入力信号の周波数を高精度にカウントします。アラン分散などの統計解析も可能です。

* **[Spectrogram](widgets/spectrogram.md)**
    * 時間経過に伴う周波数成分の変化を色で可視化します（声紋分析など）。

---

## 📉 歪み・音質

機器の性能や音の品質を評価するためのツールです。

* **[Distortion Analyzer](widgets/distortion_analyzer.md)**
    * THD (全高調波歪) や THD+N を測定します。基本的な歪み測定はこちらを使用します。

* **[Linearity Analyzer](widgets/linearity_analyzer.md)**
    * 入出力のレベル直線性を測定します。DACの微小信号再現能力やダイナミックレンジの検証に使用します。

* **[Advanced Distortion Meter](widgets/advanced_distortion_meter.md)**
    * マルチトーン測定や IMD (混変調歪) など、より高度な歪み解析を行います。



* **[Lock-in Harmonic Analyzer](widgets/lockin_harmonic_analyzer.md)**
    * ロックインアンプの原理と行列表射を用いた、窓関数不要の超低歪み測定モジュールです。

* **[Sound Quality Analyzer](widgets/sound_quality_analyzer.md)**
    * シャープネス (Sharpness) やラフネス (Roughness) など、聴感上の「音質」指標を計算します。

* **[Noise Profiler](widgets/noise_profiler.md)**
    * ノイズフロアの特性（1/fノイズ、ホワイトノイズなど）を分析します。

---

## 🔌 回路・伝達関数

電子回路やシステムの伝送特性、インピーダンスなどを測定します。

* **[Network Analyzer](widgets/network_analyzer.md)**
    * 周波数特性（ゲイン・位相・群遅延）を測定します。アンプやフィルタの特性確認に。

* **[Impedance Analyzer](widgets/impedance_analyzer.md)**
    * スピーカーや素子のインピーダンス特性（LCR）を測定します。

* **[Lock-in Amplifier](widgets/lock_in_amplifier.md)**
    * ノイズに埋もれた微小信号を検出します。FRA（周波数応答解析）としても利用可能です。

* **[Lock-in Frequency Counter](widgets/lock_in_frequency_counter.md)**
    * 基準信号に対する微小な周波数偏差や位相変動を追跡します。

* **[Loopback Finder](widgets/loopback_finder.md)**
    * オーディオインターフェースのループバック経路を検出します。

---

## 📈 時間領域

波形の形状や過渡的な変化を時間軸で観察します。

* **[Oscilloscope](widgets/oscilloscope.md)**
    * 一般的なオシロスコープです。波形そのものを観測します。

* **[Raw Time Series](widgets/raw_time_series.md)**
    * 長い時間の波形を記録し、スクロールして確認できるチャートレコーダーのようなツールです。

* **[Transient Analyzer](widgets/transient_analyzer.md)**
    * インパルス応答などの過渡現象をトリガーして解析します。ウェーブレット変換表示も可能です。

* **[Boxcar Averager](widgets/boxcar_averager.md)**
    * 繰り返し信号を平均化してノイズを除去し、微細な波形を取り出します。

---

## 🎧 空間・音響

ステレオイメージや空間的な音の響きを扱います。

* **[Goniometer](widgets/goniometer.md)**
    * リサージュ図形などでステレオ信号の位相関係（広がり）を表示します。

* **[BNIM Meter](widgets/bnim_meter.md)**
    * Binaural Neural Image Map。聴覚モデルに基づいて音像の定位（ITD/ILD）を可視化します。

* **[HRTF Player](widgets/hrtf_player.md)**
    * 頭部伝達関数 (HRTF/SOFA) を読み込み、畳み込みによる3Dオーディオ再生をシミュレートします。

---

## 🛠️ ユーティリティ

その他の便利な機能です。

* **[Recorder & Player](widgets/recorder_player.md)**
    * シンプルな録音・再生機能です。
* **[Inverse Filter](widgets/inverse_filter.md)**
    * スピーカーや部屋の特性を打ち消すための逆フィルターを作成します。
* **[Detachable Wrapper](widgets/detachable_wrapper.md)**
    * 任意のウィジットを別ウィンドウとして切り離すための枠組みです。
* **[Settings](widgets/settings.md)**
    * オーディオデバイス設定、言語設定、テーマ変更などを行います。
* **[Welcome](widgets/welcome.md)**
    * 起動画面です。
