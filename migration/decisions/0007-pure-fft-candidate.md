# 0007: Pure Rust FFTの参照比較結果

2026-09-30、MIG-006-A。2026-10-04に結果・数値境界だけへ整理。
基準HEAD `e0b992ce36b7eec562059bc31891378f37d01814`。
RealFFT 3.5.0 / RustFFT 6.4.1、Rust 1.98.1、Intel/debug、build並列4、FFT 1 thread。
採用・release性能・同条件Python相対性能の結果ではない。

## 数値と所有権

[実装](../../native/dsp-core/src/lib.rs)は元fixtureのlittle-endian/frame-major bytesを使う。
forwardは負符号の無正規化DFT、比較は`X/N`、inverseは`1/N`。
DC/偶数Nyquistと奇数最終binを区別し、FS peak/coherent bin RMS/PSD/ASDを明示する。
窓・正規化はf64。f32の窓乗算/FFT/inverseはf32で、f64 FFTへの昇格はしない。
plan/scratchはAnalyzerが所有し、結果はowned配列。callbackへ演算やallocationを移さない。

24保存ケースは開始時の[数値許容差](../contracts/numerics.md)内で理論/現行参照へ合格した。
2/4/8ch、f32/f64、DC/Nyquist/impulse/無音、4095/24000/48000/4194304、boxcar/Hannを対象。
f32はN=4096の2/4/8chで、拡張/endpoint全構成を保証しない。
最大正規化FFT差はf64約1.33e-13、f32約8.35e-9。inverse最大差は約5.83e-16 / 1.04e-7。
phase最大差は約1.84e-9 / 5.26e-8 rad。
現行SpectrumのDC/Nyquist表示との約+6.0206 dB peak、約+3.0103 dB RMS/ASD差は既知差として保持。

## core編集の結果

同じ係数分岐変更からRustテストと24参照比較まで、5回とも成功。
26.093 / 24.544 / 24.770 / 24.493 / 24.453秒。
中央値24.544秒、min/max 24.453 / 26.093秒、標準偏差0.621秒。
Python同等修正とGUI波及は未確認。MIG-008ではこれを既存の参考値として利用する。
reportは`migration/benchmarks/results/2026-09-30-006-a-intel.json`。
再実行コードは[runner](../../scripts/migration_fft_candidate.py)。
