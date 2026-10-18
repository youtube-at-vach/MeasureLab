# MeasureLab Rust プロトタイプ

**正確な測定を、無料で、すべての人へ。** MeasureLabは、PCとオーディオ入力を使って信号を観察・測定するアプリです。Rust版はScopeとSpectrumを中心に再構築しているプロトタイプで、現在はソースからビルドして試せます。

バイナリ配布は準備中で、まだ公開していません。[配布版の導入](install.md) に配布対象・権限・署名状態をまとめています。

## 現在使える機能

| 機能 | 範囲 |
| --- | --- |
| 入力 | CPALによる1〜16chの同期入力。取得後の測定はf64、公称サンプルレートを使用 |
| Scope | 任意の4ch、独立した表示・縦軸、Auto／Normal／Single、Autoset、生サンプルのRMS・Peak・P-P、カーソル |
| Spectrum | 最大4ch重ね表示、1,024〜524,288点、振幅／PSD／ESD、帯域電力・RMS／窓エネルギー、平均、ピーク保持 |
| Spectrogram／XY | 時間周波数表示と同期2chのXY表示 |
| 保存と比較 | CH校正と版付き設定の保存・復元、保持したScope／Spectrum結果のJSON・CSV・PNG、参照JSONとの比較 |
| Software Loopback | 機器なしで既知のゲイン・位相・遅延・雑音を共通入力から評価 |
| Generator（実験段階） | 最大16カードを追加・削除・複製・並べ替え、Sine／Square／Triangle／Noiseと独立したOUTを選択。内部2ch／CPAL最大16ch、f64生成・ライブ数値編集・OFF復元。動的カードと多波形の実機・手動受け入れは未確認 |
| Lock-in（実験段階） | 同期REFと応答の基本波を測定。X/Y、R/θ、Gain、整定・REF状態、条件付きJSON／CSV保存と参照比較 |
| 同期2ch比較（実験段階） | 任意REF／SIGの自己・クロスPSD、H1ゲイン・位相、コヒーレンス、位相遅延・条件付き傾斜、停止・JSON／CSV・参照比較 |

取得・測定・描画は別の実行責務を持ち、表示を閉じても解析・平均を続けます。停止した結果は取得時の入力・設定・校正・欠落と対応付けます。

## 対応範囲と制限

測定の検証記録はmacOSの限定条件が中心です。Windows VMはGNU／dev-fast起動、Linux AppImageはX11の一条件で起動・実GPU読み戻しを確認しています。これらは現在のrelease配布物での実入出力・保存復元の受け入れではありません。Windows／LinuxもCIのビルド・テスト対象ですが、CIの成功は各OSのGPU・音声デバイスの実機確認を意味しません。機器・入力レンジ・校正に依存する精度や、設定上限768 kHzでの実動作を保証するものではありません。

macOSのBlackHoleとUAC-232物理ループでは、Lock-inの入力REF・独立数値照合・条件付き保存、UAC-232のGUI保存・再起動・再測定を確認しています。過去のGUIなし600秒記録と、今回の通常GUI約270秒の観測は別の条件です。未校正FS・公称Fsでの限定条件で、物理校正精度、レベル依存位相、絶対遅延や他OSの実機保証を含みません。通常Generatorの実出力は段階4.5の条件付き評価中です。外部入力結果へ出力の観測履歴・失敗を保存しますが、入力窓との対応は未校正で、参照との数値差を表示しません。出力校正・入出力サンプル時計の対応、THD／FRF／IR、VST3、実サンプルレート校正、自由配置、多言語UIは未実装です。旧版の全機能を移植した版ではありません。Scopeの波形軸・トリガーはFSで、校正した数値読み出しの物理単位と区別してください。

Spectrogramは撮影操作が重なった高負荷評価でGUIの長い停止、STFT転送・Generator内部入力の欠落を観測しました。UAC-232の192 kHz起動時にもSTFT欠落があります。原因の切り分け・耐性改善、通常GUIの包括的手動操作・実モニター間DPIは受け入れを残します。

## 始める・報告する

まず [クイックスタート](quickstart.md) のSoftware Loopbackで取得・停止・保存を試してください。不具合は [GitHub Issues](https://github.com/youtube-at-vach/MeasureLab/issues) へ、Rust版であること、コミット、OS・GPU・入力機器、Fs・CH・FFT設定、再現手順を添えて報告できます。

開発情報・詳細な操作・検証方法は [リポジトリ](https://github.com/youtube-at-vach/MeasureLab) の`guide/rust/`にあります。Rust版は`main`で開発しています。

## Python最終版を使う場合

[Python v0.9.1 のダウンロード](https://youtube-at-vach.github.io/MeasureLab/download/) と [保存版マニュアル](https://youtube-at-vach.github.io/MeasureLab/) は引き続き利用できます。旧マニュアルの既存URLは維持します。ソースは [v0.9.1タグ](https://github.com/youtube-at-vach/MeasureLab/tree/v0.9.1) に保存しています。
