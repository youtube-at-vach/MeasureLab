# 0006: Qt接続のIntel反復・bundle比較結果

2026-09-30、MIG-004-B。2026-10-04に結果だけへ整理。
macOS 14.8.9 / Core i5-5675R / RAM 8 GiB / 並列4、Rust 1.98.1、Qt 6.11.2、
CXX-Qt 0.10.0 / Qt Bridge 0.3.0、debug、offscreen/software/Basic、英語560×360 px。
基準HEADは`80435eef`。現在の工程は[評価計画](../../guide/RUST_QML_MIGRATION_PLAN.md)に従う。

## 測定結果

| 経路 | CXX-Qt 中央値、min〜max | Qt Bridge 中央値、min〜max | 判定 |
| --- | --- | --- | --- |
| clean + core/UI検査 | 221.795秒、221.259〜224.705秒 | 258.154秒、254.057〜258.282秒 | 両方式とも600秒以内 |
| no-op + core/UI検査 | 2.470秒、2.440〜2.513秒 | 2.646秒、2.578〜2.894秒 | 回数・状態/寿命検査合格。専用の時間予算なし |
| QML編集 + UI検査 | 2.063秒、2.035〜2.093秒 | 2.241秒、2.215〜2.341秒 | 両方式とも10秒以内 |
| package + 展開/UI検査 | 56.903秒、56.807〜75.745秒 | 59.842秒、58.845〜101.453秒 | 両方式とも900秒以内。クリーンOSは未確認 |

各経路の主時間は次の全sampleを測定順に保存する（秒、小数3桁に丸め、warmupを除く）。

| 経路 | CXX-Qt 全sample | Qt Bridge 全sample |
| --- | --- | --- |
| clean | 221.795 / 224.705 / 221.259 | 258.154 / 258.282 / 254.057 |
| no-op | 2.513 / 2.440 / 2.478 / 2.470 / 2.458 | 2.658 / 2.646 / 2.578 / 2.619 / 2.894 |
| QML編集 | 2.093 / 2.086 / 2.063 / 2.063 / 2.035 | 2.234 / 2.215 / 2.261 / 2.241 / 2.341 |
| package | 56.807 / 56.903 / 75.745 | 59.842 / 58.845 / 101.453 |

QML変更はlabelだけで、外部QML読込みのためcodegen/relinkは発生しなかった。
clean各3回、no-op各warmup1回+5回、QML各5回、package各3回。32 sampleとwarmup2回が成功。
現行Python全体のoffline起動中央値は7.100秒、6.861〜8.815秒。workloadが違うため速度比にしない。

bundleはad-hoc署名、展開後起動・寿命と開発SDKからの分離まで確認。
署名配布、clean OS、Gatekeeper、手動操作、統合graph/実音声の保証ではない。
Linux CIの旧失敗はSDKのICU不足。仕様へICU archiveを追加したがremote再実行は未確認。

reportは`migration/benchmarks/results/2026-09-30-004-b-intel.json`と同名の圧縮log directory。
再実行コードは[runner](../../scripts/migration_qt_iteration.py)。
MIG-008では既存値を利用し、clean/packageの追加反復や別OS検証を行わない。
