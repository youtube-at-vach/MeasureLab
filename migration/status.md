# 次期コア検証の進捗

更新: 2026-10-01。計画の正本は[評価計画](../guide/RUST_QML_MIGRATION_PLAN.md)。
Rust/QMLの採用は未決定。MIG-003-A/B/Cの参照側とMIG-004-Aの基本GUI境界を検証済み。
004-BのIntel反復build/編集/ローカルpackageは検証済み。対象OS全体の完了ではない。
Linux CIのICU不足を修正し、再実行は未確認。006-Aへ純粋FFT候補を追加し、24ケースの数値比較に合格。
Intelでのコア編集5回も完了、中央値24.544秒。
006-Bのpure共有graphを追加し、Rust16テストと保存18ケースで共有・分岐・所有権を検証した。
005-Aへpure音声境界とCPAL adapterを追加し、10契約例と4/8ch f32/f64の元bytesを検証。
005-BはUAC-232の交互3回にBlackHole 2ch／16chの回帰経路を追加。USB再接続・排他・絶対遅延は未確認。
以後の通常音声テストはBlackHole 16ch／2chを優先し、実機が必要な要件だけUAC-232を使う。
006-Cのworker所有履歴・Timebase・世代fenceをpure共有graphへ接続し、保存13契約と4入力bytesが合格。
006-Dのgraph所有filter/rate stateを追加し、f64保存21ケース×5 chunk/6 rate境界が合格。
006-Eの不変result/基本ID校正/JSON・CSV保存を追加し、保存2校正契約・4交換例と4/8ch f32/f64が合格。
005のinput.raw取得queue→履歴→共有FFTを接続し、保存4入力×2bindingの8ケースに合格。
CPALのBlackHole診断にも同じworkerを接続した。
005-Aへ固定容量の動的出力route mailboxを追加。保存f32の12条件とBlackHoleの9取得/3 cancelを検証した。
007-Aの保存入力→実graph→両Qtのline/heatmap表示を追加した。
BlackHoleの実入力→同じ共有result→両Qt表示を追加した。
分離viewと既存JSONによる9言語QMLを追加。保存4/8ch f32/f64×9言語×両Qtの72実行が成功。
取得ownerのTrigger captureを追加し、保存4入力×2bindingの32完全resultを検査した。
QtのTrigger要求配送と2view共通hold/retry/releaseを追加。保存4入力×9言語×両Qtの72実行が成功。
BlackHoleのTrigger要求配送も2/4/8ch×両Qt×3反復の18実行が成功。
校正・製品保存操作、製品共通adapter、製品保存互換/非同期保存は未着手。
007-CはIntel/Metalのwgpu 1候補と簡易plotterの最小試験を実施した。
候補の10万/100万点・rolling imageは約29〜30 Hzで更新。基準100万点のJSON/QML境界はSIGBUSを3回再現した。
PyQt画像provider経路の試験であり、採用判断・個別widgetの本実装・native GPU texture共有は含まない。

## 作業場所と基準

| 項目 | 値 |
| --- | --- |
| 現行版 | `/Users/vach/MeasureLab`、`main` |
| 検証用worktree | `/Users/vach/.codex/worktrees/next-core-evaluation/MeasureLab`（Codex管理） |
| 検証用ブランチ | 統合先`codex/next-core-evaluation`、今回の作業`codex/migration-trigger-delivery`（Trigger workerの`6e0b1ce2`から分岐） |
| 作業開始・Python参照コミット | `9fd79958`（MeasureLab 0.9.0、開始時のローカルmain） |
| 計画書の調査コミット | `68cbdabc3ecd542d9d73fa0aa86bf9159f44d811` |
| 最終main同期 | 2026-10-01にfetch。origin/mainは参照`9fd79958`のまま、取込み差分なし |
| 統合担当 | 当面、この検証ブランチを担当する単一の作業者 |
| リモート | 今回開始時は`codex/migration-trigger-capture`の`6e0b1ce2`がremote一致・clean。Qt Trigger配送の変更は未コミット。今回のpush・PR・Issue・Project更新・配布は未実施 |

調査コミットから開始時mainまでの差分には計画書、設計ガイド、Measurement Consoleのレイアウト、
Goniometerのテーマ対応、翻訳と対応テストがある。
MIG-002の棚卸しでは開始時mainを確認した。参照は`9fd79958f6a8bbae6808813d3704617612e6d26c`。
MIG-003-AでFFTの入力・期待値・source hash・依存バージョンを一緒に固定した。
MIG-003-Bは003-Aを変更せず、4/8ch参照と新契約の手計算例を別fixtureへ追加した。
MIG-003-Cも既存fixtureと契約を変更せず、filter/rate参照を独立したfixtureへ追加した。

## タスク

| タスク | 状態 | 成果・次の判断 |
| --- | --- | --- |
| MIG-001 | 完了 | 管理されたworktree、専用Python環境、状態を分離したオフライン起動、Rust/C++ビルドツール、再開・同期手順 |
| MIG-002 | 完了（P0文書・整合検査） | 41モジュール+共通10件、20プリミティブと双方向対応、コア/数値契約、16受け入れ条件、性能・反復予算、後続作業票 |
| MIG-003 | 完了（A/B/Cの参照側） | FFT20+4ケース、27契約例、4保存例にfilter/rateの21数値ケースと6 rate境界を追加。候補実装でのAC合格は005/006以降 |
| MIG-004 | 進行中（AとBのIntel範囲を完了） | Bの32 sample+warmup2回とローカルbundleが合格。Linux CIのICU不足を修正したが再実行未確認。他OS/clean環境は未確認 |
| MIG-005 | 進行中（Aの取得graph・動的f32 routeとBの短い実機／仮想比較） | 取得queue/履歴/共有FFTに動的出力mailboxを追加。保存12条件、BlackHole 2→2/4→16/8→16の9取得と3保留cancel。製品共通adapter/全tap、時刻写像、排他/USB復帰/長時間は残る |
| MIG-006 | 進行中（A〜Eのpure範囲を完了） | FFT/共有/履歴/filterに不変result/ID校正/保存を追加。Eの2校正契約・4交換例・4/8ch f32/f64、graph Rust50テスト合格。校正/保存/Qtの実取得統合は未着手 |
| MIG-007 | 進行中（Aの保存／BlackHole実入力表示・分離/9言語・Qt Trigger配送、CのIntel最小試験） | 保存表示/分離/9言語、取得ownerのTrigger captureにQtのhold/retry/releaseを追加。保存4入力×9言語×両Qtの72実行・288完全result/72 PNG、BlackHole要求配送18実行が成功。校正・製品保存操作/実window manager/他OS/統合性能は残る。renderer候補9試行成功、基準100万点3試行SIGBUS。採用判断・個別widgetの本実装・native texture共有は含めない |
| MIG-008 | 未着手 | 計画にある依存関係に従う。採用判断までの検証範囲 |

`native/`にツールチェーン/SDKの固定、Cargo workspace/lock、模擬workerと2方式のadapter、共通QMLを置いた。
006-Aの`dsp-core`へFFT/窓/単位/PSD、006-Bの`graph-core`へ固定DAG・共有/購読/独立平均/cacheを追加。
005-Aの`audio-core`とCPAL 0.18.2の`audio-probe`を追加した。
006-Cは`graph-core`内にworker所有履歴/有理数時刻/旧世代公開のfenceを追加した。
006-Dで同じgraphへf64の一段filter/rate stateと派生世代fenceを追加した。
006-Eは共有FFTから全配列と来歴をowned resultへ保存し、ID校正/JSON・CSVのpure境界を追加した。
005-graphはinput.rawの取得queueをworker所有履歴/固定FFT schedulerへ接続し、CPAL診断にも利用する。
現行PortAudioは比較基準。input.rawのgraph接続は追加済み。動的出力routeは固定容量mailboxでCPAL callbackへ配送する。
007-Aに保存replay用の独立解析threadと両Qt表示を追加した。
BlackHole input.rawの解析thread schedulerと両Qt表示を追加した。
同じviewの分離/reparent/close回収と、製品翻訳JSON→QML `tr()`を追加した。
取得ownerへ非消費Trigger capture/共有raw FFT/trigger付き不変resultを追加した。
Qtからrevision付き要求を解析threadへ配送し、両viewの共有hold/retry/releaseを接続した。
汎用scheduler、全tap/Qt接続、製品backend共通化は未作成。
候補実装は契約v0.1を出発点とし、公開型・ABI・採用ライブラリは後続の検証で決める。

## MIG-007-A Qt Trigger要求配送の成果と検証

着手: 2026-10-01、HEAD `6e0b1ce2`。前回の「Trigger capture未コミット」は古く、
開始時にremote一致・cleanの保存済みcommitを確認した。
同じworktreeで`codex/migration-trigger-delivery`へ分岐。今回の変更は未コミット。
変更境界はdisplay-core/両Qt adapter/共通QML、取得ownerのcache解除/Serializeとresultの読取りAPI、
翻訳10キー×9言語、独立runner/test/Native CIと検証文書。
現行Python DSP/GUI、audio callback、元fixture/数値契約/許容差、Cargo.lockは変更していない。

- [要求mailbox](../native/display-core/src/trigger.rs)は8 KiB以下のtyped要求と一件の未処理操作を持つ。
  解析ownerだけが履歴query/FFTを実行し、pending/gapには数値を返さない。
  明示retryは同じイベント/revision、releaseは後続公開をfenceして追加cacheを解除する。
  busy/旧世代/逆順revisionを拒否し、stopは未完成要求をcancelledにする。
- [共通QML操作](../native/qml/TriggerPanel.qml)から手動sample位置を送り、
  同じ不変projectionを両viewで保持する。通常取得は継続し、cursor/zoom/分離も同じ結果を参照する。
  encoded文字列の変更を介して凍結し、Qt Bridgeの通常counter通知で保持objectを再生成しない。
  stop/restart/Backend破棄後も外部の完成結果を保持できる。
- [runner](../scripts/migration_qt_trigger.py)は実queue/graphの全result/取得bytes/receipt/PNGを要求する。
  全配列を元bytesのNumPy oracleへ比較し、共有raw ID/追加FFT数不変、未校正reason、分数残差、
  保留→明示retry、hold中の取得、release/gap/世代/停止/破棄、実ラベル/button幅/最小サイズを検査する。
  同じ解析ownerをBlackHoleにも接続し、callbackの変更や未知clockの推定は行わない。
- [手順](../native/trigger-display.md)、[決定0021](decisions/0021-qt-trigger-delivery.md)、
  P03/P19、ACと作業票を更新した。Native CIへ保存Qt比較を登録し、GitHub実行は未確認。

最終保存report: `.migration-local/2026-10-01-trigger-delivery-final-v4/report.json`。
保存4/8ch f32/f64×9言語×両Qtの72実行、通常144＋Trigger144の288完全result、
Trigger144取得窓bytesと72 PNGがすべて成功。
mainのlayout最小サイズは640〜841×540 px、Qt SDK 6.11.2/macOS Intel/offscreen/software/Basic。
640 ms GUI停止中に通常FFTは6〜9窓進み、共有hold/独立zoom/分離の結果は不変だった。
短い診断条件であり、定常throughput/通知遅延/AC15・16の性能合格には数えない。

BlackHole最終report: `.migration-local/2026-10-01-trigger-delivery-live-final-v2/report.json`。
2→2/4-from-16/8-from-16×両Qt×3反復の18実行、通常36＋Trigger36の72完全result、
通常36＋Trigger36の72取得窓bytesと18 PNGが成功。全Trigger配列を元取得bytesのNumPy oracleへ比較した。
peak差の最大は約`1.3814e-9 FS`、callback error/XRUN/rejectedと取得gapは0、stream回収26.9〜36.9 ms。
GUI停止640 ms中にFFTは30〜37窓進んだ。queue最大深さは1024〜7680/8192 frameで、
負荷下の余裕や長時間性能は保証しない。default deviceとcallback処理は変更していない。

Rust workspaceはGraph72/Display11/Audio18/Audio probe8/DSP5/模擬worker5、計119 passed。
Displayはlive-audioを指定した別実行でも11件成功（重複あり）。workspace format/全target Clippyと両Qt buildも成功。
参照FFT14、core4 FFT/27契約/4保存、filter21数値/6 rate境界、41件台帳と2563キーの厳格翻訳checkも成功。
通常表示の回帰は`2026-10-01-trigger-delivery-display-regression-v2/report.json`の8実行/24完全result/8 PNGが成功。
分離表示の回帰は`2026-10-01-trigger-delivery-workspace-regression-v2/report.json`のen/ja×8ch f64×両Qt、
4実行/16完全result/12 PNGが成功。既存Pythonの全9言語UIサイズ検査は170.6秒で`Verification Passed`。
最終QMLは日本語/ロシア語の保持画面も目視確認した。Python対象回帰は最終sourceで226 passed（45.95秒）。
証拠破損/翻訳/寿命検査と既存の取得/保存/台帳/参照/校正/JSON・CSV回帰を含む。全体Pytestの代わりにはしない。

開発・失敗記録は保持する。
最初のsmokeはQt内部contentItemの画像取得と、Qt Bridgeの通常通知によるhold object再生成で失敗した。
既存canvasからの撮影とencoded文字列の変更に修正した。
最初の72実行は操作/数値/寿命が成功したが、dock直後の未反映geometryにより32画像のregion検査が失敗した。
実サイズ反映を待つv2は71成功、一件の8ch f64/Qt Bridgeが320 ms GUI停止中のFFT評価二窓の条件で失敗した。
原因は未特定。Triggerの診断を640 msへ固定し実増分を保存するv3へ変更し、全72実行を再検査した。
元runを性能合格に置き換えず、最終成功件数に混ぜない。
最初のBlackHole report（`2026-10-01-trigger-delivery-live-final/report.json`）は18実行中11成功・7失敗。
同一区間の二度目の要求が2窓の履歴から失効し、
8chでは取得queueのgapも記録した。履歴を8窓に広げ、通常表示の全列JSON化を必要列の読取りへ変更し、
完成resultもArc共有へ変更した。元の失敗reportを保持し、同じgap/error判定でBlackHoleを再実行した。
その後、保存全72実行も最終sourceのv4で再検査した。v3以前の成功を最終sourceの成功件数へ含めない。
workspace全testの初回はQt Bridgeのtest harnessがSDKを見つけられずdyldで失敗した。
既存Qt runnerと同じ明示SDK runtime環境を付けて再実行し、全119件とClippyが成功した。失敗logも保持する。
hash監査の初回は旧runner reportのbasename形式をrepo相対pathとして扱って失敗した。
runnerの既存形式を解決し、最終4 report・manifest・source/runner/binary/取得bytes/result/PNG、
1332ファイルのhashが一致した。監査時点47件のcommand/gzip log hashと過去5失敗reportも保存した。
監査は`2026-10-01-trigger-delivery-checks/audit.json`。最終成功件数へ過去runを混ぜていない。

command/終了コード/gzip log/hashは`.migration-local/2026-10-01-trigger-delivery-checks/`へ保存する。
分離した保存先でPython参照版のoffscreen起動self-testも成功した（9.83秒）。
Ruff lint/format、Markdown lint、diff whitespaceの最終終了コードも同じディレクトリへ記録する。
SDKのlocale/font、ranlib/重複rpath警告は残る。全体Pytest/Mypy、GitHub CIは未実施。
push/PR/Issue/Project更新・配布も行っていない。
検出器のarm/cancel、前段filter/外部clock、製品校正・保存互換/非同期保存、長時間/負荷下/他OSは未確認。
007-A全体/007-B/008、Rust/QML採用、製品41機能の移植は完了にしない。
次はID校正/基本保存のQt操作と実取得統合、または005の全tap/製品共通adapterへ進められる。

## MIG-007-A Trigger capture workerの成果と検証（前回記録）

着手: 2026-10-01、HEAD `68de1691`。CI修復ブランチはremote一致・cleanだった。
同じworktreeで`codex/migration-trigger-capture`へ分岐。今回の変更は未コミット。
前回の分離表示/9言語は`1390e64e`、CI境界・校正CSV登録は`36c0eaea`、
LinuxのFFT parameter ID上限修正は`68de1691`へ保存済み。これらのGitHub実行は今回未確認。
変更境界はgraph-coreの取得/履歴API、独立runner/test/CIと検証文書。
現行Python DSP/UI、Qt/QML/翻訳、audio callback、元fixture/契約/許容差、Cargo.lockは変更していない。

- [取得owner API](../native/graph-core/src/acquisition/trigger.rs)から既存履歴を非消費でqueryする。
  元eventのfloor/pre/post/分数残差を保持し、pending/gapには数値を返さない。
  古い世代・不正要求を拒否し、restart/stopは追加cacheを解除する。
- 同じ通常key/区間のraw FFTは同じID/allocationを再利用する。
  それ以外は既存FFTを一時graphで一回評価して回収し、追加raw cacheは一件に制限する。
  過去窓を通常購読へ公開せず、最新位置・独立平均・通常graphのFFT件数を維持する。
- 元TriggerEventと全配列を不変MeasurementResultへ接続した。同じrawを使うcaptureでも
  metadataが異なる結果には別のresult IDを付ける。未知clockと未校正電圧はnull/reasonのまま。
  snapshot/resultは履歴上書き・新世代・停止後も外部が保持できる。
- [独立runner](../scripts/migration_trigger_candidate.py)は元4/8ch f32/f64と2bindingを
  実queueへ通す。未取得要求→完成/遅い通知→1frameずれの分数trigger→別読者→
  保持超過→旧世代/二重stopを保存し、全数値配列を元bytesのNumPy oracleへ比較する。
  未移動FFTは保存済み理論/現行値にも比較する。期待値をcandidateへ送らない。
- [手順](../native/trigger-capture.md)、[決定0020](decisions/0020-trigger-capture-worker.md)、
  P03/AC/作業票と独立Rust CIを更新した。通常Python CIにはNumPyだけの証拠破損テストを残す。

最終保存report: `.migration-local/2026-10-01-trigger-final/report.json`。
4/8ch f32/f64 × identity/逆順bindingの8条件、32完全result/32保持窓bytesが成功。
各条件で通常FFTの共有、追加FFT一回、通常graphの前後stats一致、最新区間/独立平均不変を確認した。
通常購読を閉じて新世代/stopへ進めた後に全result/bytesを保存し、不変性を照合した。
分数位置と受信host時刻は別に保持し、全配列は元bytesのNumPy oracleへ既存許容差で一致した。

Qt回帰report: `.migration-local/2026-10-01-trigger-display-final/report.json`。
両方式を最終sourceで再buildし、保存4入力×両方式の8実行、24完全result/8 PNGが成功。
Qt SDK 6.11.2/macOS Intel/offscreen/software/Basicで、trigger UIの合格には数えない。
再build前の`trigger-display-regression`は診断だけに使い、最終sourceの合格件数へ含めない。

| 検証 | 結果 |
| --- | --- |
| Trigger取得/数値/所有権 | 保存8条件/32完全result、元bits/ID/位置/残差/未校正reason、cache/通常平均不変/世代/停止後の不変性が成功 |
| Rust | Graph71（追加9）/Audio18/DSP5/表示8/模擬worker5、計107 passed。表示はlive-audio featureを含む。workspace format/全target Clippyと両Qt build成功 |
| Python対象回帰 | 205 passed（50.37秒）。新規37に履歴/取得/保存/表示/live証拠/workspace/台帳を含む。不正snapshot/trigger/数値/寿命/型を拒否 |
| 保存fixture/参照起動 | FFT14、core4 FFT・27契約・4保存、filter21・6 rate境界、台帳41件と分離offscreen起動が成功 |
| 両Qt保存表示 | 最終buildで8実行/24完全result/8 PNGが成功。実入力/trigger UIは今回未実施 |
| Ruff/Markdown/diff | Ruff lint/format成功。Markdown 207ファイル0 issues、diff whitespace成功。最終文書更新後にも再検査 |
| source/report/hash | 最終triggerとQt reportのsource/runner/binary/request/保持bytes/result/PNG、計233照合が一致 |
| main/CI | fetch後もorigin/mainは`9fd79958`で取込み差分なし。今回追加CIのGitHub実行は未確認 |

command/終了コード/gzip log/hashは`2026-10-01-trigger-checks.json`と`trigger-*.log.gz`、
参照起動/Rust tests/runnerのlog、監査は`2026-10-01-trigger-audit.json`に保存した。すべて`.migration-local/`内。
SDKのlocale/font、ranlib/重複rpath警告は残る。全体Pytest/Mypy/全言語UIサイズは今回未実施。
push/PR/Issue/Project更新・配布も行っていない。

N≤4096の同期解析owner APIまでを完了した。Qt操作/実入力要求配送、arm/cancel/検出器、
前段filterのtrigger、外部clock、長時間/負荷下/他OSは未確認。
007-A全体/007-B/008、Rust/QML採用、製品41機能の移植は完了にしない。
次はQtからrequest/revisionを配送し、2viewの共有hold/retry/releaseを接続する。
校正・製品保存操作、005の全tap/製品共通adapterも引き続き後続に残る。

## MIG-007-A 分離表示と9言語の成果と検証（前回記録）

着手: 2026-10-01、HEAD `973c8290`。007-live-displayはremote一致・cleanで保存済みだった。
同じworktreeで`codex/migration-007-windows-i18n`へ分岐。今回の変更は未コミット。
変更境界は表示workerのlocale/両Qt adapter/共通QML、翻訳JSON・キー保守、runner/test/独立CIと文書。
現行Python DSP/GUIコード、音声callback/取得core、元fixture・契約・許容差、Cargo.lockは変更していない。

- [共通wrapper](../native/qml/PlotPane.qml)で同じviewを分離Windowへreparentする。
  結果snapshot/需要token/ch/cursor/独立zoom/履歴を保持し、再接続で購読を増やさない。
  native closeでview需要を解除し、他の需要は継続、最後の解除でworker/graphを回収する。
  通常表示への再オープン、分離中のBackend再生成・アプリ終了も検査する。
- [locale境界](../native/display-core/src/locale.rs)から製品のen.jsonを正本にした35キーを
  QML `tr()`へ渡す。9言語をbinaryへ埋め込み、起動時の`--language`で選ぶ。
  既存のIdle/Stop/Spectrum等の訳と用語をそろえ、全言語の置換fieldを維持した。
  callback/解析threadへ翻訳処理を加えず、結果ID・単位・reasonは保存値のまま。
- 翻訳check/updateは同じQML source inventoryを使用する。コメント/文字列内の偽呼出しを除外し、
  QMLだけのキーが未使用扱いで削除されない。既存の翻訳キー/値は変更していない。
- [runner](../scripts/migration_qt_workspace.py)は両方式のcatalog/実ラベル/button幅/最小サイズに加え、
  4世代の完全resultとmain/分離2画面のPNGを要求する。全peak/軸を元の理論/現行fixtureへ照合する。
  長い翻訳でpanel位置が変わるため、実Canvas座標で画素を検査し、領域外・重複・空画像を拒否する。
- renderer spikeの既存SpectrumViewにも英語catalogを供給した。workspace操作のfooterはspikeで表示せず、
  元のデータ領域/試験条件を維持する。採用・性能の追加判断は行っていない。
- [手順](../native/workspace-display.md)、[決定0018](decisions/0018-detached-localized-displays.md)、P19/AC/作業票を更新した。
  Rust CIへ9言語のQt検査と不正証拠拒否、厳格翻訳checkを追加。GitHub実行は未確認。

最終保存report: `.migration-local/2026-10-01-007-windows-final-v3/report.json`。
保存4/8ch f32/f64×9言語×両Qt方式の72実行、288完全resultと216 PNGがすべて成功。
mainのlayout最小サイズは640〜841×540 px、分離Windowは320〜402×280 px。
Qt SDKのmacOS既定fontで1180×690 pxの上限内。日本語・中国語・ロシア語の最終画像を目視確認した。
BlackHole回帰: `.migration-local/2026-10-01-007-windows-live-final/report.json`。
他のGUI/build試験を止めて3入力条件×両Qt方式×3反復の18実行、54完全result/取得窓/停止診断、18 PNGが成功。
全peakのNumPy oracleとの差は最大約`1.8382e-9 FS`、stream回収26.5〜32.7 ms、queue最大深さ1280〜4864/8192 frame。
callback error/XRUN/rejectedと取得gapは0。短い診断で、絶対遅延・負荷下の性能合格ではない。

| 検証 | 結果 |
| --- | --- |
| 分離/9言語QML | 72実行/288 result/216 PNG、全ラベル・button幅・layout上限・close/reopen/recreate/終了が成功 |
| BlackHole英語回帰 | 18実行/54 result・取得窓・回収記録/18 PNGが成功。全peakはNumPy oracleへ既存f32許容差で一致 |
| Rust | 両Qt build、表示8 tests、workspace全target Clippy/formatが成功。依存版/lock不変 |
| Python対象回帰 | 89 passed。workspace/display/live/renderer/台帳/localization。偽catalog/label/clipping/寿命/画像領域を拒否 |
| 保存fixture・台帳 | FFT14、core4 FFT/27契約/4保存、filter21数値/6 rate境界、41件の台帳checkが成功 |
| 既存Python全言語UI | 全9言語Verification Passed。QMLの実行結果とは別 |
| Ruff/翻訳/Markdown | Ruff lint/format、2553キーの厳格翻訳check、Markdown 204ファイル0 issues、diff whitespaceが成功。最終文書更新後にも再検査 |
| source/report/hash | 最終workspace/実入力のsource、翻訳9 JSON、runner/helpers、binary、全request/result/取得窓/停止診断/PNGが一致。854種類のfile・1078照合 |
| main/CI | fetch後もorigin/mainは`9fd79958`で取込み差分なし。追加CIのGitHub実行は未確認 |

開発中の失敗と限界:

- `007-windows-smoke`は追加restartでcoalesced counterがリセットされた後の試験が失敗した。
  v2は浮動Windowのclose拒否がアプリ終了も拒否する問題と、初期翻訳bindingの空fieldを検出した。
  両方を修正し、v3/v4を別directoryへ保存した。失敗記録を保持する。
- 最初の`007-windows-final`は固定座標のPNG検査が翻訳後の細いpeakを見落としたため中断した。
  実Canvas領域を検査するよう修正した。v2は用語を製品既存訳へそろえる前の開発runとして中断・保持した。
  未完了runを最終72条件の合格には数えない。
- 最初の`007-windows-live-regression`はGUI/renderer比較と同時実行した。
  2/4chの4実行は成功、8chの両方式は`live_input_gap`で失敗し、queue最大深さが8192/8192 frameに達した。
  失敗を正常なzeroや成功へ変換せず、stream/graph回収と診断を保存した。
  同時負荷の影響を含む失敗で、性能予算や負荷下での安定性の合格ではない。
  最終18実行は他のGUI試験を止めて再実行した。007-Bで負荷条件を固定した検証が必要。
- rendererの互換診断では候補9/基準6が成功、既知の基準100万点SIGBUSを3回再現しrunner終了コードは1。
  同時試験/短い更新の診断で、前回の性能表を置き換えない。原データは`007-windows-renderer-regression`に保持した。
- 最終sourceのrenderer互換スモークは基準Spectrum 10万点3更新、rolling 1024×32行40更新の両方が成功。
  再生成・cursor・元データ領域も検査した。`007-windows-renderer-final-spectrum`/`-spectrogram`へ保存した。
  短い互換試験で、性能表・採用判断の更新には使わない。
- SDKのlocale/font、offscreenのpropagateSizeHints、ranlib/重複rpath警告は残る。

検査log/終了コード/hashは`.migration-local/2026-10-01-007-windows-checks.json`と`007-windows-check-*.log.gz`、
UI logは`007-windows-ui-size.log`、最終監査は`2026-10-01-007-windows-audit.json`へ保存した。

分離操作/9言語のQt SDK 6.11.2/macOS Intel/offscreen/software/Basic範囲を完了した。
実window managerの移動/focus/minimize、他OS/font/DPI、動的言語切替と配布は未確認。
007-A全体/007-B/008、Rust/QML採用、製品41機能の移植を完了にしない。
次はtrigger/保持履歴操作、基本校正・製品保存操作、または005の全tap/製品共通adapter。
全体Pytest/Mypyは今回未実施。push/PR/Issue/Project更新・配布も行っていない。

## MIG-007-A BlackHole実入力の共有result表示の成果と検証（前回記録）

着手: 2026-10-01、HEAD `f49ba320`。007-rendererはremote一致・cleanで保存済みだった。
同じworktreeで`codex/migration-007-live-display`へ分岐。今回の変更は未コミット。
変更境界はCPAL input-only owner、既存表示worker/共通QML、独立runner/test、Rust CIと検証文書。
現行Python DSP/UI、元fixture、core/numerical契約・許容差、renderer spikeは変更していない。
Cargo.lockはdisplay-coreから既存audio-probeへの依存1件だけ。外部package全項目は不変と照合した。

- [CPAL入力owner](../native/audio-probe/src/live.rs)を解析threadで作成・開始・停止・破棄する。
  callbackは固定queue/atomicだけを操作し、GUI用mutex・JSON・ファイルI/Oを持たない。
  device/物理channel数/論理ID→portを明示し、fallback、暗黙の精度変換、clock写像推定を行わない。
- [実入力scheduler](../native/display-core/src/live.rs)を同じ履歴/共有FFT/不変result/両Qt表示へ接続した。
  保存replayと購読同期・allocation共有・通知mailbox・回収を共通化した。
  最新GUI通知が保留でも取得/解析を継続する。gap/callback失敗/XRUN/3秒無入力は明示failureにする。
- [runner](../scripts/migration_qt_live.py)はBlackHole 2chの逆順binding、16chから飛び飛びに選ぶ4ch／8chを検査する。
  logical ch別のtoneと未選択portの別toneで誤bindingを検出する。
  3世代の取得窓bytes/完全result/停止診断、PNGを要求し、全peakを独立NumPy FFTへ照合する。
  数値は既存f32契約、port別toneは事前に固定した`1e-6 FS`で評価する。
- 準備中cancel/二重開始停止/注入失敗、2view→1view→sessionだけ→最後の解除、
  再オープン/旧世代拒否/Backend再生成/動作中終了、cursor/独立zoom/不変snapshot/画像保存を検査した。
  GUIを320 ms止めてもFFTが進み、停止時にstreamとgraphのnode/subscription/cache/in-flightを回収した。
- [手順](../native/live-display.md)と[決定0017](decisions/0017-live-result-display.md)、P19/AC/作業票を更新した。
  独立Rust CIのaudio-backendへlive featureの検査とNumPy-onlyの不正証拠拒否を追加。GitHub実行は未確認。

最終report: `.migration-local/2026-10-01-007-live-final/report.json`。
3入力条件×両Qt方式×3反復の18実行、54取得窓/完全result/停止診断、18 PNGがすべて成功。
macOS 14.8.9/Intel、Qt SDK 6.11.2、offscreen/software/Basic、f32/48 kHz/256 frame、N=1024/boxcar。
取得窓とNumPy f64 oracleの全peak最大差は約`1.3813e-9 FS`。
未知clock原点/不確かさはnull、未校正電圧はnull＋uncalibratedのまま。
54停止診断のstream回収は約27.6〜49.0 ms、queue最大深さは1280〜5888/8192 frame。
callback error/XRUN/rejectedと取得gapは0。短時間の診断値で、性能protocol/絶対遅延/物理I/Oの合格ではない。

| 検証 | 結果 |
| --- | --- |
| 実入力→実graph→両Qt | 18実行、54完全result/取得窓/回収記録、18 PNGが成功。8ch最終画像を目視確認 |
| 保存表示の回帰 | `007-live-replay-regression/report.json`。4/8ch f32/f64×両方式の8実行、24 result/8 PNGが成功 |
| Rust | 両Qt build、Audio18/CPAL8/Graph62/DSP5/模擬worker5/表示worker7の計105 passed、workspace全target Clippy/format成功。live featureなしの表示7件も別途成功 |
| Python対象回帰 | 137 passed（14.88秒）。live20件＋保存表示/取得graph/音声契約/動的route/台帳。不正bytes/metadata/clock/未校正値/stream未回収/XRUN/markerだけの偽成功を拒否 |
| 保存fixture・台帳 | FFT14、core4 FFT/27契約/4保存、filter21数値/6 rate境界、41モジュールの台帳checkが成功 |
| UIサイズ | 英語QMLのimplicit最小サイズは690×540 px。既存Python GUI全9言語はVerification Passed。9言語QML合格とは別 |
| Ruff/Markdown/diff | lint/format成功。Markdown 202ファイルは0 issues、diff whitespaceも成功。最終文書更新後も再検査 |
| source/report/hash | 最終/回帰reportのnative source、runner/helpers、binary、全request/result/取得窓/診断/PNGを照合し一致 |
| main/CI | fetch後もorigin/mainは`9fd79958`、取込み差分なし。追加CIのGitHub実行は未確認 |

Rust/Python/referenceのcommand/gzip log/hashは`2026-10-01-007-live-*-checks.json`、
UI logは`2026-10-01-007-live-ui-size.log`、監査は`2026-10-01-007-live-audit.json`に保存した。
すべて`.migration-local/`内。`007-live-smoke`の2実行はrunnerがf32へf64相当の閾値を当てたため失敗した。
既存f32契約を使うようrunnerを修正し、6実行の`007-live-development`と最終18実行を別directoryへ保存した。
失敗記録を残し、元fixture/DSP/数値契約は変えていない。SDKのlocale/font・ranlib/重複rpath警告は残る。

BlackHole input.rawの実表示境界までを完了した。007-A全体/007-B/008とRust/QML採用は未完了。
次はtrigger/保持履歴操作、基本校正・製品保存操作、分離window/9言語、または005の全tap/製品共通adapter。
物理USB復帰、外部clock、実device校正、長時間性能、他OS/配布は未確認。
全体Pytest/Mypy/厳格翻訳キー検査は今回未実施。push/PR/Issue/Project更新・配布も行っていない。

## MIG-007-C Plot Renderer Feasibility Spikeの成果と検証（前回記録）

着手: 2026-10-01、HEAD `366aa7f3`。007-displayはremote一致・cleanで保存済みだった。
同じworktreeで`codex/migration-007-renderer`へ分岐。変更は未コミット。
変更境界は独立したrenderer crate/QML試験画面、Python試験host/oracle/test、独立Rust CIと検証文書。
現行Python DSP/UI、既存native workspace/lock、簡易plotter、保存fixture・数値契約・許容差は変更していない。

- [wgpu候補](../native/renderer-spike/src/main.rs)はGPUでSpectrumの最大値縮約とRGBA rasterを生成する。
  rolling imageは32行の循環bufferに新しい1行だけをuploadし、画像全体を読み戻す。
  Cargo workspace/lockを分離し、wgpu 30.0.1、Rust 1.98.1を固定した。
- [試験host](../scripts/migration_plot_renderer.py)が同じf32入力と1024×256 pxのデータ領域で、
  既存SpectrumViewとwgpu候補を比較する。PyQt image providerでQMLへ接続し、画像を実表示したことを画素で検査する。
  候補の入力hash、狭い1 bin peak、元データcursorと32行を越えたrolling historyを全更新でCPU oracleと照合する。
  oracleは表示更新の測定後に実行する。
- Zoom/Pan、画面座標↔周波数、元データ参照、viewの破棄/再生成、GPU ownerのstop/再生成、
  GPU更新要求直後のQML engine破棄とGPU完了/owner破棄を検査した。
  この接続はGUI threadで読み戻しを待つ。非同期mailbox・CXX-Qt/Qt Bridge接続・GPU texture共有は未実装。
- [再実行手順・コピー内訳](../native/renderer-spike.md)を追加した。
  Rust CIはGPU/Qtを起動しないbuild/test/Clippy/formatと、Pythonの不正証拠拒否を検査する。GitHub実行は未確認。

最終reportは`.migration-local/2026-10-01-007-c-final-v3/report.json`。
検査要約は`.migration-local/2026-10-01-007-c-checks.json`、source/hash監査は`2026-10-01-007-c-audit.json`へ保存した。
macOS 14.8.9/Intel、Iris Pro Graphics 6200/Metal、PyQt Qt runtime 6.11.2、Qt offscreen/software/Basic。
更新目標30 Hz、warmup 3更新、Spectrum 30更新、Spectrogram 40更新、各3回。
候補9試行と基準10万点/rollingの6試行は検査成功。基準100万点の3試行は失敗し、比較runnerの終了コードは1。

| 経路 | 更新Hz（3試行） | 表示までの中央値ms（3試行） | p95 msの範囲 | CPU全run率の範囲 |
| --- | --- | --- | --- | --- |
| 基準 Spectrum 10万点 | 3.034 / 3.110 / 3.076 | 323.727 / 318.002 / 321.328 | 322.112〜328.975 | 98.65〜99.32% |
| 基準 Spectrum 100万点 | 未取得（全3試行SIGBUS） | 未取得 | 未取得 | 未取得 |
| 基準 Spectrogram 1024×32行 | 12.075 / 11.951 / 12.106 | 88.491 / 90.517 / 87.089 | 116.215〜118.176 | 93.29〜93.57% |
| wgpu Spectrum 10万点 | 29.349 / 29.280 / 29.318 | 13.129 / 13.105 / 13.072 | 13.559〜13.646 | 39.31〜39.60% |
| wgpu Spectrum 100万点 | 29.308 / 29.435 / 29.483 | 31.927 / 31.982 / 31.980 | 32.426〜32.927 | 81.41〜83.50% |
| wgpu Spectrogram 1024×32行 | 29.212 / 29.279 / 29.223 | 11.052 / 11.014 / 11.006 | 11.487〜11.550 | 31.47〜31.77% |

主時間には生成・転送・表示を含む。CPU全run値はoracle・warmup・生成/破棄も含む。
候補は軸/文字等を持たない最小rasterで、基準のCanvas/JSON経路全体との試験である。
この差をrenderer単体・言語単体の性能差やAC15/16の合格として扱わない。
OSのGPU全体使用率中央値は、候補100万点が各試行2%、他の成功条件は0〜1%。
他アプリの負荷も含み、低い値は短い処理の無活動を意味しない。
GPU timestamp featureは未対応なのでpass時間はnull。候補だけのGPU負荷/転送時間は未確認。

基準100万点は初回の38,752,554 bytesのJSONをQMLへ渡す境界でSIGBUS（終了-10）を3回再現した。
macOS診断のfaulting threadはQtQml/QQmlBindingで、保護されたJS VM Isolated Heapへのアクセスを示す。
`QV4_FORCE_INTERPRETER=1`でもSIGBUSを再現した。Qtの根本原因や修正は未確定。
GPU側が100万点を処理できた結果と、基準JSON/QML経路の失敗を分けて記録する。
開発/初回測定は`007-c-development`、`007-c-final`/`007-c-final-v2`と各`007-c-*-smoke*`、
interpreter診断は`007-c-million-interpreter-diagnostic`へ保持し、失敗記録は削除していない。

明示的な候補copy/転送は、入力upload 1回、uniform upload 1回、GPU readback copy 1回、
mapped buffer→Vec copy 1回、RGBA IPC 1,048,576 bytes、QImage.copy 1回/更新。
入力はSpectrumで400,000/4,000,000 bytes、rollingで新規行4,096 bytes、uniformは32 bytes。
OS pipe・Qt/driver内部のcopy回数とUMAの物理転送回数は未確認。
共有textureと非同期転送による削減余地を後続の検証材料とする。

| 検証 | 結果 |
| --- | --- |
| renderer最小試験 | 候補9＋基準6試行成功、基準100万点3試行失敗。入力/画素/cursor/rolling/再生成/終了を検査 |
| Rust | release build、2 tests、Clippy、format成功。既存workspace/lockは不変 |
| Python対象回帰 | 36 passed。新規5件＋既存表示runner/台帳。入力不一致・peak欠落・誤cursor・rolling破損・不正/truncated transportを拒否 |
| 保存fixture・台帳 | FFT14、core4 FFT/27契約/4保存、filter21数値/6 rate境界と41モジュールの台帳checkが成功 |
| Ruff/Markdown | lint/format成功、Markdown 200ファイルは0 issues。最終文書更新後も再検査 |
| UIサイズ | 既存Python GUI全9言語はVerification Passed。試験QMLは英語、1088×352/392 pxでデータ領域1024×256 px。9言語QMLの合格ではない |
| source/hash | 最終reportのrunner/試験QML/基準QML/Rust/WGSL/lock/実行物のhashはすべて一致。候補の記録354更新と終了中の更新を検査 |
| main/GitHub CI | fetch後もorigin/mainは`9fd79958`、取込み不要。新しい独立CIは未実行 |

007-CのIntel最小試験と確認記録を完了した。rendererの採用判断・製品組込み・個別widgetの本実装は行っていない。
rsplot、native GPU texture共有、非同期GUI、他OS、9言語QML、実音声、複数viewと10分性能は未確認。
次は007-Aの実音声表示/trigger/基本校正/保存操作/9言語、または005の全tap・共通adapterへ進める。
全体Pytest/Mypy/厳格翻訳キー・実音声回帰は今回未実施。push/PR/Issue/Project更新・配布も行っていない。

## MIG-007-A保存入力の共有result表示の成果と検証（前回記録）

着手: 2026-10-01、HEAD `408a79f5`。005-routeはremote一致・cleanで保存済みだった。
同じworktreeで`codex/migration-007-display`へ分岐。今回の変更は未コミット。
変更境界は新しい表示worker/両Qt adapter/QML、独立runner/test/CI、検証文書。
現行Python DSP/UI、既存audio/graph/probeと004-Aの画面、003-A/B/Cの元fixture・契約・許容差は変更していない。
Cargo.lockはローカル3 crateの追加だけ。既存package/dependencyの全項目が不変と照合した。

- [display-core](../native/display-core/src/lib.rs)が保存元bytesを実queue→履歴→共有FFTへ継続投入する。
  view/sessionの最大16 tokenを実graph購読へ反映し、完成窓ごとに全購読の同じraw allocationを確認する。
  result/projectionを一度だけ作り、容量1のmailboxでQtへ通知する。表示が遅れても解析を続ける。
- [共通QML](../native/qml/Display.qml)を独立したCXX-Qt/Qt Bridge実行物が読む。
  line/heatmapは同じID・区間・Timebaseを持つ凍結済みprojectionを共有する。
  channel/cursor/zoomは表示ごとに独立。全binの解析精度を保持し、描画だけを画素列の最大値へ縮約する。
  heatmapは最大32表示snapshotをsample時間で配置し、未表示区間を空白にする。
- 準備中cancel/失敗/停止、旧世代通知、2view→1view→sessionだけ→最後の解除、Backend/表示再生成を検査する。
  stopでnode/subscription/cache/in-flight、動作中終了でworker/modelを回収する。
  PNG保存中は表示snapshotを保持し、解析は継続する。画像保存失敗を成功表示しない。
- [runner](../scripts/migration_qt_display.py)は元fixtureを変更せず4/8ch f32/f64を両方式へ通す。
  markerだけでは合格にせず、3世代の完全なresultとPNGのCRC/寸法/両plot画素を要求する。
  [決定0016](decisions/0016-shared-result-display.md)、[再検査手順](../native/display-candidate.md)、P19/AC/作業票を更新した。
  独立CIへpure表示worker test/ClippyとQt保存表示比較を追加。GitHub実行は未確認。

最終report: `.migration-local/2026-10-01-007-a-final/report.json`。
4入力×両方式×3反復の24実行、72の完全なresult、24 PNGが成功。
全peak配列と軸を保存済み理論/現行期待値へ照合した。
理論に対する最大peak絶対差はf64約1.30e-14 FS、f32約1.67e-8 FS。
未知clock原点/不確かさはnull、未校正の電圧はnull＋uncalibratedを保持する。

| 確認 | 結果 |
| --- | --- |
| 保存入力→実graph→両Qt | 24実行成功。共有ID/区間/Timebase、cursor/独立zoom、凍結/保持snapshot、遅いGUI、世代fence、購読解除/再生成/終了 |
| 完全result/PNG | 72 resultの全peak/軸/metadataと24画像のCRC/寸法/両plot画素が成功。最終8ch f32画像を目視確認 |
| 最小Python環境 | `2026-10-01-007-a-minimal/report.json`。Python 3.12.14/NumPy 2.2.6/pipだけで8実行・24 result・8 PNG成功。GUI/device importなし |
| 既存004-A Qt回帰 | `2026-10-01-007-a-old-qt-regression.json`。両方式×3反復の6実行成功 |
| Rust build/test/Clippy/format | workspace build、Audio18/CPAL6/Graph62/DSP5/模擬worker5/表示worker5、計101 passed。workspace全target Clippyとformat成功 |
| Python対象回帰 | 141 passed（494.66秒、並行build待ちを含む）。表示runner15件＋Qt/反復/取得graph/result/graph/台帳 |
| UIサイズ | 英語QMLはimplicit layout由来690×540 px。既存Python GUI全9言語はVerification Passed。9言語QMLの合格ではない |
| 保存fixture verify | FFT14、core4 FFT/27契約/4保存、filter21数値/6 rate境界が成功。元fixture変更なし |
| Ruff/Markdown/台帳/diff・分離起動 | 成功。635 Python/199 Markdown、41モジュール双方向対応。専用state-dirのoffscreen self-test終了0 |
| source/report/hash監査 | 最終/最小環境のnative source53件、runner/補助source、binary、全request/result/PNGとcommand gzip log/hashを照合 |
| main/CI | fetch後もorigin/mainは`9fd79958`。取込み差分なし。既存005-routeのGitHub run検索は0件、新しいCIも未実行 |

Rust command/log/hashは`2026-10-01-007-a-rust-checks.json`、Python/UIは`2026-10-01-007-a-python-checks.json`、
台帳/fixture/Ruff/Markdown/分離起動は`2026-10-01-007-a-static-checks.json`へ保存した。
最小環境の導入版は`2026-10-01-007-a-minimal-environment.json`、hash監査は`2026-10-01-007-a-audit.json`。
すべて`.migration-local/`内。開発runは`2026-10-01-007-a-development*`、単一診断は`007-a-one-diagnostic`へ保持する。
開発中のCXX型名/二重buildのlink問題、invalid結果をFFT評価数で待ったテスト、PNG検査範囲、Clippy指摘を修正した。
最終check記録のCargo fmtに渡した不適用引数は修正して再実行し、失敗記録も残している。
SDKの既存locale/font・ranlib/重複rpath警告は残るが、検査の終了コードは成功。

このworkerは保存入力のreplay用で、実音声callback/clockのGUI接続ではない。
英語QMLと既存Python全言語UIの検査を、9言語QML・分離window・trigger UI・製品校正/保存の合格に置き換えない。
10分性能/CPU/RSS、QML編集反復、他OS/配布も未確認。007-A/007-B/008全体とRust/QML採用は未完了。
次はBlackHole入力をこの表示境界へ接続し、trigger/基本校正/保存操作/9言語を検証するか、005の全tap/共通adapterへ進める。
全体Pytest/Mypy/厳格翻訳キー/実音声回帰/GitHub CIは今回未実施。push/PR/Issue/Project更新/配布は行っていない。

再実行:

```bash
./.venv/bin/python scripts/migration_qt_display.py --qt-prefix .tools/qt/6.11.2/macos --repeat 3 --output .migration-local/007-display-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_display.py
```

## MIG-005動的出力routeの成果と検証（前回記録）

着手: 2026-10-01、HEAD `8f1d1362`。005-graphはremote一致・cleanで保存済みだった。
前回の「005-graph未コミット」は古く、このcommitへ保存済みと確認した。
同じworktreeで`codex/migration-005-route`へ分岐。007-display着手時に`408a79f5`へ保存済み・remote一致を確認した。
変更境界はaudio-coreの制御→callback配送、CPAL診断、独立runner/test/CI、検証文書。
現行Python DSP/UI、003-A/B/Cの保存入力・期待値・契約・許容差、Cargo依存/lockは変更していない。

- [動的mailbox](../native/audio-core/src/dynamic_route.rs)はcontrol/callback各1 owner、未確認要求1件。
  制御側で検証・compileし、callbackでは固定16×16 termsをblock境界でcopyする。
  callbackのalloc/解放/lock/待機loop/文字列操作はない。unsafeを使わない。
  busy/無効/旧世代/逆順/output binding変更は現在のrouteを保ったまま拒否する。
- callbackの全block検査後に、要求位置以上の境界へ適用。数値sequence/区間を返し、
  制御側でrevision・要求/実適用sampleを不変eventへ記録する。遅いackでも音声を続ける。
  closeは冪等、callback破棄後に保留をcancelledとして一度返す。再開時は新endpointを使う。
- [保存比較runner](../scripts/migration_audio_route.py)は003-Bの4/8ch f32元bytesを4→2/8、8→4/16へ通す。
  固定/可変blockと1/4 blockおきのack確認の12条件。独立sampleモデルと手計算位置を照合し、
  output.mixed/mute後device_bufferの全bytes、generation/sequence/revision/要求/実位置を検査する。
- [CPAL診断](../native/audio-probe/src/main.rs)の制御loopから実callbackへ同じmailboxを配送する。
  全scheduleをdevice open前に検証し、未完了の変更は保存reportと終了失敗へ反映する。
  ackは`output-callback.frame`に限定し、input.rawへ出力revisionを事後適用しない。
  全raw提出/入力、共有FFTの件数/共有/回収、mute/error/XRUN/gapを検査する。
- [決定0015](decisions/0015-dynamic-output-route.md)、[再検査手順](../native/dynamic-route.md)、
  P02/AC03/作業票を更新。独立CIへroute build/portable比較を追加。GitHub実行は未確認。

最終保存report: `.migration-local/2026-10-01-005-route-final.json`。
最小環境report: `.migration-local/2026-10-01-005-route-minimal.json`。
12条件が成功。要求位置257/1025/2049に対し、固定256 blockは512/1536/2304、
可変blockは384/1790/2174、遅いackは383/1659/2298で適用し、独立oracleと一致した。
mixed/device bytesは完全一致。空のFS合計の符号付きzeroは既存CompiledRouteを保ち、muteは+0。

| 確認 | 結果 |
| --- | --- |
| 保存入力・動的route・tap | 4/8ch f32 × 出力2種 × block/ack3種の12条件、36変更の値/metadata完全一致 |
| 最小Python環境 | Python 3.12.14/NumPy 2.2.6＋pipだけで同じ12件成功。Qt/FFTW/SciPy/音声依存なし |
| BlackHole実配送 | `.migration-local/2026-10-01-005-route-blackhole-final-v3/report.json`。2→2/4→16/8→16を各3回、計9取得・27適用とPreparing中3保留cancel成功。入力/提出最大誤差0 FS、gap/error/XRUN/reject 0 |
| 実取得graph | 計3564完成窓。各窓の共有FFT評価1、同じraw allocationを2購読で共有し、stop後のnode/subscription/cache/in-flightは0 |
| Rust test/fmt/Clippy | Audio18/CPAL request6/Graph62/DSP5/模擬worker5、計96 passed。追加11件。2,000件の同時配送、旧世代/無効/busy/停止/再開/16ch/加算順、workspace formatとpure/CPAL Clippy成功 |
| Python対象回帰 | 251 passed（128.08秒）。新route33件とaudio/virtual/取得graph/result/graph/history/filter/台帳/分離起動/ring buffer |
| 保存fixture verify | FFT14、core4 FFT/27契約/4保存、filter21数値/6 rate境界が成功。入力・期待値更新なし |
| Ruff/Markdown/台帳/CI仕様/diff | 成功。631 Python/197 Markdown、41モジュール双方向対応、CIは既存workflowへroute build/portable 2行だけの追加・inline SDK Python整合を検査 |
| 起動分離 | 専用state-dirの保存先確認とoffline/offscreen self-test終了0。従来のlocale/font警告のみ |
| source/report/hash監査 | 最終/最小環境/CPALのsource/runner/lock/binary、元fixture不変、全raw/request/manifestと57 commandのgzip log/hash/終了コード0を照合 |
| main同期 | fetch後もorigin/mainは`9fd79958`。取込み/参照更新不要 |

Rust/対象回帰/保存fixtureのcommandとlogは`.migration-local/2026-10-01-005-route-rust-final-v2-checks.json`、
`2026-10-01-005-route-python-checks.json`へ保存する。
台帳/Ruff/Markdown/分離起動は`2026-10-01-005-route-static-checks.json`、文書の最終確認は`2026-10-01-005-route-final-checks.json`、
CIの最小変更照合は`2026-10-01-005-route-ci-check.json`、hash監査は`2026-10-01-005-route-audit.json`。
開発runと中間のBlackHole runは別名で保存し、最終v3は同じ最終source/hashで全9取得・3 cancelを再実行した。
開発中の空sumの符号付きzero照合、共有通知のcoalesceを完成窓数と同一視したchecker、
Rust testのJSON macroとClippy/固定配列比較を修正した。失敗run/中間runは削除せず分けて保持する。
旧静的audio runnerも、新moduleを含むsource hashへ広げた。

内部mailbox/係数は固定容量で、controlの文字列/外部snapshot/全process RSSの上限ではない。
callbackはf32のみ。f64元bytesは既存queue回帰で検査したが、動的f64演算の合格ではない。
CPALのcopyするtapはdevice提出buffer。mixedの実取得queue/graph購読、全tap、製品PortAudio共通adapter、
Qt表示、実取得校正/非同期保存、device/host clock写像、USB復帰、排他、長時間、他OSは未確認。
MIG-005全体、最小2chフロー、Rust/QML採用は未完了。次は007-Aの実result表示、または製品共通adapter/全tapへ進められる。
全体Pytest/Mypy/翻訳/全言語UIサイズとGitHub CIは未実施。製品UI/翻訳の変更はない。

再実行:

```bash
./.venv/bin/python scripts/migration_audio_route.py --report .migration-local/005-route-new.json
./.venv/bin/python scripts/migration_audio_route.py --virtual-device --output .migration-local/005-route-blackhole-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_audio_route.py
```

## MIG-005取得graph接続の成果と検証（前回記録）

着手: 2026-10-01、HEAD `ab0c6247`。006-Eはremote一致・cleanで保存済みだった。
同じworktreeで`codex/migration-005-graph`へ分岐。005-route着手時に`8f1d1362`へ保存済み・remote一致を確認した。
変更境界はaudio queue→graph接続、CPAL診断、独立runner/test/CI、検証文書。
現行Python DSP/UI、003-A/B/Cの入力・期待値・契約・許容差を変更していない。
Cargo lockはgraph-core→audio-core、audio-probe→graph-coreのローカル依存2行だけを更新した。

- [取得worker](../native/graph-core/src/acquisition.rs)は一つのinput.raw queue、明示ID/port binding、
  worker所有履歴、固定N/hopの共有FFT schedulerを持つ。表示とは独立にpollし、内部購読は作らない。
  f32/f64の元bits/絶対frame位置/flags/backend secondsを保持。Timebase原点/不確かさはunknown。
- dequeue数と完成窓数を別に制限し、大きなgapでもpoll上限を守る。
  Historyへ末尾gapを明示し、欠落窓に数値を作らない。未読表示/cache/平均をresetし、旧jobをfenceする。
  nonfiniteはchannel別reason、未解釈のflagsはunsupported＋元flagsを保持する。
- restartは新queue/formatを検証してから旧世代の公開をfenceする。旧callback queueは再利用しない。
  失敗時は現履歴/queue/未読resultを維持する。worker失敗はFailed(reason)、stop/破棄は冪等で回収する。
- [保存比較runner](../scripts/migration_audio_graph.py)は003-Bの4/8ch f32/f64元bytesを、
  identity/逆順bindingの8件で実queue→履歴→共有FFTへ通す。
  全元bitsと保存FFT数値、2view＋保存tokenの同じallocation/ID・評価1、sessionだけの続行、
  最後の解除後の回収、履歴失効/停止後に保持したsnapshotの不変性を検査する。
- [CPAL診断](../native/audio-probe/src/main.rs)も同じ取得workerを利用する。
  callbackへのgraph/FFT追加はなく、通常の制御loopがN=1024/hop=512/symmetric Hannを解析する。
  [BlackHole runner](../scripts/migration_audio_virtual.py)で全完成窓の評価1、2購読の共有、unknown時刻、
  停止後のnode/cache/subscription/in-flight回収とPreparing中cancelを検査する。
- [決定0014](decisions/0014-acquisition-history-shared-fft.md)、[再検査手順](../native/acquisition-candidate.md)、
  P02/P03/P15、ACの範囲と作業票を更新した。独立CIへbuild/portable比較を追加。GitHub実行は未確認。

最終report: `.migration-local/2026-10-01-005-graph-final.json`。
4入力×2bindingの8ケースすべて合格。最大complex絶対差はf64約1.57e-14、f32約8.35e-9。
queue/poll raw/履歴/停止後に保持したsnapshotは期待するport順の元bytesと完全一致。

| 確認 | 結果 |
| --- | --- |
| 保存入力・共有・回収 | 8ケース成功。2view＋保存tokenのFFT評価1、session継続、最後の解除とstop後の回収 |
| 最小Python環境 | `.migration-local/2026-10-01-005-graph-minimal.json`。Python 3.12.14/NumPy 2.2.6＋pipだけで同じ8件成功。Qt/FFTW/SciPy/音声依存なし |
| BlackHole実取得 | `.migration-local/2026-10-01-005-graph-blackhole/report.json`。2ch/16ch/4→16/8→16 × 交互3回の24取得・12比較・4 cancel成功 |
| 実取得graph | CPAL 12回、計4748完成窓（各395/396）。各窓の評価1・同じraw allocation、gap 0、XRUN 0、停止後の回収。全sampleの最大入力誤差0 FS |
| Rust test/fmt/Clippy | Graph62＋Audio9＋CPAL request4＋DSP5＋模擬worker5の85 passed。追加12件、workspace formatとpure4 crate/CPALのClippy成功 |
| Python対象回帰 | 219 passed（109.59秒）。新取得境界35件とaudio/virtual/result/graph/history/filter/台帳/分離起動/ring buffer |
| 保存fixture verify | 開始時FFT14、core4 FFT/27契約/4保存、filter21数値/6 rate境界が成功。入力・期待値更新なし |
| main同期 | fetch後もorigin/mainは`9fd79958`。取込み/参照更新不要 |
| Ruff/Markdown/台帳/CI/diff・起動分離 | 成功。627 Python/195 Markdown、41モジュール双方向対応、CI3 jobの取得build/portable、fixture不変、専用state-dirのoffscreen self-test終了0 |
| source/report/hash監査 | 成功。最終/最小環境の配列・数値一致、source/runner/lock/binary hash、全commandのgzip/log hashと終了コード0、CPAL 12経路/4748窓、CI inline Pythonを照合 |

Rust/回帰commandとgzip log/hash/終了コードは
`.migration-local/2026-10-01-005-graph-rust-checks.json`、`2026-10-01-005-graph-python-checks.json`へ保存した。
最終文書/CI/起動検査は`2026-10-01-005-graph-final-checks.json`、hash監査は`2026-10-01-005-graph-audit.json`へ保存した。
開発runは`2026-10-01-005-graph-development.json`、BlackHoleのraw bytes/request/manifestも専用ディレクトリへ保持する。
初期の型/Clippy指摘、runnerのchecked_fileのbytes/path混同、共通conftestがQtをimportするheadless判定を修正した。
headlessは独立processと最小venvで検証する。

このworkerは呼出側が継続pollする単一所有のinput.raw境界。独立した永続thread schedulerではない。
一回のpollは最大8192 delivery/4096窓、履歴payload/spansはHistoryLimitsで制限する。
CPAL診断は1024 delivery/16窓、履歴8192 frame。外部snapshot/全process RSSの上限は別。
BlackHoleは短時間の診断で、定常性能、3×10分、物理clock/遅延精度の合格には数えない。

動的出力route配送、全tap、製品PortAudio共通adapter、Qt表示、実取得resultの校正/非同期保存、
device/host clock写像、USB復帰・排他、長時間、他OSは未確認。
MIG-005全体、最小2chフロー、Rust/QML採用は未完了。次は007-Aの実result表示、または005-Aの動的出力routeへ進める。
全体Pytest/Mypy/翻訳/全言語UIサイズとGitHub CIは未実施。製品UI/翻訳の変更はない。

再実行:

```bash
./.venv/bin/python scripts/migration_audio_graph.py --report .migration-local/005-graph-new.json
./.venv/bin/python scripts/migration_audio_virtual.py --virtual-device --output .migration-local/005-graph-blackhole-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_audio_graph.py tests/logic_verification/test_migration_audio_virtual.py
```

## MIG-006-Eの成果と検証

着手: 2026-10-01、HEAD `633067d7`、006-Dのブランチはremote一致・clean。
前回記録の「006-D未コミット」は古く、このcommitへ保存済みと確認した。
同じworktreeで`codex/migration-006-e`へ分岐。005-graph着手時に`ab0c6247`へ保存済み・remote一致を確認した。
変更境界はgraph-coreのresult/校正/保存、独立runner/test/CI、検証文書。
現行DSP/UI、003-A/B/Cの保存入力・期待値・契約・許容差、Cargo lockは変更していない。

- [不変result](../native/graph-core/src/result.rs): privateなowned documentへ元Stream/generation/ChannelId、
  区間、Timebase、raw result ID、演算条件、trigger/clock写像、取得/結果host時刻、校正、軸/単位、validityを保存。
  raw FFTの全配列と元precisionを保持し、profile変更・世代更新・graph停止/回収後も確定snapshotは不変。
- profileはChannelIdで検索し、並替え後にも同じ係数/binding/revision/適用区間を保持する。
  `input.raw`の解析後にV/FSを適用し、RMS V/dBVとV²/補正HzのPSDを生成。
  未設定/未校正でもFSを保持し、絶対値はnull＋uncalibrated。zeroのdBVと非有限/overflowには別reasonを持つ。
  SPLは全てuncalibrated。mixed/既に校正済みtapへの単純な絶対係数の再適用は拒否する。
- version付き実験用JSON/CSVへ全metadata/配列/shape/precision/null/reasonを保存し、完全再読込する。
  一時fileへの全書込み/flush/fsync後、same-directory hard-linkで既存fileを置換せず公開。
  不正版/重複key/shape/精度/単位/理由・非有限値・校正/trigger/写像の不整合、write/flush/保存先失敗を検査する。
- [保存比較runner](../scripts/migration_result_candidate.py): 保存2校正契約・4交換例と4/8ch × f32/f64の元bytesを検査。
  2view＋保存sessionが同じraw result/allocationを受け、FFT評価1回。両view解除後はsessionが需要を保持し、
  最後の解除/shutdown後にnode/subscription/cache/in-flightが0。保存した値は独立平均や表示間引きに置換しない。
- [決定0013](decisions/0013-result-calibration-exchange.md)と[再検査手順](../native/result-candidate.md)を追加。
  P13/P14、作業票、AC12の検証範囲を更新。独立Rust CIのbuild/portable比較/pathへresultを追加した。
  GitHub上の実行は未確認。

最終report: `.migration-local/2026-10-01-006-e-final.json`。
2校正契約/4保存例、4共有FFT結果、各JSON/CSVのnative/Python readerによる完全一致が合格。
保存FFTの最大complex絶対差はf64約1.57e-14、f32約8.35e-9。RMSの保存理論との差は0。
typed f64の係数/軸補正`1.0`は旧fixtureへの照合時だけ整数`1`の表記へ戻す。
値・係数bits・契約・許容差の変更ではなく、製品file互換の合格としては扱わない。

| 最終確認 | 結果 |
| --- | --- |
| 校正/保存/元bytes/共有 | 2校正契約・4保存例・4/8ch f32/f64すべて合格。JSON/CSVの値/metadata完全再読込、評価1、最後の解除後の回収 |
| 最小Python環境 | `.migration-local/2026-10-01-006-e-minimal.json`。既存Python 3.12.14/NumPy 2.2.6+pipだけのvenvで同じ2/4/4件成功。Qt/FFTW/SciPy/音声依存なし |
| Rust test/fmt/Clippy | Graph50＋Audio9＋CPAL request4＋DSP5＋模擬worker5の73 passed。workspace formatとpure4 crate/CPALのClippy成功 |
| 新Rust境界 | result追加12テスト。ID並替え/旧profile/unknown、不正校正/mixed、zero/非有限/overflow、f32/f64無効窓、世代/shutdown、trigger/写像、重複key/shape/版、容量拒否、保存失敗 |
| Python対象回帰 | 280 passed、2 skipped（108.63秒）。新result33件、既存graph/history/filter/core/FFT/台帳/分離起動/ring bufferと製品校正/export。skipは既存の奇数長Nyquist非該当2件 |
| 保存fixture verify | FFT14、core4 FFT/27契約/4保存、filter21数値/6 rate境界が成功。保存fixture更新なし |
| 起動分離 | 専用state-dirで保存先確認とoffline/offscreen self-test成功、終了コード0。従来のlocale/font警告のみ |
| report整合 | 最終/最小環境/checksのsource/runner/lock/binary、30 commandのgzip/log hashと終了コード0を照合済み |
| Ruff lint/format・Markdown・台帳・CI仕様・diff | 成功。623 Pythonファイル、193 Markdown、41モジュール双方向対応、CI YAML3 jobとresult trigger/build/portable、inline Python、`git diff --check` |
| main同期 | fetch後もorigin/mainは`9fd79958`。取込み/参照更新不要 |

Rust/回帰/保存fixtureの検査commandは`.migration-local/2026-10-01-006-e-rust-checks.json`、
`2026-10-01-006-e-python-checks.json`、`2026-10-01-006-e-reference-checks.json`へ保存。
最終の文書/CI/台帳/Ruff検査は`2026-10-01-006-e-final-checks.json`、
数値/hash監査は`2026-10-01-006-e-audit.json`へ保存する。
開発runは`.migration-local/2026-10-01-006-e-development.json`へ分離した。
Pytestの共通conftestによるQt/audio importは、runnerを独立processで検査して切り分けた。

numeric/軸payloadは4,000,000 scalar、32ch、4096 validity span、読取fileは256 MiBまで。
metadata/allocator/外部snapshot/全process RSSの上限ではなく、大きなFFT resultは保守的な容量検査で明示拒否する。
保存公開にはfilesystemのhard-link対応が必要。directory metadataの電源断耐性や複数fileの一括commitは未保証。
今回deviceは開かず、通常音声テストのBlackHole 16ch／2ch優先という引継ぎを維持する。

006-Eの完了はAC12のpure不変result/基本校正/交換形式/保存失敗まで。
現行製品CSV/JSON importer、非同期保存worker/cancel、実取得/永続scheduler/Qtのsave session、
SPL/周波数・位相map/実device校正、長時間/steady-state/他OSは未確認。
MIG-006全体や最小2chフロー、Rust/QML採用の完了には数えない。
全体Pytest/Mypy/翻訳/全言語UIサイズとGitHub CIは今回未実施。製品UI/翻訳の変更はない。
次は005-A/Bの取得queue/graph接続、または007-Aの実result表示境界へ進める。

再実行:

```bash
./.venv/bin/python scripts/migration_result_candidate.py --report .migration-local/006-e-new.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_result_candidate.py
```

## MIG-006-Dの成果と検証（前回記録）

着手: 2026-09-30、HEAD `a0d1bdb6`、006-Cのブランチはremote一致・clean。
前回記録の「006-C未コミット」は古く、このcommitへ保存済みと確認した。
同じworktreeで`codex/migration-006-d`へ分岐。006-E着手時に`633067d7`へ保存済み・remote一致を確認した。
変更境界はgraph-coreのfilter/rate stateと派生世代fence、独立runner/test/CIと検証文書。
現行DSP/UI、003-A/B/Cの保存入力・係数・期待値・契約・許容差、Cargo lockの変更なし。

- [filter/rate](../native/graph-core/src/filter.rs): 絶対位置と有理数phaseを保持する因果FIR/中心補償polyphase、
  保存SOS係数の因果DF-II state。前後方向SOSは明示した完全配列adapterへ分離する。
- [共有graph](../native/graph-core/src/lib.rs)が一つのfilter stateを所有する。
  最後の購読解除/shutdownで回収し、親Streamのgeneration fenceを派生Streamと旧Completionへ伝播する。
  重複/連鎖/不正Source/容量超過を拒否し、失敗時にstateを維持する。
- FIRのgap/元validity/channel/reasonをsupportへ拡張し、端点paddingをwarmupとして保持する。
  trigger1024→512、信号遅延1/2 output sample、原点/処理遅延のunknownを丸めたり0へ補わない。
  無効窓はFFT数値を公開せず、独立平均をresetする。SOSは全区間zero-state warmup、gap/無効入力は明示拒否。
- [保存比較runner](../scripts/migration_filter_candidate.py): f64のFIR5/polyphase12/SOS4を、
  whole/1/127/256/不規則chunkで保存理論/現行へ比較する。出力/最終stateはchunk間でbytes一致。
  元入力と保存係数だけを候補へ渡し、manifest全体・source/generator/契約・全133ファイルのhashを検査する。
- filter出力→worker所有履歴→共有FFTの13,980窓を検査。
  12,985の有効窓で各FFT評価1、2購読の同一ID/allocation。995無効窓は数値なし/平均reset。
  有効窓のある各ケースは最初のcomplex FFTを保存理論出力の独立NumPy FFTへ照合する。
- [決定0012](decisions/0012-filter-rate-graph.md)と[再検査手順](../native/filter-candidate.md)を追加し、
  P06台帳/作業票を更新。独立Rust CIへbuild/Clippy/NumPy-only比較とfilter変更pathを追加。GitHub実行は未確認。

最終report: `.migration-local/2026-09-30-006-d-final.json`。
最大絶対差はFIR約2.78e-17 FS、polyphase0 FS、SOS出力/state/複素応答約2.12e-15。
共有FFTの最大complex絶対差は約2.87e-17。許容差は変更していない。
Serde JSONの既定parserで保存係数の1 ULP差を検出し、既存1.0.151の`float_roundtrip`で解消した。
係数bitsをSourceの同一性にも含め、別kernelが同じrevision名で共有されることを防ぐ。

| 最終確認 | 結果 |
| --- | --- |
| 保存数値/phase/state/validity | 21ケース×5 chunkと6 rate境界が合格。FIR gap `[100,104)`→`[50,53)`、warmup `[0,1)`、trigger/遅延一致 |
| 最小Python環境 | `.migration-local/2026-09-30-006-d-minimal.json`。既存NumPy 2.2.6+pipだけのvenvで同じ21×5/6件が成功。SciPy/Qt/FFTW/音声依存なし |
| Rust test/fmt/Clippy | Graph38＋Audio9＋CPAL request4＋DSP5＋模擬worker5の61 passed。workspace formatとpure4 crate/CPALのClippy成功 |
| 新規graphテスト | 006-D追加11件。1/2/4/8ch FIRの独立有限和、任意chunk、gap/末尾gap、原点、非有限/元validity、容量拒否の原子性、SOS state、世代と回収 |
| Python対象回帰 | 265 passed in 89.63s (0:01:29)。新filter境界37件と既存history/graph/audio/core/filter/台帳/起動分離/ring buffer |
| 保存fixture verify | 開始時FFT14、core4 FFT/27契約/4保存、filter21数値/6 rate境界が成功。保存fixture更新なし |
| 起動分離 | 保存先確認とoffline/offscreen self-test成功。従来のlocale/font警告のみ |
| report整合 | 最終/最小環境/検査commandのgzip/log hash/終了コード0、source/runner/lock/binary hashを照合済み |
| Ruff lint/format・Markdown・台帳・CI仕様・diff | 成功。619 Pythonファイル、191 Markdown、41モジュール双方向対応、CI YAML3 jobとfilter trigger/build/portable/inline Python、`git diff --check`を確認 |
| main同期 | fetch後もorigin/mainは`9fd79958`。取込み/参照更新不要 |

Rust検証は`.migration-local/2026-09-30-006-d-rust-checks.json`、
Python回帰は`.migration-local/2026-09-30-006-d-python-checks.json`、
その他検査は`.migration-local/2026-09-30-006-d-final-checks.json`、
数値/hash監査は`.migration-local/2026-09-30-006-d-audit.json`へ保存する。
開発比較は`.migration-local/2026-09-30-006-d-development.json`、診断出力は`.migration-local/006-d-debug/`へ分離した。
実装中の構文/型/Clippy指摘、readerのJSON空白比較、テストの共有辞書変更とFFT件数固定を修正した。

容量は32ch/4097 FIR係数/16 SOS section、callごとの入力65536 frame（gap込み）/出力131072 frame、
4096 validity spanで制限する。FIR履歴は有限supportだけ。metadata/allocator/外部snapshot/全process RSSは別。
今回deviceは開かず、以後の通常音声テストはBlackHole 16ch／2chを優先する引継ぎを維持する。

006-Dはf64保存コーパスと一段のpure graphに対するAC10/14まで。
SOSのgap回復、f32 filter、全rate/filter・chain、実取得/永続scheduler/Qt、物理clock/処理遅延、
release/steady-state/長時間/他OSは未確認。MIG-006全体やRust/QML採用の完了には数えない。
全体Pytest/Mypy/翻訳/全言語UIサイズとGitHub CIは今回未実施。製品UI/翻訳の変更はない。
次は006-Eの不変result・channel校正・CSV/JSON来歴、または005-A/Bの取得/graph統合へ進められる。

再実行:

```bash
./.venv/bin/python scripts/migration_filter_candidate.py --report .migration-local/006-d-new.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_filter_candidate.py tests/logic_verification/test_migration_history_candidate.py tests/logic_verification/test_migration_graph_candidate.py
```

## MIG-006-Cの成果と検証（前回記録）

着手: 2026-09-30、HEAD `f9ff4558`、005-virtualのブランチはremote一致・clean。
前回記録の「005-virtual未コミット」は古く、このcommitへ保存済みと確認した。
同じworktreeで`codex/migration-006-c`へ分岐。006-D着手時に`a0d1bdb6`へ保存済み・remote一致を確認した。
変更境界はgraph-coreのhistory/timeと世代公開境界、独立runner/test/CI、検証文書。
保存003-A/B/Cの入力/期待値/契約/許容差、現行DSP/UI、既存DSP/audio実装、Cargo lockの変更なし。

- [実履歴](../native/graph-core/src/history.rs): frame容量・numeric bytes・validity span数を制限したworker所有buffer。
  任意chunkから独立readerと非消費trigger queryへowned snapshotを渡し、retention後も値を維持する。
  gap/pending/負位置/floorと分数残差を正確に返す。source revision境界をまたぐ窓は明示拒否する。
- [正確な時刻](../native/graph-core/src/time.rs): 有理数の原点/rateと世代付きclock写像。
  未知原点はunknown、別clockの写像なし/期限切れ/世代不一致はunsynchronized。
  不確かさNoneを0で補わず、checked演算の表現超過も明示拒否する。
- [共有graph](../native/graph-core/src/lib.rs)へsnapshotだけを渡す。gap/pendingはFFT jobを作らず、
  validity spanは無効数値と平均resetへ伝播する。restartは新構成を検証してからgraphへ世代fenceを入れる。
  旧event/reader/block/cache/reconfigureを拒否し、計算済みの旧Completionも新世代へ公開しない。
  外部が保持した確定snapshotの寿命は維持する。
- [保存比較runner](../scripts/migration_history_candidate.py): 保存履歴9/時刻4契約を完全一致で比較。
  4/8ch × f32/f64の4入力bytesを1/127/256/17 frameから復元し、遅いreaderとretention後にも元bytesを保持する。
  同じFFT結果を2購読へ渡し、保存理論/現行数値、Source/区間/同一ID/allocation、停止後の回収を検査する。
- [決定0011](decisions/0011-history-timebase-graph.md)と[再検査手順](../native/history-candidate.md)を追加。
  独立Rust CIへharness build/portable比較と変更pathを追加。GitHub実行は未確認。

最終report: `.migration-local/2026-09-30-006-c-history-final.json`。
保存13契約と4入力bytes/FFT比較が成功。最大正規化complex差はf64約1.57e-14、f32約8.35e-9。
各FFT評価1、2購読の同一ID/allocation、終了後node/subscription/cache/in-flight数0。
容量上限は内部の保持numeric payloadとspan数で、metadata/allocator/外部snapshot/全process RSSは別。
今回deviceは開かず、BlackHole 16ch／2ch優先という音声テストの引継ぎは維持する。

| 最終確認 | 結果 |
| --- | --- |
| 保存履歴/時刻/元bytes | 13契約と4/8ch f32/f64の4件すべて合格。snapshot/delayed/retention後の全bytes一致 |
| 最小Python環境 | `.migration-local/2026-09-30-006-c-minimal.json`。既存NumPy 2.2.6+pipだけのvenvで同じ13+4件成功、Qt/FFTW/音声依存なし |
| Rust test/fmt/Clippy | Graph27＋Audio9＋CPAL request4＋DSP5＋模擬worker5の50 passed。workspace formatとpure4 crate/CPALのClippy成功 |
| 新規graphテスト | 006-C追加11件。独立cursor/通知遅延/正確なgap、所有snapshot、世代fence、失敗restartの原子性、validity、写像期限。4/8ch両精度の断続取得を独立frame集合oracleと照合 |
| Python対象回帰 | 237 passed（34.20秒）。新履歴境界27件と既存graph/audio/core/filter/FFT/台帳/起動分離/ring buffer |
| 共有graph保存回帰 | `.migration-local/2026-09-30-006-c-graph-regression.json`。元の18ケースすべて数値/共有/回収が合格 |
| 保存fixture verify | FFT14、core4 FFT/27契約/4保存、filter21数値/6 rate境界が成功。入力・期待値の変更なし |
| 起動分離 | 保存先確認とoffline/offscreen self-test成功。従来のlocale/font警告のみ |
| report整合 | 最終/最小環境/共有回帰/Rust検査の34 commandのgzip/log hash/終了コード0、source/runner/lock/binary hashを確認 |
| Ruff lint/format | 成功、615 Pythonファイルのformat確認 |
| Markdown lint・台帳・CI仕様・diff | 成功。189 Markdown、41モジュール双方向対応、CI YAML3 jobとhistory trigger/build/portable経路、inline Python、`git diff --check` |
| main同期 | fetch後もorigin/mainは`9fd79958`。取込み/参照更新不要 |

Rust検証は`.migration-local/2026-09-30-006-c-rust-checks.json`、
数値/hash監査は`.migration-local/2026-09-30-006-c-audit.json`に保存する。
開発runは`.migration-local/2026-09-30-006-c-development.json`へ分離した。
初回harnessの所有権に関するコンパイルエラー2件とClippyのmanual_pop_if指摘1件を修正した。
CI構文確認はPython環境にPyYAMLがなかったため、既存Ruby YAML parserとPython compileで確認した。

006-Cの完了はAC08/09のworker所有履歴/Timebase/世代とpure共有graphまで。
取得queue/永続scheduler/CPAL・PortAudio/Qtとの接続、実clockの推定/物理遅延/外部trigger、
trigger付きMeasurementResultの保存、release/steady-state/長時間/他OSは未確認。
全体Pytest/Mypy/翻訳/全言語UIサイズとGitHub CIは今回未実施。製品UI/翻訳の変更はない。
Rust/QMLの採用やMIG-006全体の完了には数えない。006-D/Eへ進められる。

再実行:

```bash
./.venv/bin/python scripts/migration_history_candidate.py --report .migration-local/006-c-new.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_history_candidate.py tests/logic_verification/test_migration_graph_candidate.py
```

## MIG-005仮想デバイスの成果と検証（前回記録）

着手: 2026-09-30、HEAD `3fc00cbf`、005-A/Bのブランチはremote一致・clean。
前回記録の「005-A/B未コミット」は古く、このcommitへ保存済みと確認した。
同じworktreeで`codex/migration-005-virtual`へ分岐。今回の変更は未コミット。
変更境界はCPAL診断adapter、独立runner/test/CI、検証文書。製品DSP/UIと保存fixtureは変更していない。

ユーザーの引き継ぎ指示: UAC-232はひとまず実機で動作確認済み。以後はBlackHole 16ch／2chでよい。
通常の音声回帰・channel対応・mute・開始／停止・再オープンはこの2台を使う。
UAC-232は物理ADC/DAC・hardware gain／電圧／配線・USB復帰・物理遅延など実機が必要な要件だけ。
仮想で確認できない項目だけを未確認として残し、依存しない工程を進める。
[環境の引き継ぎ](environment.md#音声テストの引き継ぎ)と[決定0010](decisions/0010-blackhole-virtual-audio.md)へ同じ方針を記録した。

- [CPALプローブ](../native/audio-probe/src/main.rs): 1〜16の入力／出力数、複数source、
  明示gain行列、mute区間を追加。[request検証](../native/audio-probe/src/lib.rs)はdevice open前に行う。
  既存UAC-232のrequestとL-only出力の既定値を維持する。
- [仮想device runner](../scripts/migration_audio_virtual.py): 完全一致のBlackHole 2ch／16chだけを使い、
  `--virtual-device`と新規出力先を要求する。system default deviceへfallbackしない。
- 2chは既存AudioEngine、16chは直接PortAudio streamとCPALを交互に比較する。
  全16port identity、4／8ch→16portの並替え・複製・mix・zeroを検査する。
  製品AudioEngineのN-channel化や動作中のroute配送は行っていない。
- 48 kHz／256 frame／f32／4秒、各sourceの異なるtoneと固定marker、区間mute。
  事前許容差は全sample絶対差2e-6 FS、channel間marker差1 frame、backend振幅差0.1 dB。
  元source、raw入力／device提出出力、時刻、XRUN、source/binary/lock/log hashをローカルへ保存する。

初回開発runの16ch PortAudio取得1件でunderflow8件と最大約0.00317445 FSの波形差を検出し不合格。
開始時のBlackHole 16chは96 kHz。PortAudio側で48 kHzのdevice設定変更と変換時の拒否を明示し、
再度96 kHzで開いて閉じた状態から再検証した。開発runは
`.migration-local/2026-09-30-005-virtual-development/`、準備記録は
`.migration-local/2026-09-30-005-virtual-rate-setup.json`に保持する。

最終report: `.migration-local/2026-09-30-005-virtual-validated/report.json`。
全24取得・12比較・準備中cancel4件が合格。全portの最大波形差0 FS、backend振幅差0 dB、
channel間marker位置差0 frame。muteと無音portも一致。XRUN／backend error／queue gapは0。
最終CPAL queue最大深さは入力2048／出力512 frame（容量各8192）。
これは短いheadless診断で、同等GUI負荷の性能比や10分3回の合格ではない。

| 最終確認 | 結果 |
| --- | --- |
| 仮想device取得 | BlackHole 2chと16ch identity、4／8ch→16port routeをPortAudio／CPAL各3回。24取得／12比較／cancel4件合格 |
| Rust test/fmt/Clippy | Audio9＋CPAL request4＋Graph16＋DSP5＋模擬worker5の39 passed。workspace formatとpure4 crate／CPALのClippy成功 |
| Python対象回帰 | 202 passed（21.30秒）。新仮想checker16件と既存audio／core参照／graph／起動分離／台帳／AudioEngine |
| 保存fixture verify | FFT14、core4 FFT／27契約／4保存、filter21数値／6 rate境界が成功。入力・期待値の変更なし |
| 起動分離 | 保存先確認とoffline/offscreen self-test成功。従来のlocale／font警告のみ |
| report整合 | 最終source／binary／lockとraw全24取得、cancel manifest4件、build／CPALの17 commandのgzip／log hash／終了コード0を確認 |
| 保存音声候補の回帰 | 10契約例と4／8ch f32／f64の4入力bytesが成功。元fixtureの変更なし |
| Ruff lint／format | 成功。611 Pythonファイルのformat確認 |
| Markdown lint・台帳・CI仕様・diff | 成功。187 Markdown、41モジュールの双方向対応、CI YAML3 jobとdevice不要のCPALテスト追加、`git diff --check` |
| main同期 | fetch後もorigin/mainは`9fd79958`。取込み／参照更新不要 |

数値／hash監査は`.migration-local/2026-09-30-005-virtual-audit.json`、
Rust検証3 commandは`.migration-local/2026-09-30-005-virtual-rust-checks.json`に保持する。

再実行:

```bash
./.venv/bin/python scripts/migration_audio_virtual.py --virtual-device --output .migration-local/blackhole-new-run
./.venv/bin/pytest -q tests/logic_verification/test_migration_audio_virtual.py tests/logic_verification/test_migration_audio_candidate.py
```

USB抜き差し、物理出力／電圧校正、物理遅延、排他、長時間、他OSは未確認。
動的route配送、永続scheduler、PortAudio／Rustの製品共通adapter、graph／Qt接続、時刻写像は残る。
再オープン時のgeneration metadataは確認するが、旧世代event拒否の実装検証とは区別する。
MIG-006-Cの実履歴／Timebase／旧世代拒否へ進められる。
全体Pytest/Mypy/翻訳/全言語UIサイズとGitHub CIは今回未実施。製品UI／翻訳の変更はない。

## MIG-005-A/Bの成果と検証（前回記録）

着手: 2026-09-30、HEAD `41d3a534`、006-Bのブランチはremote一致・clean。
前回記録の「006-B未コミット」は古く、このcommitへ保存済みと確認した。
同じworktreeで`codex/migration-005-a`へ分岐。今回の変更は未コミット。
変更境界はaudio用native2 crate、workspace/lock、独立runner/test/CIと検証文書。
現行DSP/UI、003-A/B/Cの保存入力・期待値・許容差、既存DSP/graph実装は変更していない。

- [音声境界](../native/audio-core/src/lib.rs): 独立した入出力数/port binding、明示gain行列、
  routeの検証/拒否とblock境界ack、mixed/device_bufferの分離、世代/形状/gap検証。
- f32/f64の容量制限付き1 producer/1 consumer queue。事前確保したatomic slotを上書きし、
  readerへ最古frameの正確なgapを返す。callbackにalloc/lock/file/graph処理を置かない。
  数値payload/queue容量の上限とworkerのowned snapshot/RSSの上限は分ける。
- [保存比較runner](../scripts/migration_audio_candidate.py): 003-Bの10例と、4/8ch f32/f64の4入力。
  期待値を候補processへ送らず、元bytes・論理ID/順序・sample位置を完全照合した。
- [CPAL probe](../native/audio-probe/src/main.rs)と[実機runner](../scripts/migration_audio_hardware.py):
  現行AudioEngine/PortAudioとCPAL 0.18.2をrelease候補で交互に測定。
  raw入力/提出出力、XRUN、時刻、状態、source/binary/lock/log hashをローカルへ保存。
- [決定0009](decisions/0009-audio-boundary-uac232.md)と[手順](../native/audio-boundary.md)を追加。
  pure Rust CIとNumPy-only比較を拡張し、Qtに依存しないCPAL/ALSA buildジョブも追加。
  GitHub実行は未確認。

実機はCore Audioの`ZOOM UAC-232`、2入力/2出力。
配線は出力Lを分岐し、−20 dB attenuator経由で入力L、直結で入力R。出力Rは未接続。
48 kHz/256 frame/f32/4秒/1 kHz、出力peak −30 dBFS、固定markerと区間muteを使った。
事前許容差はbackend振幅差0.1 dB、attenuator公称差1 dB、L/R marker差1 sample、
backend相対phase差1度、mute tone低下60 dB。入力電圧/attenuator/hardware gainは未校正。
ユーザーの指示で今回は接続したまま測定し、USB抜き差しは行わない。

最終report: `.migration-local/2026-09-30-005-b-uac232-validated/report.json`。
全6取得・3比較・CPAL準備中cancelが合格。入力L/R差は−20.0135〜−20.0264 dB。
最大backend振幅差0.0126094 dB、相対phase差0.000703度、L/R marker差は全runで0 sample。
mute tone低下は99.567 dB以上。queue gap/CPAL error/XRUNは0、現行のこのrunのstatusは0。
予備playrecでは入力underflow1件があり、開発/修正確認runと分けて保持している。

| 3回の最終sample | PortAudio | CPAL |
| --- | --- | --- |
| 入力L/R差 dB | −20.014264 / −20.014026 / −20.014190 | −20.014382 / −20.013488 / −20.026424 |
| 停止 wall ms（2回stop/pauseとclose/dropを含む） | 278.668 / 274.337 / 261.156 | 90.408 / 95.042 / 87.170 |
| callback p99 ms | 0.229 / 0.175 / 0.189 | 入力上限0.03 / 0.04 / 0.03、出力上限0.04 / 0.03 / 0.03 |

短いheadless診断値で、同等GUI負荷の性能比や通知p95予算の合格ではない。
最終CPAL queue最大深さは入力1792/1792/1536、出力511/511/512（容量各8192）。
SeqCstの安全性とこの短い負荷での成功を、backend全体のRT保証に置き換えない。

raw ADC/DAC marker時刻差はPortAudio約−3.54〜−3.46 ms、CPAL約−1.05〜−1.01 msと負値。
backend時刻の原点/latency補正/不確かさが未検証のため、`physical_delay_ms=null`、
物理遅延の精度はunknown。未知の時刻写像を同期済み・精度合格にしていない。

| 最終確認 | 結果 |
| --- | --- |
| 保存候補比較 | `.migration-local/2026-09-30-005-a-final.json`。10契約例と4/8ch f32/f64の4元入力bytesが成功 |
| Rust test/fmt/Clippy | Audio9+Graph16+DSP5+模擬worker5の35 passed。workspace formatとpure4 crate/CPALのClippy成功 |
| Python対象回帰 | 170 passed（12.52秒）。新規18件、既存core/graph/起動分離/audio engine |
| 保存fixture verify | FFT14、core4 FFT/27契約/4保存、filter21数値/6 rate境界すべて成功。入力・期待値更新なし |
| 起動分離 | 保存先確認とoffline/offscreen self-test成功。従来のlocale/font警告のみ |
| Ruff lint / format | 成功、608 Pythonファイルのformat確認 |
| 実機report整合 | 最終source/binary/lock、全コマンドのgzip/log hash/終了コード0を確認 |
| Portable比較 | 保存10例+4/8ch f32/f64の4件成功。NumPy-only CI経路を追加、今回の新規最小venv再実行は未実施 |
| Markdown lint・台帳・diff・CI仕様 | 成功。186 Markdownファイル、41モジュール双方向対応、YAML3 job/inline Python、ローカルリンクとdiffを確認 |
| main同期 | fetch後もorigin/mainは`9fd79958`。取込み/参照更新不要 |

005-Aの完了範囲はpure boundary・保存数値/queueとCPAL基本adapter。
callbackへの動的route配送、永続scheduler、PortAudio/Rust共通adapter、実graph/Qt接続は未実装。
005-Bは短い物理2ch・mute・start/二重stop/cancelまで。
切断復帰・排他・正確なXRUN区間・出力R・絶対遅延、10分3回、他OS、P2全体・採用は未確認。
全体Pytest/Mypy/翻訳/全言語UIサイズは未実施。製品UI/翻訳の変更はない。

再実行:

```bash
./.venv/bin/python scripts/migration_audio_candidate.py --report .migration-local/005-a-new.json
./.venv/bin/python scripts/migration_audio_hardware.py --hardware --output .migration-local/uac232-new-run
./.venv/bin/pytest -q tests/logic_verification/test_migration_audio_candidate.py
```

## MIG-006-Bの成果と検証

着手: 2026-09-30、HEAD `4c6ea93e`、006-Aのブランチはremote一致・clean。
前回記録の「006-A未コミット」は古く、`60474671`で実装、`4c6ea93e`までにreport整理済みと確認した。
同じworktreeで`codex/migration-006-b`へ分岐。今回の変更は未コミット。
変更境界は`native/graph-core`、workspace/lock、独立runner/test/CIと検証文書。
現行DSP/UI、003-A/B/Cの保存入力・期待値・許容差、006-AのDSP実装は変更していない。

- [pure graph](../native/graph-core/src/lib.rs): owned入力→共有FFT→購読別PSD平均/最新snapshotの固定DAG。
  Source/Timebase・signal条件の完全比較、同一allocation/ID、nonCloneの購読tokenを追加。
- node/subscription/in-flight数、N/channel数、cache結果数/numeric bytesを制限。
  未保持cacheを先に外し、表示の最新snapshot置換と測定gapを分ける。
- Job/Completionを解析workerで実行し、公開時に需要とincarnationを再確認。
  最後の解除、旧世代、同key再購読、shutdown/dropでも不要nodeが復活しない。
  in-flight結果と外部に保持する公開済みsnapshotは寿命を保ってから解放する。
- [比較runner](../scripts/migration_graph_candidate.py): 18ケースの元input bytesを解析threadへ渡し、
  理論/現行数値、共有、metadata、終了時回収を検査。NumPyだけのportable環境でも成功。
- [決定0008](decisions/0008-shared-fft-graph.md)と[再実行手順](../native/shared-graph.md)を追加。
  非Qtの独立CIへgraph test/build/Clippyとportable比較を追加。GitHub実行は未確認。

| 最終確認 | 結果 |
| --- | --- |
| 共有数値比較 | `.migration-local/2026-09-30-006-b-graph-final.json`。小規模14+4/8ch 4件すべて理論/現行へ合格。各FFT評価1、同一result ID/allocation、解除/shutdown後node/subscription/cache/in-flight数0 |
| 最小Python環境 | `.migration-local/2026-09-30-006-b-minimal.json`。既存のNumPy 2.2.6+pipだけのvenvでportable18件成功。Qt/FFTW/音声依存なし |
| Rust test/fmt/Clippy | `.migration-local/2026-09-30-006-b-rust-checks.json`。Graph16+DSP5+模擬worker5の26 passed、workspace formatとpure3クレートのClippy成功 |
| Python対象回帰 | 177 passed（27.59秒）。新graph境界21件と既存FFT/core/filter/台帳/起動分離 |
| 保存fixture verify | FFT14+拡張6、core 4 FFT/27契約/4保存、filter 21数値/6 rate境界すべて成功。保存入力・期待値の更新なし |
| 起動分離 | 設定保存先とRust 1.98.1を確認。Python offline/offscreen self-test成功、終了コード0。従来のlocale/font警告のみ |
| report/log整合 | 最終数値18+最小環境18とbuild/checkを含む41コマンドのgzip/hash/終了コード0、現source/runner/実行物hashを確認 |
| Ruff lint / format | 成功、603 Pythonファイルのformat確認。初回の新テストS603は呼出し条件を確認・明記して解消 |
| Markdown lint・台帳・diff | 成功。184 Markdownファイル、41モジュールの双方向対応、変更文書の100ローカルリンク、`git diff --check`を確認 |
| main同期 | fetch後もorigin/mainは`9fd79958`。差分なし、取込み/参照更新不要 |

最大正規化complex FFT差はf64約5.99e-14、f32約8.35e-9。許容差は変更していない。

AC05/06とAC07のpure graph/node/cache/in-flight所有権までが006-Bの検証範囲。
Job実行はcaller-owned threadで、永続scheduler・実取得queue・音声callback/実保存・QML adapterは未実装。
cacheのbyte上限はgraph所有のnumeric payloadだけで、外部snapshotやprocess RSSの上限ではない。
trigger/historyは006-C、filterは006-D、校正/保存は006-E。拡張6件のgraph比較、release、10分連続、
描画性能、他OS、実機、P2全体・Rust/QML採用は未確認。
全体Pytest/Mypy/翻訳/UIサイズは未実施。製品UI/翻訳を変更していない。

再実行:

```bash
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p graph-core
./.venv/bin/python scripts/migration_graph_candidate.py --report .migration-local/006-b-verify.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_graph_candidate.py
```

## MIG-006-Aの成果と検証（前回記録）

着手: 2026-09-30、HEAD `e0b992ce`、004-Bのブランチはremote一致・clean。
statusの004-B欄には未コミットとあったが、開始時にcommit済みであることを確認した。
同じworktreeで`codex/migration-006-a`へ分岐。今回の変更は未コミット。
変更境界は`native/dsp-core`、独立runner/test/CI、`migration/`の記録。
現行DSP/UI、003-A/B/Cの保存入力・期待値・許容差は変更していない。

- [純粋FFT候補](../native/dsp-core/src/lib.rs): RealFFT 3.5.0 / RustFFT 6.4.1、f32/f64、
  boxcar/symmetric Hann、N-channel、FS peak/coherent bin RMS/時間RMS、PSD/ASD、inverse。
- [比較runner](../scripts/migration_fft_candidate.py): 元の`input.bin`をRustへ渡し、保存済み理論値と現行値の両方へ比較。
  schema/ID順/shape/dtype/単位/hash/有限性を検査。phase/dBは定義した閾値を守る。
- [編集反復runner](../scripts/migration_fft_iteration.py): 専用sourceコピー/targetで同じ係数分岐変更を5回。
  元checkoutとfixtureを編集せず、Rustテストと全24比較まで測る。5回すべて成功。
- [決定0007](decisions/0007-pure-fft-candidate.md)と[再実行手順](../native/fft-candidate.md)を追加。
- 非Qtの独立CIへDSP test/ClippyとNumPyだけのportable比較18件を追加。GitHub実行は未確認。

数値比較は小規模14件、4/8ch 4件、拡張6件すべて合格。
最大正規化FFT差はf64約1.33e-13、f32約8.35e-9。許容差の変更なし。
AC01は同じ入力に対するFFT部分、AC04は保存コーパスに対する候補の数値合格。
f32の保存参照はN=4096の2/4/8chで、f32拡張/endpoint全構成は今回追加していない。
実音声経路、route、共有graph、GUI、実機、他OS、release/steady-stateは別の未完了範囲。

| 最終確認 | 結果 |
| --- | --- |
| 候補数値比較 | ローカルreport: `fixtures/runs/2026-09-30-intel-candidate-fft.json`。小規模14/4・8ch 4/拡張6件すべて理論・現行の両方へ合格 |
| コア編集反復 | ローカルreport: `benchmarks/results/2026-09-30-006-a-intel.json`。5回すべてRust5テストと24比較成功、DSP再コンパイルを確認 |
| 編集時間 | 26.093/24.544/24.770/24.493/24.453秒。中央値24.544、min/max 24.453/26.093、母標準偏差0.621秒。絶対30秒目安内 |
| report/log整合 | 採用反復の161コマンド、単独数値24/最小環境18を含む205コマンドのgzip/hash/終了コード0を確認 |
| 最小Python環境 | ローカルreport: `fixtures/runs/2026-09-30-intel-candidate-minimal.json`。NumPy+pipのみでportable数値比較18件成功。Qt/FFTW/音声依存なし |
| Rust build/fmt/Clippy | workspaceで成功。既存CXX-Qtの空init archive/重複rpathのlink警告は残る。ソースlint警告なし |
| Rust test | DSP5件、模擬worker5件、合計10 passed |
| Qt境界回帰 | ローカルreport: `qt/2026-09-30-intel-006-a-regression.json`。新lockで両方式の共通QML寿命検査各1回成功 |
| Python対象回帰 | 216 passed、2 skipped（33.48秒）。新runner/反復/異常系25件を含む。skipは既存の奇数長Nyquistの該当しない組合せ |
| 保存fixture verify | FFT小規模14/拡張6、core 4 FFT/27契約/4保存、filter 21数値/6 rate境界すべて成功。入力・期待値の変更なし |
| 起動分離 | 参照設定とRust1.98.1を確認。Python offline/offscreen self-test成功、終了コード0。従来のlocale/font警告のみ |
| Native CI仕様 | YAML 2 job/inline Pythonと、pure DSPの最小依存経路をローカル確認。GitHub実行は未確認 |
| Ruff lint / format | 成功、599 Pythonファイルのformat確認 |
| Markdown lint・台帳・diff | 成功、182 Markdownファイル、41モジュールの双方向対応、変更文書のローカルリンク、`git diff --check`を確認 |
| main同期 | 終了時fetch後もorigin/mainは`9fd79958`。取込み・参照更新不要 |

初回の編集反復は他のbuild/testと重なったのでローカルの`benchmarks/results/2026-09-30-006-a-development.json`へ分離し、
採用run中は他のagent build/testを止めた。電源状態・他アプリ負荷の時系列は未記録。
実装中のコンパイル失敗1回とClippy失敗2回は[決定0007](decisions/0007-pure-fft-candidate.md)へ記録した。
単独数値比較全体33.095秒/Python親peak RSS 473,767,936 bytesは診断値で、Rust FFT単体の性能値ではない。

006-Aの完了は保存コーパスの数値合格とIntel/debugの編集反復記録まで。
Python同等編集、GUIへの波及、release/10分連続、Rust子RSS、物理I/O、他OS、AC16全体は未確認。
全体Pytest/Mypy/翻訳/現行Pythonの全言語UIサイズは未実施。製品UI・翻訳の変更はない。

再実行:

```bash
./.venv/bin/python scripts/migration_fft_candidate.py --extended .migration-local/fft-extended-v1 --report .migration-local/006-a-verify.json
./.venv/bin/python scripts/migration_fft_iteration.py --extended .migration-local/fft-extended-v1 --report .migration-local/006-a-edits.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_fft_candidate.py
```

## MIG-004-Bの成果と検証（前回記録）

着手: 2026-09-30、HEAD `80435eef`、004-Aのブランチはremote一致・clean。
このworktreeで`codex/migration-004-b`へ分岐した。今回の変更は未コミット。
変更境界は薄いQMLパス解決、独立runner/test、SDK/Native CIと`migration/`の記録。
現行製品のDSP/UI、003-A/B/Cの入力・期待値・許容差は変更していない。

- [反復runner](../scripts/migration_qt_iteration.py)を追加。通信なし、CPU並列数4、debug、同じQML/worker/lock。
  方式別targetを完全削除するclean 3回、no-op warmup1回+5回、固定QML編集5回、package3回。
- 元のsourceと既存targetを使わず、専用コピーで測定。QML変更は毎回同じbytesへ復帰する。
  ローカルの`benchmarks/results/2026-09-30-004-b-intel.json`に32 sampleとwarmup2回、全commandの圧縮log/hashを保存。
- bundle内のQML読み込みを追加。ad-hoc署名、ZIP化、再配置後にSDK環境変数・開発PATHを外して起動。
  読み込んだQMLとQt library/pluginの実パスがbundle内であることを要求する。
- ローカル補助検査report（`qt/2026-09-30-intel-bundle.json`）: Cocoaでも両方式の寿命検査と展開後の署名検査に成功。
  QMLを外すと両方式ともexit 101で拒否し、開発checkoutへfallbackしない。検査後は復元した。
- [決定0006](decisions/0006-qt-iteration-local-bundles.md)と[再実行手順](../native/qt-iteration.md)を追加。
  試行失敗4件もローカルの`benchmarks/results/2026-09-30-004-b-development.json`へ本測定と分けて保存した。
- 004-Aの[GitHub CI](https://github.com/youtube-at-vach/MeasureLab/actions/runs/36671211283)はpure core成功、
  Qt境界はICU 73不足でbuild失敗、QML試験skipだった。[根拠](qt/2026-09-30-linux-ci.json)を保存し、
  Linux専用ICU archiveと環境を空にしたqmakeの事前検査を追加。修正後のCIは未実行。

| 反復経路（必要な検査込み） | CXX-Qt 中央値 | Qt Bridge 中央値 | 結果 |
| --- | --- | --- | --- |
| clean | 221.795秒 | 258.154秒 | 各3回成功、600秒以内 |
| no-op | 2.470秒 | 2.646秒 | warmupを除く各5回成功 |
| QML編集 | 2.063秒 | 2.241秒 | 各5回成功、10秒以内、10回すべてnative再コンパイルなし |
| package→ZIP展開→寿命検査 | 56.903秒 | 59.842秒 | 各3回成功、900秒以内。ZIP約44.47/45.17 MiB |

packageの3回目は75.745/101.453秒まで伸びた。全値とばらつきを保存し、短いrunだけを選んでいない。
原因は特定していない。実行性能や言語だけの効果と解釈しない。
現行Python全体のoffline起動も3回成功し、ready中央値7.100秒。
小さなQML画面とworkloadが違うため、速度比や同等表示編集の予算判定には使わない。

| 最終確認 | 結果 |
| --- | --- |
| 本測定・report/log検査 | 32 sample、warmup2回、Python起動3回すべて成功。回数・終了コード・全log hashとgzipを確認 |
| Rust build/fmt/Clippy | 成功。既存のCXX-Qt空init archive/重複rpathのlink警告は残る。ソースlint警告なし |
| 模擬coreのRustテスト | 5 passed。追加したbundleパス解決を含む |
| 最終worktreeの共通QML再検査 | 両方式1回ずつ成功。実行物とsourceは測定コピーとは別記録 |
| Python対象回帰 | 38 passed（3.39秒）。新runnerの14件と既存のrunner/起動分離/台帳検査 |
| 保存fixture verify | FFT小規模14/拡張6、core 4 FFT/27契約/4保存、filter 21数値/6 rate境界すべて成功。更新なし |
| Cocoa画面の画像確認 | 両方式の英語canvas PNG bytes一致。画像は`.migration-local/`に保存。手動操作評価は未実施 |
| CI仕様 | YAML 2 job、inline Python、Linux限定のICU archiveをローカル確認。修正後のGitHub実行は未確認 |
| Ruff lint / format | 成功。594 Pythonファイルのformat確認 |
| Markdown lint・台帳・diff | 成功。180 Markdownファイル、41モジュールの双方向対応、変更文書のリンクと`git diff --check`を確認 |
| main同期 | 終了時fetch後もorigin/mainは`9fd79958`。取込み・参照更新不要 |

MIG-004-BはIntelの開発反復と同じhostでのローカルbundleまで。
ARM/Windows/Linuxの反復とpackage、クリーンOS、release、Gatekeeper/署名/notarization、
同等Python表示編集、core編集、実機2ch、10分連続、QMLの9言語・入力/フォーカス/テーマは未確認。
AC07の実graph所有権、AC13の実音声回収、AC16全体の合格や技術採用には数えない。
全体Pytest/Mypy/翻訳/現行Pythonの全言語UIサイズは今回未実施。製品UI・翻訳の変更はない。

再実行:

```bash
./.venv/bin/python scripts/migration_qt_iteration.py --qt-prefix .tools/qt/6.11.2/macos --report .migration-local/004-b.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_iteration.py tests/logic_verification/test_migration_qt_probe.py
```

## MIG-004-Aの成果と検証（前回記録）

着手: 2026-09-30、HEAD `a8ff6dd7`、統合ブランチの作業ツリーはclean。
このworktree内で`codex/migration-004-a`へ分岐した。
変更境界は`native/`、runnerと対象テスト、`migration/`、独立したRust CI。
現行DSP/UI、003-A/B/Cの保存入力・期待値・許容差は変更していない。

- [Qt SDK仕様](../native/qt-sdk.toml): 6.11.2とaqtinstall 3.3.0を固定して`.tools/qt/`へ分離導入。
  [導入記録](qt/2026-09-30-intel-sdk.json)に配布metadata、取得した5アーカイブのhash、compiler/SDK/依存版を保存。
- [workspace](../native/Cargo.toml)とCargo.lock: Rust 1.98.1、CXX-Qt 0.10.0、Qt Bridge 0.3.0、CXX 1.0.202。
  初回のCXX本体/生成器の版違いによるリンク失敗を修正し、両方式をビルド・実行した。
- [共通QML](../native/qml/Main.qml)と[模擬worker](../native/probe-core/src/lib.rs):
  Preparing/Runningの区別、cancel/失敗/停止、重複要求、容量1の最新snapshotと通知集約、旧世代拒否。
- 各viewと模擬保存sessionが一意のtokenを保持する。1view、両viewを閉じた後も残る需要で継続し、
  最後の解除で停止する。異なるProbeのtokenと重複解除を拒否する。
- [共通runner](../scripts/migration_qt_probe.py)でBackend・共有view windowの破棄/再生成と、running中の終了を検査。
  終了コード、シナリオ完了、engine/application破棄後のworker/model数0を要求する。
- [決定0005](decisions/0005-qt-boundary-probes.md)に両方式の差分表と境界を記録。
  [再実行手順](../native/qt-probe.md)と[独立Rust CI](../.github/workflows/native-evaluation.yml)を追加した。

| 今回の確認 | 結果 |
| --- | --- |
| Python参照の分離起動・self-test | 成功、終了コード0。従来と同じlocale/font警告 |
| 保存fixtureのverify | FFT小規模14/拡張6、coreの4 FFT/27契約/4保存、filterの21数値/6 rate境界すべて成功。期待値更新なし |
| Qt開発SDK | qmake/moc 6.11.2、headers/private headers/frameworksを確認。PyQt runtimeとは別パス |
| Rust locked build / fmt / Clippy | 成功。CXX-Qt側に空のinit archiveと重複rpathのlink警告は残る。ソースlintの警告はなし |
| 模擬workerのRustテスト | 4 passed。遅いconsumer、cancel/失敗/旧世代、破棄、2view/sessionと最後のtoken解除 |
| 両方式の共通QML検査 | 各3回すべて成功。160 msのGUI停止中もproducerが進行。通知集約、list model、購読・破棄・再生成・終了を検査 |
| QML画面の画像確認 | 英語、offscreen/software/Basic、560×360 px。両案のcanvas PNG bytes一致。画像は`.migration-local/`に保存 |
| Python関連回帰 | 181 passed、2 skipped（31.38秒）。runnerの追加異常系を含む最終単独検査は7 passed。skipは既存の奇数長Nyquistという該当しない組合せ |
| 現行Python UI全言語サイズ | 9言語すべて成功、`Verification Passed!`、終了コード0。新QMLの9言語評価とは別 |
| Ruff lint / format | 成功、590 Pythonファイルのformat確認 |
| Markdown lint・台帳・diff | 成功。178 Markdownファイル、41モジュールの双方向対応、変更文書のリンク、`git diff --check`を確認 |
| Native CI定義 | YAMLの構文と2 jobをローカル確認。GitHub上の実行は未確認 |
| main差分 | fetch後もorigin/mainは`9fd79958`。参照更新・マージ不要 |

ローカルの`qt/2026-09-30-intel-probe.json`に同じQML、ソース/lock/実行物のhash、環境と各runを保存。
各self-testの時間は診断値で、004-Bの性能protocolによる反復build・実行性能の比較ではない。
MIG-004-Aの完了は、このIntel hostでSDK・両実行物・基本GUI境界が揃った範囲に限定する。

Qt Bridgeの公式READMEはmacOS arm64 experimentalと記載し、Intelは未掲載。
今回はCommand Line ToolsのApple Clang 16/Apple SDK 15.2で成立したが、full Xcodeは未導入。
他OS/CPU、配布、全言語QML、アプリ全体のwindow root再生成、全例外経路、10分連続・負荷・性能予算は未確認。
AC07の実graph/node/cache/in-flight result所有権は006-B、AC13の実backend/device/callback回収は005-B/008で検証する。
模擬保存sessionは需要tokenのみで、実ファイル保存やDSPの共有計算を行っていない。
全体Pytest/Mypy/翻訳検査、GitHub CIは未実施。

再実行は[004-Aの手順](../native/qt-probe.md)の環境変数を設定してから行う。

```bash
cargo +1.98.1 build --locked --manifest-path native/Cargo.toml
cargo +1.98.1 fmt --manifest-path native/Cargo.toml --all --check
cargo +1.98.1 test --locked --manifest-path native/Cargo.toml -p probe-core
cargo +1.98.1 clippy --locked --manifest-path native/Cargo.toml --workspace --all-targets -- -D warnings
./.venv/bin/python scripts/migration_qt_probe.py --qt-prefix .tools/qt/6.11.2/macos --repeat 3 --report .migration-local/qt-probe.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_probe.py
```

## MIG-003-Cの成果と検証

着手: 2026-09-30、`codex/next-core-evaluation`、HEAD `1cd243f2`、作業ツリーはclean。
statusの前回記録には003-Bが未コミットとあったが、開始時にcommit済み・remote一致を確認。
変更境界は`scripts/`・`tests/`・`migration/`。現行DSP/UI・003-A/Bのfixture・契約の許容差は変更していない。

- [参照runner](../scripts/migration_filter_reference.py)、[独立oracle](../scripts/migration_filter_oracle.py)、
  [ケース定義](../scripts/migration_filter_cases.py)を追加。GUI/deviceをimportしない。
- [fixture仕様](fixtures/filter-v1.md): 最小FIR5件、現行polyphase12件、代表SOS4件と6 rate境界。
  入力・係数・初期state・期待出力・metadataとhashを133ファイルへ固定。
- FIRは直接有限和と新契約モデルを照合。trigger1024→512、信号遅延0.5 output sample、
  gap `[100,104)`→`[50,53)`、warmup `[0,1)`、whole/1/127/256/不規則chunk一致を確認。
- polyphaseは独立sinc/Kaiser式・中心補償した有限和、SOSは独立direct form Iと帯域/位相を照合。
  SOSの因果参照はzero stateからの出力・最終state・chunk一致も保存する。
- [決定0004](decisions/0004-filter-rate-reference.md): 現行一括API、新契約FIR、同じ係数の因果SOS参照を区別。
  invalid rateの現行bypassと新契約拒否、独立chunk呼出しによる端点/長さ差を別記録した。

| 今回の確認 | 結果 |
| --- | --- |
| 参照起動分離・offscreen self-test | 成功、終了コード0。従来と同じlocale/font警告 |
| Rust/C++スモーク | 既存実行物の再実行成功。Qt接続は未検証 |
| 新fixture再検査 | 固定環境で21数値ケース・6 rate境界すべて成功、GUI/device importなし |
| 新fixture再生成 | Pytest内で新しい一時ディレクトリへ明示生成。manifestを含む全133ファイルのbytesが保存版と一致 |
| 独立理論との比較 | 最大差はFIR約2.78e-17、polyphase約1.11e-16、SOS約4.77e-14。全ケースで契約内 |
| 対象回帰Pytest | 213 passed、2 skipped（31.01秒）。新規44件を含む。skipは既存003-Aの奇数長Nyquistという該当しない組合せ |
| 既存保存fixture | 003-Aの小規模14件・拡張6件、003-Bの4 FFT・27契約例・4保存例を固定環境で再検査し成功。期待値更新なし |
| Ruff lint / format | 成功。変更後の全体lint・format確認を最終実行でも通過 |
| Markdown lint・台帳・diff | 成功。176 Markdownファイル、台帳41件/20プリミティブ、変更文書のリンクと`git diff --check`も成功 |
| main差分 | fetch後もorigin/mainは`9fd79958`。参照更新・マージ不要 |

ローカルの`fixtures/runs/2026-09-30-intel-filter.json`へ時間・process peak RSS・各誤差を保存。
検査全体約2.64秒、RSS 106,176,512 bytesは単発の診断値で、並行Pytestの影響もある。
性能protocolに沿う比較結果ではない。

現行polyphaseの127-frame独立呼出しでは、48→24 kHzの1秒入力が24189 framesになる
（一括は24000）。SOSの独立前後処理にも端点差がある。現行製品を修正したり、
これらを連続処理の合格として扱ったりせず、006-Dのstate/phase保持の比較資料にした。

全体Pytest/Mypy/翻訳/UIサイズとGitHub CIは未実施。製品UI・翻訳の変更やPR作成は行っていない。
候補core・共有graph・物理I/O・Qt・他OS、IIR gap回復・全filter/rate構成は未完了。
MIG-003の完了はA/B/Cの参照入力・期待値・再現検査が揃った意味に限定する。

再実行:

```bash
./.venv/bin/python scripts/migration_filter_reference.py verify
./.venv/bin/python scripts/migration_core_reference.py verify
./.venv/bin/python scripts/migration_fft_reference.py verify
./.venv/bin/python scripts/migration_fft_reference.py verify --fixtures .migration-local/fft-extended-v1 --baseline migration/fixtures/fft-extended-v1.manifest.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_filter_reference.py tests/logic_verification/test_migration_core_reference.py tests/logic_verification/test_migration_fft_reference.py tests/logic_verification/test_migration_reference.py tests/logic_verification/test_migration_inventory.py tests/logic_verification/analysis/test_resample.py tests/logic_verification/analysis/test_filters.py tests/logic_verification/analysis/test_analysis_cache.py tests/logic_verification/core/test_fft_manager.py tests/logic_verification/core/test_window_functions.py tests/logic_verification/analysis/test_spectrum_rms_accuracy.py
./.venv/bin/python scripts/check_migration_inventory.py
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

## MIG-003-Bの成果と検証（前回記録）

着手: 2026-09-30、`codex/next-core-evaluation`、HEAD `320eb506`、作業ツリーはclean。
変更境界は`scripts/`・`tests/`・`migration/`。現行DSP/UI・003-Aのscript/fixture・契約の許容差は変更していない。

- [コア参照runner](../scripts/migration_core_reference.py)、[契約モデル](../scripts/migration_core_oracle.py)、
  [独立した手計算ケース](../scripts/migration_core_cases.py)を追加。GUI/deviceをimportせず実行する。
- [fixture仕様](fixtures/core-v1.md): AC01の4/8ch×f64/f32を現行FFTと解析式で比較。
  AC02/03/08/09/11/12の27契約例、校正snapshotのJSON/CSV保存例4件を固定。
- routeの並替え・mix・複製・zero・不正要求、triggerの厳密な区間、pending/保持超過/gap、
  世代切替、clock写像、tap/mute、IDに追随する校正と不変metadataを検査。
- [決定0003](decisions/0003-core-contract-oracles.md): 新契約oracleと現行参照を区別。
  履歴は区間の可用性までで、実バッファ・共有graph・製品exporterの実装合格とは扱わない。
- manifestにsource/runner/契約文書hash・全導入版を保存。metadataと位置/reasonは厳密一致。
  破損hash、shape/順序/版、null→0、非有限数などを拒否し、通常verifyは期待値を更新しない。

| 今回の確認 | 結果 |
| --- | --- |
| 参照起動分離・offscreen self-test | 成功、終了コード0。従来と同じlocale/font警告 |
| Rust/C++スモーク | 既存実行物の再実行成功。Qt接続は未検証 |
| 新fixture再検査 | 4 FFT・27契約例・4保存例すべて成功、GUI/device importなし |
| 新fixture再生成 | 一時ディレクトリへ明示再生成。manifestを含む全82ファイルのbytesが保存版と一致 |
| 理論比較 | 最大正規化FFT複素差はf64約1.56e-14、f32約7.25e-9。bin/phase/peak/RMS/PSD/inverseも契約内 |
| 新規Pytest | 70 passed（5.26秒）。区間の別実装との照合、snapshot保持、保存失敗、破損fixtureも検査 |
| 対象回帰Pytest | 162 passed、2 skipped（15.05秒）。skipは003-Aの奇数長Nyquistという該当しない組合せ |
| 003-Aの保存fixture | 小規模14件・拡張6件を固定環境で再検査し成功。入力・期待値の更新なし |
| Ruff lint / format | 成功、580 Pythonファイルのformat確認 |
| Markdown lint・台帳・diff | 成功。174 Markdownファイル、台帳41件/20プリミティブ。`git diff --check`も成功 |
| main差分 | fetch後もorigin/mainは`9fd79958`。参照更新・マージ不要 |

ローカルの`fixtures/runs/2026-09-30-intel-core.json`に時間・process peak RSS・誤差を保存。
単発の全検査の診断値であり、性能protocolによる新旧比較ではない。
全体Pytest/Mypy/翻訳/UIサイズとGitHub CIは未実施。製品UI・翻訳の変更やPR作成は行っていない。
003-C、候補core、物理I/O、Qt、他OS、実バッファ/共有graph、製品保存互換は未完了。

再実行:

```bash
./.venv/bin/python scripts/migration_core_reference.py verify
./.venv/bin/python scripts/migration_fft_reference.py verify
./.venv/bin/python scripts/migration_fft_reference.py verify --fixtures .migration-local/fft-extended-v1 --baseline migration/fixtures/fft-extended-v1.manifest.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_core_reference.py tests/logic_verification/test_migration_fft_reference.py tests/logic_verification/test_migration_reference.py tests/logic_verification/test_migration_inventory.py tests/logic_verification/core/test_ring_buffer.py tests/logic_verification/core/test_ring_buffer_mismatch.py tests/logic_verification/core/test_calibration_alignment.py tests/core/export/test_json_exporter.py tests/core/export/test_csv_exporter.py
./.venv/bin/python scripts/check_migration_inventory.py
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

## MIG-003-Aの成果と検証（前回記録）

着手: 2026-09-30、`codex/next-core-evaluation`、HEAD `996ed1dc`、作業ツリーはclean。
変更境界は`scripts/`・`tests/`・`migration/`。現行DSP/UIと契約の許容差は変更していない。

- [参照runner](../scripts/migration_fft_reference.py)と[独立理論oracle](../scripts/migration_fft_oracle.py):
  生成と検査を分離。現行FFT/窓、解析式DFT、正規化/PSD/RMS/inverse、phase/dBを照合。
- [fixture・再現手順](fixtures/README.md): 小規模14件の入力/期待値bytesをGit対象へ保存。
  拡張6件の全hashとmanifest、実行reportを保存。N=24000/48000/4194304の配列はローカルに保持。
- GUI/device moduleをimportしない。source/runner hash、全導入版、dtype/shape、ID/metadataを検査し、
  不一致・NaN・暗黙FFT fallbackを拒否。明示portable modeでもsource/hash/数値の条件は維持する。
- [決定0002](decisions/0002-fft-reference-runner.md): Spectrumの対象メソッドASTをそのまま実行するadapterの境界、
  1 thread・空wisdomによる数値検証、巨大配列の保存方式を記録。
- DC/Nyquistの現行表示差を実測。peakは理論より約+6.0206 dB、RMS換算/ASDは約+3.0103 dB。
  理論値と現行値を別保存し、製品側の修正は行っていない。

| 今回の確認 | 結果 |
| --- | --- |
| 参照起動分離・offscreen self-test | 成功、終了コード0。従来と同じlocale/font警告 |
| Rust/C++スモーク | 既存実行物の再実行成功。Qt接続は未検証 |
| 固定環境のfixture再検査 | 小規模14件・拡張6件すべて成功、GUI/device importなし |
| 再生成とbaseline照合 | 別ディレクトリへ再生成し、小規模manifest/入力/期待値一致。拡張も保存manifestと一致 |
| 理論比較 | f64の最大正規化FFT複素差は約1.34e-13、f32は約2.83e-9。窓・inverse・PSD積分・phase/dBも契約内 |
| 対象Pytest | 78 passed、2 skipped（12.12秒）。skipは直接DFT試験の奇数長Nyquistという該当しない2組合せ。奇数最終binのfixture自体は検証済み |
| Ruff lint / format・Markdown lint・台帳 | 成功。574 Pythonファイル、172 Markdownファイル、台帳41件/20プリミティブ。`git diff --check`も成功 |
| main差分 | fetch後も`9fd79958`。参照基準の更新・マージ不要 |

検査時間とprocess peak RSSは[実行report](fixtures/README.md#ケースと結果)へ記録した。
単発の検査全体の診断値であり、性能protocolに沿う新旧比較ではない。
AC01は2ch、AC04は参照fixture側まで。MIG-003全体、候補実装、4/8ch、filter/rate、Qt/実機/他OSは未完了。
全体Pytest/Mypy/翻訳/UIサイズとGitHub CIは未実施。製品UI・翻訳の変更やPR作成は行っていない。

再実行:

```bash
./.venv/bin/python scripts/migration_fft_reference.py verify
./.venv/bin/python scripts/migration_fft_reference.py verify --fixtures .migration-local/fft-extended-v1 --baseline migration/fixtures/fft-extended-v1.manifest.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_fft_reference.py tests/logic_verification/test_migration_reference.py tests/logic_verification/test_migration_inventory.py tests/logic_verification/core/test_fft_manager.py tests/logic_verification/core/test_window_functions.py tests/logic_verification/analysis/test_spectrum_rms_accuracy.py
./.venv/bin/python scripts/check_migration_inventory.py
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

## MIG-002の成果と検証（前回記録）

- [機能台帳](inventory.md): `ALL_MODULE_KEYS` / `MODULE_REGISTRY`の41件と共通・外部連携10件。
  サブ機能、現行source、代表テスト、プリミティブ対応を記録。移行状態は全件未着手。
- [プリミティブ台帳](primitives.md): 20件の入出力、単位、Timebase、状態、validity、精度、共有条件と利用機能の逆引き。
- [コア契約](contracts/core.md)・[数値契約](contracts/numerics.md): ID/世代、N-channel、履歴/trigger、routing/tap、
  validity伝播、FFT共有、校正/保存、数式・許容差。新契約と現行の挙動を区別。
- [受け入れ条件](contracts/acceptance.md)・[比較手順と予算](benchmarks/protocol.md): AC01〜16と最小2chフローの終了条件。
- [決定0001](decisions/0001-p0-contracts.md)・[後続作業票](tasks.md): 現行との差と003〜008の目的・依存・範囲・判定条件。
- [台帳チェック](../scripts/check_migration_inventory.py): Qt/DSPをimportせず、キー/登録source、ID、状態、ローカルリンク、双方向対応を検査。

| 今回の確認 | 結果 |
| --- | --- |
| 分離先確認・offscreen GUI self-test | 成功、終了コード0。前回と同じlocale/font警告 |
| Rust/C++のスモーク再実行 | 成功。既存ビルドから実行可能。Qt接続は未検証 |
| 台帳整合チェック | 41件のキー/source、20プリミティブとの対応、ローカルリンク一致 |
| 台帳検査の異常系と既存のbuffer/window/resample/RMS/校正/export試験 | 44 passed（2.95秒） |
| Ruff lint / format | 成功、569ファイルのformat確認 |
| Markdown lint | 成功、170ファイル、指摘0件 |
| main差分 | fetch後のorigin/mainは参照コミットと同じ。取込み・参照更新は不要 |

台帳には現行のsingle-reader buffer、暗黙のch補正、1/2ch I/O、plan共有と結果共有の差を残した。
Spectrum標準表示のDC/Nyquist係数などはコード読解上の差で、MIG-003で現行値と理論値を別に保存する。
今回は製品DSP/UIを変更していない。新契約の数値・時刻・共有動作が実装で合格した意味ではない。
性能予算は初期基準で、実測値ではない。MIG-003のfixture・MIG-004のQt SDK/画面はまだ作成していない。

再実行:

```bash
./.venv/bin/python scripts/check_migration_inventory.py
./.venv/bin/pytest -q tests/logic_verification/test_migration_inventory.py tests/logic_verification/core/test_ring_buffer.py tests/logic_verification/core/test_ring_buffer_mismatch.py tests/logic_verification/core/test_window_functions.py tests/logic_verification/analysis/test_resample.py tests/logic_verification/analysis/test_spectrum_rms_accuracy.py tests/logic_verification/core/test_calibration_alignment.py tests/core/export/test_json_exporter.py
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

## MIG-001で確認したこと（前回記録）

実行環境はmacOS 14.8.9 / Intel x86_64。詳細・コマンドは[環境と再開手順](environment.md)。

| 検証 | 結果 |
| --- | --- |
| 専用venvと`pip check` | 成功。editable installはこのworktreeを参照 |
| 分離先確認 `migration_reference.py --check` | 設定・校正・ログ・スクリーンショット・FFT wisdomの既定保存先が専用ディレクトリ内 |
| Python GUIの`--self-test` | offscreenで起動成功、5秒後の自動終了、終了コード0 |
| 分離起動・設定・utils・MainWindow activityのテスト | 68 passed、24 subtests passed（7.61秒） |
| Rustスモーク | Cargoによるコンパイル・リンク・実行成功。rustfmt/Clippyも確認 |
| C++スモーク | Apple Clang + CMake + Ninjaのコンパイル・リンク・実行を確認 |
| Ruff lint・format | 成功。559ファイルのformat確認 |
| Markdown lint | 成功。162ファイル、指摘0件 |
| `git diff --check` | 成功 |

GUI起動時にlocaleのUTF-8への切替と、`Sans Serif`のフォント代替の警告が出た。
終了コードは0で、起動失敗・例外は記録されなかった。

未確認・対象外:

- ウィンドウの目視評価、実機音声I/O、2chループバック、macOS ARM・Windows・Linux。
- QtのC++開発用SDK、Rust/Qt接続、QML画面、配布パッケージ。
- 全体Pytest・Mypy・翻訳検証・全言語UIサイズ。今回は製品UI・翻訳の変更やPR前の全体検証を行っていない。
- 実行性能・開発反復速度の比較。上記のスモーク時間は性能評価として扱わない。
- GitHubでのCI実行・必須チェック設定。既存Python CIの対象ブランチには検証ブランチを追加済み。

## 次の作業と再開

1. このファイルと`git status --short --branch`を確認する。最後の記録後の変更を保護する。
2. [環境手順](environment.md)に従い、参照版の起動とツールチェーンを再確認する。
3. 台帳チェックとFFT/core/filterの各reference runnerでverifyを実行する。
   環境差は確認し、比較時だけ明示portable modeを使う。
4. [作業票](tasks.md)の007-A-triggerは取得owner APIを完了した。Qtからの要求配送と2viewの共有hold/retry/releaseは007-A-trigger-displayへ追加した。次は基本校正・保存のQt操作/実取得統合、または005-A/Bの製品共通adapter/全tapへ進める。BlackHole実入力表示は007-live-displayへ追加した。007-CのIntel最小renderer試験と失敗記録は007-rendererへ追加した。採用判断・個別widgetの本実装は行っていない。007-Aの保存入力の共有result表示は007-displayで追加した。動的f32 routeのcallback配送/BlackHoleは005-routeで追加した。006-Aの保存コーパス/Intel編集、006-B/C/D/Eのpure graph/履歴/filter/result、004-BのIntel反復は完了した。
   Linux CIのICU修正は004-Bの`e0b992ce`へcommit済み。修正後のGitHub実行は未確認。公開する段階で確認する。
   ARM/Windows/Linuxの反復測定、full Xcode、release/clean環境の配布起動は未確認のまま残す。
5. 003-A/B/Cの保存入力と期待値は揃った。候補実装へ同じbytesを通し、参照側の完了と実装のAC合格を分ける。
6. 006-Cのpure履歴/Timebaseは共有graphへ接続済み。005-Aのpure queue/route、005-Bの実機とBlackHoleの診断経路は追加済み。
   以後はBlackHole 16ch／2chで通常の回帰を行う。UAC-232は実機が必要な要件だけに使う。
   006-Dのfilter/rateと006-Eの不変result/基本校正/保存もpure境界を検証済み。input.rawは005-graph、動的f32 route配送は005-routeで接続した。保存入力の実result表示は007-displayで追加した。BlackHole実入力表示は007-live-displayへ追加した。分離view/9言語は007-windows-i18nで追加した。取得ownerのTrigger captureとQt要求配送/共有holdは追加済み。次は基本校正・保存のQt操作/実取得統合、または全tap・製品共通adapterを検証する。
   物理USB切断／復帰は必要時にユーザーが操作できる回だけで行う。
   独立Rust CIは追加済み。source/state/所有権の境界を記録し、
   004-Aの模擬workerのmutex/通知を音声callbackへ転用しない。
7. 契約変更が必要なら決定記録、台帳、AC、fixtureを同時に更新する。MIG-002完了とRust/QML採用決定を混同しない。

無人の継続実行や定期通知は設定していない。次回もこのworktreeを再利用できる。
`.venv/`、`.tools/`、`.migration-local/`はGit管理外なので、worktreeを退役させる前に必要な測定結果を明示的に保存する。

## mainとの同期・変更の統合

週1回を目安に、また各段階の終了時に統合担当が同期する。自動マージは設定しない。
手順はworktreeのルートで実行する。

```bash
git status --short --branch
git fetch origin
git log --oneline HEAD..origin/main
git diff --stat HEAD...origin/main
```

未コミットの作業を記録・保護してから`git merge origin/main`で取り込む。共有後の長期ブランチは通常rebaseしない。
競合解消に加え、台帳・参照テスト・fixture・契約の変更を照合する。対象テストとRuffを再実行し、
同期したコミット、機能差分、参照データの更新有無、検証結果をこのファイルへ記録する。

後続の独立した実装では、この検証ブランチから`codex/migration-<task>`を分岐し、PRの比較先を
`codex/next-core-evaluation`にする。初回の環境整備は検証ブランチに直接記録する。
PR作成時は[CI Pre-checker](../.agents/skills/ci-prechecker/SKILL.md)を実行し、Ready for reviewで作成する。
GitHubへの初回公開時には、検証ブランチの必須チェックを実際のCI結果から設定する。
Rustのソースを追加するタスクで、Pythonと独立したRust CIジョブも追加する。
プレビュー配布は別名・別チャンネルとし、安定版更新へ接続しない。
