# Spectrum校正の検証

検証日：2026-10-10。対象は`0c58c5ea`を基点とする`codex/spectrum-calibration`の作業ツリー。段階3dのSpectrum校正を確認する。Scope校正の過去の条件は [Scope校正の検証](CALIBRATION_2026-10.md)、既存の振幅／PSDの定義は [Spectrumの検証](SPECTRUM_2026-10.md) に分ける。

## 定義と環境

CHの不変の校正定義 `y = gain × x(FS) + offset` をSpectrumの選択CHへ対応させる。ゲイン・オフセット・単位・ID・版・参照条件を専用ワーカーと各結果へ固定し、次回用の編集で保持結果を変更しない。生履歴、Scope波形・トリガー、Spectrogram、XYはFSを維持する。

Remove DCなしでは校正した各f64サンプルへ窓を掛ける。Remove DCありでは `gain × (x − mean(x))` をf64で計算し、オフセットを相殺してから窓掛け・任意のf32変換を行う。振幅は単位peak、PSDは単位²/Hz、帯域電力は単位²、RMSは単位を使う。複合単位は全体を括弧で囲んで二乗する。dB基準は1単位peak／1単位²/Hzで、未校正CHは従来のdBFS／FS²/Hzを使う。dBmへの換算は行わない。

EMA・保持・カーソル・帯域積算は校正したf64電力を使う。Spectrumワーカーで受けた非有限サンプルの整数位置を追跡し、履歴の描画用ゼロを正常な測定値にしない。校正値・FFT電力が非有限の場合も窓を無効にして数値を利用不可とし、平均と保持をリセットする。無効窓数と入力欠落・欠落による無効窓を別に数え、次の有効な完全窓から回復する。

macOS 14.8.9（23J631）、x86_64、Rust/Cargo 1.99、Metal / AMD Radeon R9 M290X。入力は合成f64フレームと内部デモで、物理基準から校正係数を得た試験ではない。画面・ライフサイクルQAは`qa`付きdevビルド、GPU読み戻しは通常のreleaseビルドを使った。

## 数値とワーカー

* 1,024／65,536／524,288点、Rectangular／Hann／Blackman-Harris、f64／f32、振幅／PSD、DC除去あり／なしを照合した。DC、ビン間正弦波、別ビンの正弦波、Nyquist、単発スパイクを含む入力へ−4 V/FS・オフセット0.75 Vを適用。独立した全長複素FFTを基準に全ビンを比較した。絶対＋相対許容差はf64で `1e−13 + 2e−12 × 期待値`、f32で `1e−8 + 5e−6 × 期待値`。全帯域PSD積算は校正した時間領域の窓付き平均二乗と照合し、絶対許容差はf64で2e−12 V²、f32で2e−6 V²。
* DCとNyquistを2倍せず、負のゲインとオフセットを反映することを確認した。Hannでは1 Vの校正DCがビン1へ広がることも確認し、FFT後のゲイン倍率だけで校正を代用していない。DC除去後はその成分が消える。
* 1e6 FSのDC上の1e−3 FS peak正弦波へ−2 V/FS・オフセット1e200 Vを設定し、DC除去ありの振幅2e−3 Vをf64／f32で絶対許容差3e−10 V以内で照合した。物理オフセットを先に加算してACを消す経路を使わない。
* EMA α = 1/4で振幅2 V→1 Vを処理し、平均二乗3.25 V²と保持4 V²を確認した。新しい校正への切り替えで平均・保持をリセットし、既に配信した結果の版・値・単位は変更しない。Clear holdは保持中の校正した現在値へ戻す。
* 1,024／524,288点、Continuous／Live／Latestの各モードで選択CH 16の校正版7を結果へ対応させ、全帯域電力0.75 V²を照合した。12サンプルの欠落後は新しい完全窓の0.375 V²から平均・保持を再開し、Stopによる同一窓の再平均を行わない。
* 非有限の生サンプル、校正オーバーフロー、f64電力のオーバーフロー、f32変換のオーバーフローを無効とした。Continuousでは1つの非有限サンプルを含む4つの重複窓を無効として数え、入力欠落0のまま次の完全窓から回復する。正常な0へ置き換えたPSDを報告しない。
* 16ch取得キュー→共通測定ワーカー→独立SpectrumワーカーでCH 16の4 V/FS・オフセット0.5 Vを照合した。Scopeと同じ定義を保持し、Stop後の次回用新版は既存結果を変更しない。再開で−8 V/FS・オフセット−1 VのPSD全帯域3 V²を確認した。未校正CH 8へ変更するとFS²/Hzへ戻り、16ch→2chでCH 16の校正を別CHへ流用しない。

## GPU・UI

通常releaseの`--gpu-smoke`は成功。Scope・Spectrum・Spectrogram・XY、512k f64の実ビンピーク、保持中の転送省略、Spectrogramの折り返し・欠落・Nyquistの読み戻しを確認した。

16chの共通撮影用履歴と`MEASURELAB_UI_SMOKE_CALIBRATION=1`を使い、通常幅の振幅表示と`--compact`のPSD表示を撮影・確認した。CH 16の0.375 FS peakへ4 V/FS・オフセット0.5 Vを適用し、Scope数値はV、Scope波形軸・未校正CH 8・Spectrogram・XYはFSを維持する。SpectrumのDC除去あり・Hann・8,192点では、振幅の最大ビン2.89 dB re 1 V peak、PSD最大ビン−9.55 dB re 1 V²/Hz、全帯域1.125 V²／RMS 1.06066 Vを表示した。校正ID・版と各単位の読み取りを確認した。画像は`dist/spectrum-calibration-qa/`へ保存した。

通常VSyncの初回`--ui-smoke`は`UI screenshot was not received`で失敗した。`--low-latency`を追加した再実行と狭幅の撮影は成功。通常VSyncでの静止画撮影は再確認しておらず、低遅延での成功を通常撮影の成功とは扱わない。

通常VSyncの内部デモ・ライフサイクルQA（計測5秒＋起動待ち2秒）は成功。Stop後の次回用校正編集で保持中のScope／Spectrumの値・条件を変えず、再開後に同じCH校正をSpectrumへ適用した。非表示・再表示、遅着除外、入力切り替え、既存のカーソル・保持動作も確認した。取得／Spectrum入力／STFT入力／STFT結果の欠落は0、Spectrumの欠落窓・観察の遅れも0。停止中は434.7 msの再描画なし区間を確認した。

この状態変更を含むdev QAではUI間隔p95 17.220 ms、eframe処理p95 3.050 ms。通常の長時間性能基準との比較や、releaseの性能保証には使わない。ログ・RSSサンプルは`dist/stage2-qa/spectrum-calibration-lifecycle*`へ保存した。

## 静的検証

全ターゲット・全機能の109コアテストと起動オプションの1テスト、4つのベンチマーク実行は成功。GUIなしの106テストも成功。`cargo fmt --check`、全ターゲット・全機能のClippy、通常releaseデスクトップビルドと`qa`付きdevビルド、全Markdownのlint、Ruff checkとformat check、`git diff --check`も成功した。テスト出力は`dist/spectrum-calibration-tests.log`と`dist/spectrum-calibration-headless.log`へ保存した。

## 未確認・未実装の境界

* 新しい校正を使う外部仮想I/O・物理入力の照合、物理基準・ADCの校正精度、実Fs。
* この作業ツリーでの600秒の連続計測、RSSの推移、GPU実行時間、取得から表示までの遅延、Windows／Linux実機。
* 設定・校正の永続化、安全な復元、結果と条件の書き出し。次の3dの作業として残す。
* Scope波形・トリガー、Spectrogram、XYの物理単位化とdBm。現在のFSの範囲を維持する。
* 汎用Software LoopbackとLock-in。合成入力・内部デモの成功を経路全体や物理精度の保証と扱わない。
