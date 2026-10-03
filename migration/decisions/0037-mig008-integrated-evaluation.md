# 0037: MIG-008統合評価と次の方針

2026-10-04、macOS Intel。基準HEAD `edad0838`＋今回の作業差分。
[評価計画](../../guide/RUST_QML_MIGRATION_PLAN.md)の008-A〜Cを現在の対象範囲で完了した。
**次の方針はRust coreの段階導入。現行GUIを使い、Rust/QMLの一括展開は見送る。**
製品への組込み・切替はまだ行っていない。Python境界を含む性能利益も未検証である。

## 008-A: 最小測定フロー

既存runnerのPython/sounddevice信号生成から、明示したBlackHole出力port、
CPAL入力の論理ID/port対応、取得履歴/Timebase、共有FFT、波形/line/heatmap、
ID対応V/FS校正、非同期保存までを一つの実行に接続した。
入力は2ch f32 / 48 kHz / 256 frames、固定port順は`[1,0]`。
この正しさ確認はN=1024 / boxcar、比較は後述のN=4096 / Hannで行った。

不足していた波形は、FFTと同じ履歴区間から不変projectionへ渡す。
原値・チャンネル順・区間・Timebaseを保持し、無効sampleはnullにする。
画素への縮約はmin/maxを保持し、カーソルは原配列を読む。
波形/スペクトルの切替は既存line pane内で行い、FFTを追加実行しない。

代表2ch実入力1実行・3取得世代と、保存f32 4/8ch各1条件が成功した。
通常/Triggerの製品CSV・JSONを再読込し、元値、ID、区間、校正revision、保存来歴を照合した。
保存失敗・復帰、Trigger保持、停止・再開、購読の破棄とQObject再生成・終了も成功。
開始失敗とTrigger releaseは既存の対象Rustテストで確認した。
実入力の各世代でXRUN/error/rejectedは0、queue最大深度は768/512/512 frames、回収は成功した。

レイアウト変更に伴うCXX-Qt全9言語の表示と、製品全言語UIサイズ検証も成功。
波形は表示projectionであり、製品codecに新しい時系列columnを追加していない。
保存resultの区間と、runnerが保持した取得bytesの照合で同一区間を確認する。

## 008-B: 実行と編集の比較

Intel Core i5-5675R / RAM 8 GiB / macOS 14.8.9。
Rust 1.98.1、native Qt 6.11.2 / CXX-Qt 0.10.0、Python PyQt6/Qt 6.11.0。
既存CXX-Qt displayのrelease buildと、現行Spectrum Analyzer/Spectrogramの分離表示Widgetを使った。
offscreen/software、1000×640 px、2view、historyの表示32行、表示目標約30 Hz。
2ch f32 / 48 kHz / 256 frames / N=4096 / Hann、5秒warmup後30秒・各1回、途中1回のJSON保存。
native hop=1024、取得履歴32768 frames。
Pythonはline履歴4096 / heatmap入力履歴8192 framesで、固定hopは未対応。

| 観測値 | 現行Python | CPAL / CXX-Qt |
| --- | --- | --- |
| 測定区間 | 30.017秒 | 30.011秒 |
| CPU時間、測定区間のprocess累計差 | 28.33秒 | 33.95秒 |
| peak RSS、起動/終了を含むprocess全体 | 171.6 MiB | 104.4 MiB |
| 表示更新の観測 | 938回、31.25回/秒 | 321回、10.70回/秒 |
| line / heatmap更新 | 938 / 938 callback | 314 / 314 Canvas paint |
| 最大GUI timer間隔 | 34.3 ms | 104 ms |
| 解析 | 2814 channel FFT呼出し、view別 | 1407共有2ch FFT result、表示通知の省略1049回 |
| 取得品質 | latched XRUN / callback error=0 | XRUN / error / rejected=0、取得gapなし |
| 保存完了の観測 | 6.3 ms、同期trace JSON | 96 ms、非同期全column JSON |
| 停止・終了 | 成功 | 成功、stream/graph/保存sessionを回収 |

native Hannの取得bytesから独立FFTを計算し、既存f32許容差内で一致した。
最大peak差は約`1.81e-10`。保存snapshotの全projectionと、区間`[962560,966656]`、
port別tone振幅も一致した。

比較の能力差を除去するための製品改造は行っていない。
Pythonはlineのf64演算、heatmapのf32/periodic Hann、各viewの最新窓を使う。
nativeはf32/symmetric Hann、同一区間の共有結果を使う。
Python lineの対数軸とnativeの線形軸、plot領域とcontrol、保存column数も異なる。
更新数はcallback/Canvasの観測で、compositor表示や操作応答そのものは未確認。
Pythonには取得gapの区間・世代来歴がなく、表示dropは最終pollの値0のみを記録した。
従って一律の処理速度比や保存速度比には使わない。
現在のnative統合表示はRSSが小さいが、表示目標を満たさずCPU利益も示していない。

| 編集から確認まで、debug・各1回 | 現行Python | native |
| --- | --- | --- |
| core: peak正規化の等価な式変更→対象テスト＋保存2ch f32 boxcar/Hann参照照合 | 4.902秒 | 3.803秒 |
| 表示: 既存labelへの同じ記号追加→画像確認 | 2.480秒 | 3.900秒 |

core編集はPython16テストとRust対象テスト、同じ2fixtureと元許容差を使用。
表示確認はPythonの保存生成入力と既存split Widget、nativeの既存replay/lifecycle/oracleを使った。
検査範囲は同一でなく、人の設計・修正時間も含まないため一般的な開発速度比にはしない。
4つの一時編集はbyte一致で元に戻した。clean/packageは[既存結果](0006-qt-iteration-local-bundles.md)を再利用した。

初回runnerの旧binary、QML root itemの画像取得、画像検査import、窓名と診断JSON化の不備は修正した。
最初の完走比較ではPython Widget生成がheatmap Nを2048へ戻していたため、同条件比較から除外した。
生成後に既存controlで4096を指定し、実値を検査して上表の比較を実施した。
core編集の初回oracle名の誤り、表示編集の入力shape不一致も失敗として保持し、該当sampleだけ再実施した。

## 008-C: 四案の判断

| 案 | 判断 | 理由 |
| --- | --- | --- |
| Rust + Qt Quick/QMLを本格展開 | 見送る | 最小フローは成立したが、この統合表示は約10.7回/秒。CPU時間も増えており、全機能のGUI再実装を正当化できない |
| 接続・描画方式を変更 | 将来の選択肢として保持 | coreの正しさと回収は成立。表示通知省略とGUI timer遅れは描画/adapter経路の調査材料だが、原因の局在や改善をまだ実証していない |
| Rust coreを段階導入 | 次の方針として選択 | 共有解析、不変snapshot、ID/時刻/校正/保存契約を現行GUIと組み合わせる範囲に絞れる。現在のGUI応答性を保ちながら利益と境界コストを検査できる |
| 現行Pythonを継続 | 現行製品とfallbackとして継続 | 表示性能は現在の実装が良好。段階導入で利益を示せなければ、契約・履歴・共有設計の改善だけを取り込む |

次の範囲は現行Spectrum Analyzer一つへのRust FFT/共有resultの接続評価とする。
Python/Rust境界のcopy・寿命・停止・校正付き保存と、同じ現行rendererでの利益を確認する。
41機能の移行、CPALの製品backend化、QML画面の展開、配布は同時に進めない。
今回の評価ではPython bindingを実装しておらず、段階導入の性能利益は今後の判定対象である。
Windows/ARM、clean配布、延期したtap/profile/filter/機器条件は未確認のまま保持する。
長時間試験は現在の計画へ戻さない。

## 記録

最終reportと関連失敗は`.migration-local/evidence/2026-10-04-mig008/`へgzipで保持した。
`saved-final/report.json.gz`、`live-final/report.json.gz`、`languages-final/report.json.gz`、
`runtime-final/report.json.gz`、`edits-final/report.json.gz`が成功の正本。
保存先・command・条件・途中失敗・対応表は同directoryの`index.json`。
実行/編集の元logは`.migration-local/benchmarks/mig008-runtime-v3/`と`mig008-edits-v2/`。
全source/binaryの複製や古いfixtureの再生成はしていない。

方針決定後、Qt/QML・rendererの並列試作と専用runner/CI・SDK・表示生成物を削除した。
本書の測定値・条件は実施時の記録として保持する。
削除した元コードとMIG-008の未コミット差分の復元先は[進捗](../status.md#方針決定後の整理)を参照。
