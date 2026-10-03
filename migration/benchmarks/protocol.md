# MIG-008の短い比較条件 v0.2

更新: 2026-10-04。[評価計画](../../guide/RUST_QML_MIGRATION_PLAN.md)に従う。
**統合フローと同条件Pythonの実行性能比較は未実施。**
長時間試験、10分×3回、全ch/全backend/全Qtの直積、clean build/packageの反復を削除した。

## 固定条件

現在のmacOS Intel環境で同じ2ch入力・設定を使う。
48 kHz、f32、I/O block=256、FFT N=4096/hop=1024、Hann、
lineとheatmapの2view、表示目標30 Hzを基本にする。
history容量、保存タイミング、画面サイズ、backendとQt接続方式を記録する。
現行Pythonで未対応の能力は未対応と記録し、比較のための全面改造を追加しない。

実行性能はrelease相当、編集反復は通常のdebug条件。
OS/CPU、commitまたはdirty差分、toolchain/Qt/依存lock、コマンドをreportへ残す。
測定中は他のbuild/GUI試験を止める。

## 測定区間・回数

| 経路 | 最小比較 |
| --- | --- |
| 実行性能 | 各案5秒warmup後、30秒・1回。2view表示と途中1回の保存を同じ条件で行う |
| core編集 | 同じ処理の小変更から対象テスト・参照比較の結果まで各1回 |
| 表示編集 | 同等のlabel/layout変更から表示確認まで各1回 |
| build/package | 既存[Qt反復結果](../decisions/0006-qt-iteration-local-bundles.md)と[core編集結果](../decisions/0007-pure-fft-candidate.md)を再利用。clean環境の新規試験は不要 |

CPU秒、peak RSS、表示更新率/応答時間、取得gap、FFT共有count、停止/終了結果を記録する。
既存の診断から取得できる値を使う。計測のために新しい監視基盤や全frameのarchiveを作らない。
取得できない値は未確認と記し、短い試験から長時間安定性やRT保証を推定しない。
追加試行は異常・結果の食い違い・比較条件の不一致を解消する場合だけ行う。

## 判定

数値・ChannelId・区間・校正・保存の一致は[数値契約](../contracts/numerics.md)と既存fixtureで判断する。
許容差や期待値を緩めない。4/8chは同じ統合coreの短い正しさ回帰に限定する。

性能は同条件Pythonとの実測差、編集から確認までの待ち時間、
既知の描画制約・保守負担をMIG-008の四案へ渡す。
一律の性能比率や全OS配布を完了条件にせず、測定値と選択理由を残す。
短時間では判断できない事項は未確認のまま添える。

## 保存する結果

既存runnerのreportとraw logを`.migration-local/benchmarks/`へ保存する。
条件、実測値、終了コード、失敗・未確認点と再実行コマンドを記録し、
[進捗](../status.md)と008-Cの判断にはその要点とreportの所在だけを残す。
新しい専用手順書、同じ結果の複数文書への転記、全source/binaryの複製と再hash監査は不要。
既存のreport schemaや固定fixtureのhash検査は維持する。
