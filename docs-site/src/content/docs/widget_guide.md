---
title: "用途別ガイド"
---

## 概要

MeasureLab に搭載されている多数のウィジェットを、用途ごとに分類して紹介します。

---

## 🔍 クイック検索ガイド {#quick-search-guide}

「やりたいこと」から最適なツールをすぐに見つけるための早見表です。

| あなたがやりたいこと | おすすめのウィジェット |
| :--- | :--- |
| **まず音を出したい / 信号源がほしい** | [Signal Generator](https://youtube-at-vach.github.io/MeasureLab/widgets/signal_generator/) |
| **複雑な波形を合成したい / 特定の高調波をブレンドした信号を作りたい** | [Arbitrary Harmonic Generator](https://youtube-at-vach.github.io/MeasureLab/widgets/arbitrary_harmonic_generator/) |
| **周波数成分（スペクトル）を見たい** | [Spectrum Analyzer](https://youtube-at-vach.github.io/MeasureLab/widgets/spectrum_analyzer/) |
| **特定の周波数を極めて高い分解能で確認したい** | [Lock-in Spectrum Finder](https://youtube-at-vach.github.io/MeasureLab/widgets/lockin_spectrum_finder/) |
| **波形の形をそのまま見たい** | [Oscilloscope](https://youtube-at-vach.github.io/MeasureLab/widgets/oscilloscope/) |
| **アンプや部品の歪み(THD)を測りたい** | [Distortion Analyzer](https://youtube-at-vach.github.io/MeasureLab/widgets/distortion_analyzer/) |
| **アンプやスピーカーの歪みをフィードフォワード補正したい** | [Feedforward Compensator](https://youtube-at-vach.github.io/MeasureLab/widgets/feedforward_compensator/) |
| **リアルタイムに歪みやF特をスイープ計測し、モデルを構築したい** | [Lock-in Modeler](https://youtube-at-vach.github.io/MeasureLab/widgets/lock_in_modeler/) |
| **アンプ等の周波数特性(F特)を測りたい** | [Network Analyzer](https://youtube-at-vach.github.io/MeasureLab/widgets/network_analyzer/) |
| **スピーカーのインピーダンスを測りたい** | [Impedance Analyzer](https://youtube-at-vach.github.io/MeasureLab/widgets/impedance_analyzer/) |
| **超低歪み(THD)を高精度に測りたい** | [Lock-in Harmonic Analyzer](https://youtube-at-vach.github.io/MeasureLab/widgets/lockin_harmonic_analyzer/) |
| **音の大きさ(LUFS)を管理したい** | [LUFS Meter](https://youtube-at-vach.github.io/MeasureLab/widgets/lufs_meter/) |
| **周囲の騒音レベル(SPL)を知りたい** | [Sound Level Meter](https://youtube-at-vach.github.io/MeasureLab/widgets/sound_level_meter/) |
| **ノイズの種類(1/f等)を分析したい** | [Noise Profiler](https://youtube-at-vach.github.io/MeasureLab/widgets/noise_profiler/) |
| **ポップコーンノイズなど、まれな異常の発生回数を測りたい** | [Event Detector](https://youtube-at-vach.github.io/MeasureLab/widgets/event_detector/) |
| **左右の音響特性のズレを精密に整えたい** | [Stereo Alignment Monitor](https://youtube-at-vach.github.io/MeasureLab/widgets/stereo_alignment_monitor/) |
| **異なる測定から取得した複数のプロットを重ね合わせて比較したい** | [Plot Comparer](https://youtube-at-vach.github.io/MeasureLab/widgets/plot_comparer/) |
| **デジタル/アナログ伝送路の品質、遅延、完全性を総合的に評価したい** | [Transmission Analyzer (試験的)](https://youtube-at-vach.github.io/MeasureLab/widgets/transmission_analyzer/) |

---

## 📡 信号生成

信号を出力したり、基準信号を生成するツールです。

- **[Signal Generator](https://youtube-at-vach.github.io/MeasureLab/widgets/signal_generator/)**
    - 正弦波、ノイズ、スイープ信号などを生成します。測定の基本となる信号源です。

- **[Arbitrary Harmonic Generator](https://youtube-at-vach.github.io/MeasureLab/widgets/arbitrary_harmonic_generator/)**
    - 基本周波数と複数（最大50次）の高調波成分の振幅・位相を自在にコントロールし、複雑な波形を合成できる信号発生器です。

- **[Timecode Monitor & Generator](https://youtube-at-vach.github.io/MeasureLab/widgets/timecode_monitor/)**
    - LTC (Linear Timecode) の生成と監視を行います。映像機器との同期確認などに使用します。

- **[1PPS Monitor](https://youtube-at-vach.github.io/MeasureLab/widgets/one_pps_monitor/)**
    - GPSなどからの1PPS信号を監視し、サンプリングレートの偏差(PPM)を測定します。

- **[Ultrasound AM Modulator](https://youtube-at-vach.github.io/MeasureLab/widgets/ultrasound_modulator/)**
    - オーディオ信号を超音波(40kHz)で振幅変調して出力します。パラメトリックスピーカーの実験に使用します。

---

## 📊 基本解析

オーディオ信号の基本的な特性（スペクトル、レベル、周波数）を測定します。

- **[Spectrum Analyzer](https://youtube-at-vach.github.io/MeasureLab/widgets/spectrum_analyzer/)**
    - FFTを用いて周波数成分（スペクトル）をリアルタイムに表示します。

- **[Lock-in Spectrum Finder](https://youtube-at-vach.github.io/MeasureLab/widgets/lockin_spectrum_finder/)**
    - ロックイン検出を用いて、指定した周波数帯域を高分解能でスペクトル解析します。ノイズに埋もれた特定のピークの拡大観察などに最適です。

- **[Sound Level Meter](https://youtube-at-vach.github.io/MeasureLab/widgets/sound_level_meter/)**
    - 騒音計です。音圧レベル (SPL) や等価騒音レベル (Leq) を測定します。

- **[LUFS Meter](https://youtube-at-vach.github.io/MeasureLab/widgets/lufs_meter/)**
    - ラウドネスレベル (LUFS) を測定します。放送や配信向けのレベル管理に適しています。

- **[Frequency Counter](https://youtube-at-vach.github.io/MeasureLab/widgets/frequency_counter/)**
    - 入力信号の周波数を高精度にカウントします。アラン分散などの統計解析も可能です。

- **[Spectrogram](https://youtube-at-vach.github.io/MeasureLab/widgets/spectrogram/)**
    - 時間経過に伴う周波数成分の変化を色で可視化します（声紋分析など）。

---

## 📉 歪み・音質

機器の性能や音の品質を評価するためのツールです。

- **[Distortion Analyzer](https://youtube-at-vach.github.io/MeasureLab/widgets/distortion_analyzer/)**
    - THD (全高調波歪) や THD+N を測定します。基本的な歪み測定はこちらを使用します。
- **[Nonlinear Analyzer](https://youtube-at-vach.github.io/MeasureLab/widgets/nonlinear_analyzer/)**
    - Hammersteinモデルを用いて、機器の応答から1次（線形）〜5次までの高調波カーネルを分離・抽出する高度な歪み解析ツールです。

- **[Lock-in Modeler](https://youtube-at-vach.github.io/MeasureLab/widgets/lock_in_modeler/)**
    - SSS (Synchronized Swept Sine) 信号とデジタルロックイン方式を使用して、リアルタイムに周波数特性と歪みのスイープ測定を行い、将来的にHammersteinモデルなどのシステムモデル構築へ活用するツールです。

- **[Feedforward Compensator](https://youtube-at-vach.github.io/MeasureLab/widgets/feedforward_compensator/)**
    - Hammersteinシステムモデルを利用し、音声信号に対してフィードフォワード歪み補正（LICFF: Linear-Inverse Compensated Feedforward）を適用します。

- **[Nonlinear Response Analyzer](https://youtube-at-vach.github.io/MeasureLab/widgets/nonlinear_response_analyzer/)**
    - Wienerモデルを同定し、動的な非線形システムの挙動を解析します。
- **[Linearity Analyzer](https://youtube-at-vach.github.io/MeasureLab/widgets/linearity_analyzer/)**
    - 入出力のレベル直線性を測定します。DACの微小信号再現能力やダイナミックレンジの検証に使用します。

- **[Advanced Distortion Meter](https://youtube-at-vach.github.io/MeasureLab/widgets/advanced_distortion_meter/)**
    - マルチトーン測定や IMD (混変調歪) など、より高度な歪み解析を行います。

- **[Lock-in Harmonic Analyzer](https://youtube-at-vach.github.io/MeasureLab/widgets/lockin_harmonic_analyzer/)**
    - ロックインアンプの原理を利用した超低歪み(THD)測定モジュールです。最大200次までの多重並列IQ検波により基本波および高調波へ正確に同調（ロックイン）し、微小な歪みを高精度に抽出します。

- **[Sound Quality Analyzer](https://youtube-at-vach.github.io/MeasureLab/widgets/sound_quality_analyzer/)**
    - シャープネス (Sharpness) やラフネス (Roughness) など、聴感上の「音質」指標を計算します。

- **[Noise Profiler](https://youtube-at-vach.github.io/MeasureLab/widgets/noise_profiler/)**
    - ノイズフロアの特性（1/fノイズ、ホワイトノイズなど）を分析します。

---

## 🔌 回路・伝達関数

電子回路やシステムの伝送特性、インピーダンスなどを測定します。

- **[Network Analyzer](https://youtube-at-vach.github.io/MeasureLab/widgets/network_analyzer/)**
    - 周波数特性(ゲイン・位相・群遅延)の測定。アンプやフィルタの特性確認に便利。フォノイコライザー等の検証に役立つRIAAカーブ重ね合わせ表示に対応。

- **[Impedance Analyzer](https://youtube-at-vach.github.io/MeasureLab/widgets/impedance_analyzer/)**
    - スピーカーや素子のインピーダンス特性（LCR）を測定します。

- **[Lock-in Amplifier](https://youtube-at-vach.github.io/MeasureLab/widgets/lock_in_amplifier/)**
    - ノイズに埋もれた微小信号を検出します。FRA（周波数応答解析）としても利用可能です。

- **[Lock-in Frequency Counter](https://youtube-at-vach.github.io/MeasureLab/widgets/lock_in_frequency_counter/)**
    - 基準信号に対する微小な周波数偏差や位相変動を追跡します。

- **[Loopback Finder](https://youtube-at-vach.github.io/MeasureLab/widgets/loopback_finder/)**
    - オーディオインターフェースのループバック経路を検出します。

- **[Transmission Analyzer (試験的)](https://youtube-at-vach.github.io/MeasureLab/widgets/transmission_analyzer/)**
    - PRBS信号（擬似ランダムノイズ）を用いて、デジタルオーディオのビット完全性（ビットパーフェクトやDSP処理の検出）およびアナログ伝送路のEVMやインパルス応答、遅延、ジッターを総合的に測定する試験的モジュールです。

---

## 📈 時間領域

波形の形状や過渡的な変化を時間軸で観察します。

- **[Oscilloscope](https://youtube-at-vach.github.io/MeasureLab/widgets/oscilloscope/)**
    - 一般的なオシロスコープです。波形そのものを観測します。

- **[Raw Time Series](https://youtube-at-vach.github.io/MeasureLab/widgets/raw_time_series/)**
    - 長い時間の波形を記録し、スクロールして確認できるチャートレコーダーのようなツールです。

- **[Event Detector](https://youtube-at-vach.github.io/MeasureLab/widgets/event_detector/)**
    - 閾値を横切るまれなイベントを連続監視し、発生回数と1分あたりの発生レートを測定します。

- **[Transient Analyzer](https://youtube-at-vach.github.io/MeasureLab/widgets/transient_analyzer/)**
    - インパルス応答などの過渡現象をトリガーして解析します。ウェーブレット変換表示も可能です。

- **[Boxcar Averager](https://youtube-at-vach.github.io/MeasureLab/widgets/boxcar_averager/)**
    - 繰り返し信号を平均化してノイズを除去し、微細な波形を取り出します。

---

## 🎧 空間・音響

ステレオイメージや空間的な音の響きを扱います。

- **[Goniometer](https://youtube-at-vach.github.io/MeasureLab/widgets/goniometer/)**
    - リサージュ図形などでステレオ信号の位相関係（広がり）を表示します。

- **[BNIM Meter](https://youtube-at-vach.github.io/MeasureLab/widgets/bnim_meter/)**
    - Binaural Neural Image Map。聴覚モデルに基づいて音像の定位（ITD/ILD）を可視化します。

- **[HRTF Player](https://youtube-at-vach.github.io/MeasureLab/widgets/hrtf_player/)**
    - 頭部伝達関数 (HRTF/SOFA) を読み込み、畳み込みによる3Dオーディオ再生をシミュレートします。

- **[Stereo Alignment Monitor](https://youtube-at-vach.github.io/MeasureLab/widgets/stereo_alignment_monitor/)**
    - 左右の音量・周波数特性・位相の整合性をリアルタイムで監視し、ステレオアライメントを確認します。

- **[Spatial Binaural Mixer](https://youtube-at-vach.github.io/MeasureLab/widgets/spatial_binaural_mixer/)**
    - 高品質なオフライン・マルチトラック空間オーディオレンダラーです。STEMなどの複数トラックを読み込み、HRTFを用いて独立して3D空間に配置し、リアルタイム処理特有のアーティファクトを回避した最高音質でMIXを書き出します。

---

## 🛠️ ユーティリティ

その他の便利な機能です。

- **[Recorder & Player](https://youtube-at-vach.github.io/MeasureLab/widgets/recorder_player/)**
    - シンプルな録音・再生機能です。
- **[Waveform Loop Player](https://youtube-at-vach.github.io/MeasureLab/widgets/waveform_loop_player/)**
    - オーディオファイルを読み込み、波形を確認しながら任意の区間を選択してループ再生できるツールです。過渡応答の繰り返し観測などに便利です。

- **[Detachable Wrapper](https://youtube-at-vach.github.io/MeasureLab/widgets/detachable_wrapper/)**
    - 任意のウィジェットを別ウィンドウとして切り離すための枠組みです。
- **[計測コンソール（試験的機能）](https://youtube-at-vach.github.io/MeasureLab/widgets/measurement_console/)**
    - 既存の測定ウィジェットを、音声処理を重複させずにドッキング可能なワークスペースへ配置します。
- **[Plot Comparer](https://youtube-at-vach.github.io/MeasureLab/widgets/plot_comparer/)**
    - 異なる測定モジュール（スペクトラムアナライザ、ネットワークアナライザ、オシロスコープなど）から保存・エクスポートした測定データをインポートし、ゲインオフセットや軸シフトなどを調整しながら重ね合わせて詳細に比較できます。
- **[Processor Benchmark](https://youtube-at-vach.github.io/MeasureLab/widgets/processor_benchmark/)**
    - PCのFFTおよび描画パフォーマンスをテストし、リアルタイム処理の限界を検証します。
- **[Settings](https://youtube-at-vach.github.io/MeasureLab/widgets/settings/)**
    - オーディオデバイス設定、言語設定、テーマ変更などを行います。
- **[Log Viewer](https://youtube-at-vach.github.io/MeasureLab/widgets/log_viewer/)**
    - アプリケーションのログ、警告、エラーをリアルタイムで表示し、トラブルシューティングに役立てます。
- **[Welcome](https://youtube-at-vach.github.io/MeasureLab/widgets/welcome/)**
    - 起動画面です。
