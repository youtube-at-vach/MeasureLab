# Rust 検証記録の索引

ここには条件付きの実測・数値照合と、当時の失敗・未実施を保存する。記録の成功は現行リビジョンや別OS・機器の再検証を意味しない。現在の完了条件は [PLAN](../PLAN.md)、操作手順は [README](../README.md#検証計測) を参照する。

| 対象 | 記録 |
| --- | --- |
| 初期プロトタイプ・実行分離 | [初期統合](PROTOTYPE_2026-10.md)、[測定コア](CORE_2026-10.md) |
| 入力とScope | [CHルーティング](ROUTING_2026-10.md)、[サンプルレート](SAMPLE_RATE_2026-10.md)、[Scope校正](CALIBRATION_2026-10.md) |
| Spectrum | [振幅・PSD](SPECTRUM_2026-10.md)、[校正](SPECTRUM_CALIBRATION_2026-10.md)、[512k](LARGE_FFT_2026-10.md)、[Live描画性能](SPECTRUM_PERFORMANCE_2026-10.md) |
| 設定・結果・操作 | [設定保存](SETTINGS_2026-10.md)、[JSON書き出し](EXPORT_2026-10.md)、[グラフ操作](CONTROLS_2026-10.md)、[取得と再利用](ACQUISITION_RESULTS_2026-10.md) |
| 段階4の入口 | [Lock-in数値と仮想系](LOCKIN_2026-10.md)、[Lock-in GUI](LOCKIN_GUI_2026-10.md) |

旧手順の説明はGitへ委ねるが、これらの記録は誤差の根拠・既知の失敗・未確認層を失わないため残す。新しい測定は対象リビジョン、環境、条件、基準・許容差、結果、未確認事項を記録し、大量のログと画像はQA成果物へ分離する。
