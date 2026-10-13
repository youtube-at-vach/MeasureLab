# Rust 検証記録の索引

ここには条件付きの実測・数値照合と、当時の失敗・未実施を保存する。記録の成功は現行リビジョンや別OS・機器の再検証を意味しない。現在の完了条件は [PLAN](../PLAN.md)、操作手順は [README](../README.md#検証計測) を参照する。

| 対象 | 記録 |
| --- | --- |
| 初期プロトタイプ・実行分離 | [初期統合](PROTOTYPE_2026-10.md)、[測定コア](CORE_2026-10.md) |
| 入力とScope | [CHルーティング](ROUTING_2026-10.md)、[サンプルレート](SAMPLE_RATE_2026-10.md)、[Scope校正](CALIBRATION_2026-10.md)、[可変コールバックと有限終端](CAPTURE_BOUNDARIES_2026-10.md) |
| Spectrum | [振幅・PSD](SPECTRUM_2026-10.md)、[校正](SPECTRUM_CALIBRATION_2026-10.md)、[512k](LARGE_FFT_2026-10.md)、[Live描画性能](SPECTRUM_PERFORMANCE_2026-10.md) |
| 設定・結果・操作 | [設定保存](SETTINGS_2026-10.md)、[JSON書き出し](EXPORT_2026-10.md)、[グラフ操作](CONTROLS_2026-10.md)、[取得と再利用](ACQUISITION_RESULTS_2026-10.md) |
| 段階4の入口 | [Lock-in数値と仮想系](LOCKIN_2026-10.md)、[Lock-in GUI](LOCKIN_GUI_2026-10.md)、[Lock-in結果再利用](LOCKIN_RESULTS_2026-10.md) |
| 段階4bの外部仮想I/O | [BlackHole Lock-in](BLACKHOLE_LOCKIN_2026-10.md) |
| 段階4bの物理ループ | [UAC-232 Lock-in](UAC232_LOCKIN_2026-10.md) |
| 段階4cの統合計測 | [Spectrumの窓終端とCPU遅延](SPECTRUM_LATENCY_2026-10.md) |
| 段階4のmacOS受け入れ | [GUI再利用・起動境界・統合評価](STAGE4_MACOS_2026-10.md) |
| 段階4.5のGenerator | [内部接続・保存条件](GENERATOR_INTERNAL_2026-10.md)、[CPAL実出力・PCM・通常GUI](GENERATOR_DEVICE_2026-10.md)、[コールバック負荷・通知監査](GENERATOR_CALLBACK_2026-10.md)、[実USB切断・OFF復元](GENERATOR_DISCONNECT_2026-10.md) |
| 段階5の同期2ch比較 | [数値・境界・GUI・内部／外部の同期比較](COMPARISON_2026-10.md) |

旧手順の説明はGitへ委ねるが、これらの記録は誤差の根拠・既知の失敗・未確認層を失わないため残す。新しい測定は対象リビジョン、環境、条件、基準・許容差、結果、未確認事項を記録し、大量のログと画像はQA成果物へ分離する。
