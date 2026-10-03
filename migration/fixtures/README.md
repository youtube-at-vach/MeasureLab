# 固定FFT参照データ

MeasureLab `9fd79958f6a8bbae6808813d3704617612e6d26c`を基準にMIG-003で保存した入力・期待値。
[数値基準](../contracts/numerics.md)に対するRust coreの回帰検証へ使う。
生成runner、拡張FFT・filter・route・校正の旧評価fixtureは終了した移行評価とともに削除した。

| 保存先 | 条件 |
| --- | --- |
| [fft-v1](fft-v1/manifest.json) | 14条件。2ch f32/f64、boxcar／symmetric Hann、DC、Nyquist、impulse、無音、tone、奇数最終bin |
| [core-v1](core-v1/manifest.json) | 4条件。4/8ch、f32/f64、N=4096、boxcar |

`input.bin`は元のlittle-endian、frame-major bytes。
`theory.*`は独立理論、`current.*`は当時のPythonの契約正規化adapterによる値。
f32入力・窓乗算・FFT・inverseをf32に保ち、窓構成・正規化・reductionはf64で比較する。
DC／偶数Nyquistのone-sided係数は1、その他・奇数最終binは2。
現行Spectrumのendpoint表示には約+6.0206 dB peak、約+3.0103 dB RMS/ASDの既知差がある。

[直接比較テスト](../../native/dsp-core/tests/fixtures.rs)は両参照とのFFT／逆変換／振幅／RMS／PSD、
積分power、位相、dB、ChannelId順序を元の許容差で確認する。
配列のhash・shape・精度を検査し、期待値を再生成しない。
manifestは読みやすい短い表記へ整形し、core-v1の削除済みscenario／export参照を除いた。
保持した18条件のspec・metadata・配列bytes／hash・許容差は元のまま。
manifest内の生成環境・source／generator hashは当時の来歴であり、現行buildの前提ではない。

検証コマンドとtoolchainは[native手順](../../native/README.md#buildと検証)を参照する。
旧生成コード・元のmanifestと詳細記録はGit履歴`75581059`から取得できる。
