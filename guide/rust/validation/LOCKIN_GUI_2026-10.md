# Lock-in GUIの条件付き確認

対象：2026-10-11、`7324937a`上のGUI作業差分。macOS 14.8.9、Rust 1.99、Metal／AMD Radeon R9 M290X。測定処理の定義と精度条件は [Lock-inの検証](LOCKIN_2026-10.md) を参照する。GUI追加によって実機のREF・タイミング確認を完了としない。

## 参照と実装範囲

ユーザー提供のNF LI5660／LI5655／LI5650／LI5645のパネル画像、`origin/archive/python-v0.9.1`の`src/gui/widgets/lock_in_amplifier.py`を参照した。旧Python環境は実行していない。[SRS SR865A](https://thinksrs.com/products/sr865a.html) の複数数値表示と直接操作、[Zurich LabOne Numeric](https://www.zhinst.com/en/instruments/labone/how-labOne-elevates-your-instrument-experience/) の極座標／直交座標・範囲指標を参考にした。

Rustの既存の基本波・同期入力REF・二段EMAへ接続し、R／θ・X／Y・4値の独立画面、表示専用バー、REFの有効性・整定・保持、校正単位、REF周波数・Gain、取得時の条件と次回Start用設定の区別を実装する。ハードウェア入力感度、出力発振器、可変フィルター次数、広帯域PLLは追加しない。

## 確認条件と結果

通常ビルドにも存在するSoftware LoopbackをQAアプリから開始し、有限終端でStopしてワーカーの結果を受信する。解析関数へ直接渡したダミー数値ではない。

* 公称Fs 48 kHz、REF CH 1、Signal CH 2、750 Hz、REF 0.125 FS peak、DUT gain 0.5・位相30°、積分窓4,096サンプル、既定τ 20 ms。
* 通常幅1440×860と狭幅1040×780の論理サイズ、2倍の画面撮影。Lock-in単独・Scope併用を確認する。
* 整定後のRと0.0625 FS peakとの差<1e-8、位相と30°との差<1e-6°をアプリ状態で照合する。
* 画面切り替えと前の表示の復元で、保持したf64値・解析設定が変わらないことを照合する。Lock-in単独のWorkspaceと座標表示をJSONへ往復する。

| QAモード | 結果 |
| --- | --- |
| `polar` | 通常幅のR／θ・単位・バー・REF／Gain・条件表示を撮影し、重なりがないことを確認 |
| `cartesian` | 狭幅のX／Yと符号付きバーを撮影して確認 |
| `all` | 狭幅の4値表示・単位・バーを撮影し、数値が収まることを確認 |
| `pair` | 狭幅でScopeと上下併用して撮影。全内容は縦スクロールで扱い、下部の操作／詳細は初期表示範囲外 |
| `ref-loss` | REFを無効にした共通入力でReferenceLost、X／位相の破棄を照合。「—」とマーカーのないバーを撮影して確認 |
| `settling` | τ 1 s・10τ未満の有限入力でSettlingを照合し、整定前の値・進捗・HOLDを撮影して確認 |
| `held-edit` | Stop後のヒント750→1,000 Hz、τ 20→100 msの編集で保持値が変わらないことを照合。取得条件とNext Startの区別を撮影して確認 |
| `live-edit` | 取得中のτ 20→30 msをワーカーへ反映し、条件更新・再整定・理論値一致を照合。最終差分の画像読み戻しはタイムアウト |
| `source-change` | Software Loopback→Audio inputで旧X／位相・処理窓数を破棄することを照合。最終差分の画像読み戻しはタイムアウト |

初回7モードの画像はローカルの`dist/lockin-gui-qa/`に保存した。その後の入力ソース変更時の無効化・未取得表示・Lock-in単独時のカーソル操作非表示を含む最終差分では、状態の照合は成功したが、画像読み戻しが10秒でタイムアウトし、`UI screenshot was not received`で終了した。`polar`の再撮影もVSync無効で同じ結果になった。最終差分の再撮影成功とは扱わない。実行手順は [READMEのQA手順](../README.md#検証計測) を参照する。

最終差分で`cargo fmt --all -- --check`、全ターゲット・全機能のClippy（警告をエラー化）、全ターゲット・全機能のテスト（単体143件・起動1件・ベンチ実行）、通常のdesktop releaseビルドを通過した。Ruffのcheck／format確認と変更したMarkdownのlintも通過した。画面の読み戻し成功と数値・状態の照合は別の結果として扱う。

## 未確認事項

実機と外部仮想I/OのLock-in精度、長時間安定性、Windows／Linux実機、最終差分のGPU画面再撮影は未確認。バーの自動スケールと数値の桁数は表示のためのもので、ADCの精度・入力感度・物理単位の校正精度を保証しない。狭幅でScopeと4値を併用する場合は、表示全体を縦スクロールする。
