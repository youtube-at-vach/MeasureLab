# 実行性能・開発反復速度の比較条件 v0.1

MIG-002、2026-09-29。ここには測定手順と初期予算を置く。**新旧の実行性能測定はまだ行っていない。**
MIG-001のスモーク時間は比較結果に含めない。Processor Benchmarkの製品機能移行も別に扱う。
MIG-004-Bで候補2方式のIntel開発反復とローカルbundleを測定した。
[結果と範囲](../decisions/0006-qt-iteration-local-bundles.md)を参照。実行性能・他OS・同等Python編集の比較は未確認。

## 固定条件

同じ開発機、AC01の入力bytes、rate=48 kHz、I/O block=256、FFT N=4096/hop=1024、
boxcar/Hann、2chを基本とし、4/8chと非2冪/極大FFTは別行で測る。
2view（lineとheatmap）、表示30 Hz、history容量、保存頻度を固定し、実際の画面pixel数とscaleも残す。
表示しないheadless演算とGUI込みを別測定する。現行の計算共有/N-channel未対応は「未対応」と記録し、
現行を改造した比較はadapter版を明記する。アーキテクチャの差を言語だけの効果としない。

OS/CPU/メモリ/電源状態、各commitとdirty差分hash、toolchain/Qt/bridge/backend/依存lock、
thread数/CPU並列数（初期4、両案同じ値）、debug/release、コマンド、環境変数、cache条件を保存する。
実行性能はrelease相当、開発反復は普段のdebug/検証条件とし、混ぜない。
PythonのFFTW plan/wisdom、OS page cache、Rust target、QML cacheを区別する。

## 測定区間・回数

| 経路 | 開始 → 終了 | 回数・cache |
| --- | --- | --- |
| clean build | 依存取得済み、project build生成物を除いた状態 → 起動してready | 3回。依存取得/SDK導入時間は別欄。Pythonも新processでimport/readyを含める |
| incremental/no-op | 変更なしでbuild/検証コマンド実行 → readyと対象テスト完了 | warmup1回＋5回 |
| core 1ファイル編集 | 固定した小変更patch適用済みからコマンド開始 → 対象テストと参照比較完了 | patch/hash/対象試験を同等にし5回。各回baseへ戻して同じ変更。GUI波及も含める |
| QML/表示のみ編集 | 同等の表示label/layout変更からコマンド開始 → readyと対象UI検証完了 | 5回。reload/codegen/resource/relinkの内訳を記録 |
| package | packaging開始 → clean環境で起動/ready | OS別3回。署名・notarization・download等の外部待ちを別記録 |
| 実行性能 | 30秒warmup後 → 10分連続処理 | 3回。準備/FFT planとsteady-stateを別計測 |

wall timeは単調clockで測る。各runのraw値、中央値、min/max、ばらつき、終了コードを保存する。
実行性能はcallback/解析/表示遅延のp50/p95/p99/max、process treeのCPU秒とpeak RSS、
queue容量/最大深さ、data gap、表示の更新省略、FFT評価countを記録する。
RSS成長はwarmup後の時系列で判定する。GPU使用量など取得できない値はunknownと記す。
AIによる修正ではpatch作成に要した時間、compiler/test失敗数、修正回数も別列にし、待ち時間へ混ぜない。

## 初期予算と判定

以下は実測から得た限界ではなく、P1を評価するための初期予算。
数値/状態の受け入れ条件は必須。性能の超過は改善・方式変更の判断材料で、直ちに採用/不採用を決めない。
超過したまま「予算内」と記録しない。変更が必要なら根拠・変更前後の値を決定記録へ残す。

| 項目 | 初期予算・用途 |
| --- | --- |
| callback | block時間5.333 msに対しp99≤50%、max<100%。RT経路の禁止処理がないことも別確認 |
| 連続取得 | 10分の仮想2/4/8chで欠落0。意図的overflow試験ではgapの位置/数が厳密一致 |
| 表示 | 結果が利用可能になってから描画までp95≤100 ms、stop要求から状態通知までp95≤200 ms。FFT窓取得時間は別 |
| CPU/RSS | 同等の2ch workloadでCPU秒≤現行の1.25倍、peak RSS≤2倍。history満杯後の後半5分のRSS増加≤5 MiB |
| core編集/検証 | 中央値≤max(30秒, 現行同等修正の2倍)。共有契約と数値比較を省略しない |
| 表示編集/検証 | 中央値≤max(10秒, 現行同等修正の2倍)。自動で測れるreadyに加え目視結果を別記録 |
| clean ready | 依存取得済みの中央値≤10分。同条件のPython起動も併記 |
| package ready | 外部待ちを除く中央値≤15分。対象OSでの展開・起動まで含む |

短い試行のp99だけでRT性を保証しない。負荷・再接続・終了経路、コールバック内のallocation/lock/解放も調べる。
測定のために重いlogや毎frame file出力をcallbackへ追加しない。
同条件の現行値が未取得なら比率判定は未確認。ARM/Windows/LinuxへIntel結果を外挿しない。

## 保存する結果

`migration/benchmarks/results/<日付>-<task>-<host>.json`に以下を記録する（MIG-004以降に作成）。

```json
{
  "schema_version": 1,
  "protocol": "MIG-002-v0.1",
  "task": "MIG-004-B",
  "host": {},
  "source": {},
  "workload": {},
  "commands": [],
  "cache": {},
  "runs": [],
  "correctness": "not_run",
  "budget_verdict": "not_run",
  "limitations": []
}
```

各runに開始/終了条件、duration、exit code、metrics、失敗理由を付ける。空のひな形を測定結果として登録しない。
raw logは必要な範囲を添付し、集計値だけで最良runを選ばない。ハードウェア識別に不要な個人情報は保存しない。
