# MeasureLab Rust プロトタイプ

**正確な測定を、無料で、すべての人へ。** MeasureLabは、PCとオーディオ入力を使って信号を観察・測定するアプリです。Rust版はScopeとSpectrumを中心に再構築しているプロトタイプで、現在はソースからビルドして試せます。

## 現在使える機能

| 機能 | 範囲 |
| --- | --- |
| 入力 | CPALによる1〜16chの同期入力。取得後の測定はf64、公称サンプルレートを使用 |
| Scope | 任意の2ch、Auto／Normal／Single、Autoset、生サンプルのRMS・Peak・P-P、カーソル |
| Spectrum | 1,024〜524,288点、振幅／PSD、帯域電力・RMS、平均、ピーク保持 |
| Spectrogram／XY | 時間周波数表示と同期2chのXY表示 |
| 保存と比較 | CH校正と版付き設定の保存・復元、保持したScope／Spectrum結果のJSON・CSV・PNG、参照JSONとの比較 |
| Software Loopback | 機器なしで既知のゲイン・位相・遅延・雑音を共通入力から評価 |
| Lock-in（実験段階） | 同期REFと応答の基本波を測定。X/Y、R/θ、Gain、整定・REF状態、条件付きJSON／CSV保存と参照比較 |

取得・測定・描画は別の実行責務を持ち、表示を閉じても解析・平均を続けます。停止した結果は取得時の入力・設定・校正・欠落と対応付けます。

## 対応範囲と制限

品質評価はmacOSに集中し、Windows／Linuxの実機評価は今後のタスクへ送っています。macOSでの条件付き検証記録があります。Windows／LinuxもCIのビルド・テスト対象ですが、CIの成功は各OSのGPU・音声デバイスの実機確認を意味しません。機器・入力レンジ・校正に依存する精度や、設定上限768 kHzでの実動作を保証するものではありません。

macOSのBlackHoleとUAC-232物理ループでは、Lock-inの入力REF・独立数値照合・条件付き保存、UAC-232のGUI保存・再起動・再測定を確認しています。過去のGUIなし600秒記録と、今回の通常GUI約270秒の観測は別の条件です。未校正FS・公称Fsでの限定条件で、物理校正精度、レベル依存位相、絶対遅延や他OSの実機保証を含みません。物理オーディオ出力、THD／FRF／IR、VST3、実サンプルレート校正、自由配置、多言語UIは未実装です。旧版の全機能を移植した版ではありません。Scopeの波形軸・トリガーはFSで、校正した数値読み出しの物理単位と区別してください。

## 始める・報告する

まず [クイックスタート](quickstart.md) のSoftware Loopbackで取得・停止・保存を試してください。不具合は [GitHub Issues](https://github.com/youtube-at-vach/MeasureLab/issues) へ、Rust版であること、コミット、OS・GPU・入力機器、Fs・CH・FFT設定、再現手順を添えて報告できます。

開発情報・詳細な操作・検証記録は [リポジトリ](https://github.com/youtube-at-vach/MeasureLab) の`guide/rust/`にあります。Rustの統合先はmainへの切り替えまでは`rewrite/rust`です。

## Python最終版を使う場合

[Python v0.9.1 のダウンロード](https://youtube-at-vach.github.io/MeasureLab/download/) と [保存版マニュアル](https://youtube-at-vach.github.io/MeasureLab/) は引き続き利用できます。旧マニュアルの既存URLは維持します。ソースは [v0.9.1タグ](https://github.com/youtube-at-vach/MeasureLab/tree/v0.9.1) に保存しています。
