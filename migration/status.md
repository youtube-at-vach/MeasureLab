# 次期コア検証の進捗

更新: 2026-10-03。正本は[評価計画](../guide/RUST_QML_MIGRATION_PLAN.md)。Rust/QMLの採用は未決定。
現在はP0〜P2の評価中。MIG-008の完了と全41機能の移行完了は別に扱う。

このファイルは現状・残作業・再開の入口とする。過去の詳細な試験/失敗/証拠は
[2026-10-03までの詳細履歴](status-history-2026-10-03.md)へ移した（旧本文2,248行をそのまま保存）。
履歴内の「次は」「未コミット」は当時の記録。現在の判断には以下と[残工程表](remaining-to-mig008.md)を使う。

## 作業場所と基準

| 項目 | 現在の値 |
| --- | --- |
| macOS checkout | `/Users/vach/.codex/worktrees/next-core-evaluation/MeasureLab`（Codex管理、再利用） |
| 実行環境 | macOS 14.8.9 / Intel。Linuxの前回検証はUbuntu 26.04.1 / x86_64 |
| ブランチ | 統合先`codex/next-core-evaluation`、今回`codex/migration-filter-qt` |
| 今回の開始点 | `e027696a`、remote一致・cleanの`codex/migration-filter-input`から分岐 |
| 数値/DSP参照 | `9fd79958`（MeasureLab 0.9.0）。元fixture/係数/許容差を維持 |
| 最終main同期 | 2026-10-03、origin/main `84013a76`をmerge `0fe41a7a`で取込み。差分はCURRENT_DIRECTION.mdのみ |
| Git状態 | 明示f32→f64 filter境界は`e027696a`へコミット済み。今回のfilter/Qt接続・診断・文書は未コミット |
| 外部更新 | 今回のpush/PR/Issue/Project更新/公開配布は未実施。無人継続・定期通知は未設定 |

`.venv/`、`.tools/`、`.migration-local/`はGit管理外。worktreeを退役させる前に必要な証拠を保存する。
通常の音声回帰はBlackHole 16ch/2chを優先する。USB/物理clock/電圧/遅延の要件に限りUAC-232を使う。

## タスク

「検証済み」は記載範囲だけを指し、タスク全体やAC全体の合格を意味しない。

| タスク | 状態 | 検証済みの範囲 |
| --- | --- | --- |
| MIG-001 | 完了 | 分離worktree/環境/保存先、Rust/C++/Qt SDK、再開手順 |
| MIG-002 | 完了 | 41機能+共通10件、20プリミティブ、コア/数値契約、AC01〜16、比較protocolと作業票 |
| MIG-003 | 完了（参照側） | FFT24ケース、27契約/4保存例、filter21数値/6 rate境界。候補実装の採用判定とは別 |
| MIG-004 | 進行中 | Intel/Linuxの両Qt基本寿命、build/edit反復、ローカルpackage。ARM/Windows/clean環境とGitHub CIは残る |
| MIG-005 | 進行中 | N-channel input.raw queue/履歴/共有FFT、動的f32 route、短いUAC-232/BlackHole比較。共通入力境界に加え、PortAudio native callbackと両Qtのrequestによるbackend選択を検証 |
| MIG-006 | 進行中 | FFT/共有graph/履歴/Timebase/世代、pure filter、不変result/ID校正、v1/製品JSON・CSV/非同期保存/旧形式import。保存f64取得21ケース×5 chunk、明示f32変換30条件×5 patternとnative両backend6実行。両Qtの固定filter/派生Trigger/4形式保存は下記の範囲を検証 |
| MIG-007 | 進行中 | 保存/BlackHoleの両Qt line/heatmap、分離/9言語、Trigger hold/retry/release、校正編集、v1/製品保存、製品import参照表。固定filterの派生表示/手動Trigger/保存を追加。rendererはIntelの最小試験のみ |
| MIG-008 | 未着手 | 008-Aの同じ2chフロー統合、008-Bの同条件比較、008-Cの四案の理由付き判断が必要 |

既存の代表的な成果: 両Qt保存/製品importは4入力×9言語×両方式の72実行を各段階で検査。
BlackHole取得中保存はv1/製品の各2/4/8ch×両方式×3反復、計36実行を検査。
writerの250 ms待ち注入はbusy/取消/取得継続の診断で、実ディスク性能ではない。
詳細件数・失敗・artifact hashは[詳細履歴](status-history-2026-10-03.md)に保持した。

## 今回の変更と検証

[固定filter/両Qt接続](../native/filter-qt.md)と[決定0036](decisions/0036-filter-qt-integration.md)を追加。
requestで因果3-tap `[0.25,0.5,0.25]`、48→24 kHzを明示選択し、
一つの解析owner/filter stateから派生履歴/共有FFT、両Qt line/heatmap、派生domainの手動Trigger、
ID校正、同じ不変snapshotのv1/製品JSON・CSV保存へ接続した。
親Source/明示変換/rate/遅延を`conditions.filter`へ保持し、読込み時も整合性を検査する。
製品DSP/GUI、元fixture/係数/許容差、Cargo.lockは変更していない。

| 検証 | 結果・証拠 |
| --- | --- |
| 保存入力/両Qt | 逆portのf32/f64×2/4/8ch×Boxcar/Hann×両Qtの24実行、正portのBoxcar12実行、2ch/f32/Hannの9言語×両Qt18実行、計54実行成功。独立有限和/全相対列/校正、warmup、pending/retry/gap、共有FFT/hold、分離/遅いGUI/世代/回収、4保存形式の全snapshot一致を検査 |
| BlackHole/両Qt | CPAL/PortAudio×2/4/8ch×Boxcar/Hann×両Qtの24実行・48取得世代成功。4,015,104親f32 frameのarchiveからport/tone/振幅と通常/Trigger保存の全配列を照合。first/Triggerの親support、stream close/terminate/実48 kHz、stop/restart/回収を検査。XRUN/拒否/取得gapなし |
| 既存raw表示の回帰 | 保存4/8chのf32/f64×両Qt、英語の8実行成功。共有表示、Trigger、独立zoom、pending/gap/世代/回収を検査 |
| Rust/Python | workspace194件（追加3件）、関連Python304件（追加12件）成功。派生Triggerのdomain/親event拒否/共有cache/履歴回収と、来歴/遅延改変のcodec拒否を追加 |
| 静的検査/UI | Clippy/Rust fmt、Mypy116 source、Ruff lint/format708 files、翻訳キー、Markdown lint240 files、全言語の表示/スクロールを含むUIサイズ検査に成功 |

保存の最終reportは`.migration-local/2026-10-03-filter-qt/`の
`saved-final-v2/report.json`、`forward-final/report.json`、`languages-final/report.json`。
155 source/runnerと3実行物を比較前後で照合し、固定実体と全artifact hashを同階層へ保存した。
実入力の最終reportは同階層の`live-final/report.json`。
保存/実入力の各report間でもsource/binary hashは一致し、実入力ではPortAudio libraryも固定保存した。
初回2ch/Boxcarの4実行も`live-first/report.json`で成功した。同じsource/binaryの代表診断として保持する。
各最終reportの831/495/663/1,216 artifactと初回実入力の336 artifactの全hash一致を確認し、
`verified-evidence.json`へ照合結果を保存した。raw回帰は`raw-trigger-final/report.json`を参照。

途中の失敗を合格には数えない。raw/派生窓の長さの違いに伴うreplayのpoll不足と、
24 kHzの派生結果へ48 kHz用の表示軸を使う問題を修正した。
診断の厳密bytes比較を元のFIR許容差へ合わせ、QMLの整数表記を既存手順で正規化した。
Hannで既存Trigger oracleのDC/Nyquist tone RMS誤りを検出し、
数値契約/既存DSPの端点処理へ合わせた。擬似test proofも手計算の端点へ更新した。
失敗reportは同階層の`saved-first/`、`saved-second/`、`saved-third/`、`saved-final/`へ保持した。
初回の静的/テスト失敗logも同じrootに保存した。詳細は決定0036を参照。

remote CI、全体Pytest、長時間性能/他OSは未実施。
全tap/動的route ack、親Trigger adapter、製品設定UI/永続profile、008-A全体は残る。
終了時のfetchでもorigin/mainは`84013a76`、未取込commitなしを確認した。

## 前回の明示f32→f64 filter境界

[明示f32→f64 filter境界](../native/filter-input.md)と[決定0035](decisions/0035-explicit-filter-input.md)を追加。
`Filter::new`のf32拒否を維持し、明示した`F32ToF64Exact`だけを解析ownerで拡張する。
queue/元block/raw履歴はf32、filter state/派生履歴/共有FFTはf64。元f32 Sourceを親metadataへ残し、
変換policyを出力identityへ含めた。P2の因果3-tap `[0.25,0.5,0.25]`、48→24 kHzを維持する。
製品DSP/GUI、元fixture/係数/許容差、Cargo.lockは変更していない。

| 検証 | 結果・証拠 |
| --- | --- |
| 保存f32/明示変換 | 5 FIR信号×2/4/8ch×正逆portの30条件×5 callback pattern成功。元値/port、独立有限和、全1,200派生窓のvalidity/ID/共有/平均reset、最初の有効FFT、gap `[100,104)`、poll上限/回収を照合 |
| native実入力 | 同じ実行物のCPAL/PortAudioでBlackHole各2/4/8ch、計6実行成功。計49,152元f32 frame、24,576派生frame、384派生窓を照合。選択tone/振幅、元値/全filter配列/共有FFT、stream close、PortAudio terminateと実48 kHzを検査。XRUN/拒否/取得gapなし |
| Rust | workspace191件成功（追加5件）。明示変換/極値、非有限/flags/SOS拒否、raw保持/逆port/gap/共有回収、restart fence、device不要のrequest拒否を検査 |
| Python/参照verify | 関連131件+live診断の拒否14件、計145件成功。旧f64のpure/実queueの各21ケース×5 patternも回帰。FFT14/core4 FFT・27契約・4保存/filter21・6 rateのverify成功 |

保存reportは`.migration-local/2026-10-03-filter-input/report.json`、native実入力の最終reportは
`.migration-local/2026-10-03-filter-live-final/report.json`。それぞれ43/52 native source、runner、
実行物（実入力はPortAudio libraryも）を固定保存し、591/110 artifactを`evidence-audit.json`で照合した。
比較前後のsource/runner/binary/library一致と、保存実体の全hash一致を確認した。
最初の実入力6実行も成功したが、filter数の実測記録とdevice不要のrequest拒否testを補強したため、
finalへ再build/全6条件を再取得した。最初のreportは`2026-10-03-filter-live/report.json`に保持し、最終sourceの根拠には使わない。

workspace Clippy/Rust fmt、Mypy116 source、Ruff lint/format704 files、Markdown lint238 files、diff checkは成功。
追加scriptの初回Ruffは未使用import1件を検出し、除去後の全体検査に合格した。
終了時のfetchでもorigin/mainは`84013a76`、未取込commitなしを確認した。
Native CIへ保存比較とlive診断のdevice不要testを追加した。
remote CI、全体Pytest、全言語UIサイズは未実施。レイアウト/翻訳の変更はない。
両Qtのfilter/派生Trigger/保存接続、動的route ack/全tap、製品設定UI/profile、長時間性能/他OS、008-A全体は残る。

## 前回のnative callbackと検証

[native PortAudio callback](../native/callback-input.md)と[決定0034](decisions/0034-native-portaudio-callback.md)を追加。
callbackから`InputWriter<f32>`へ直接書き、両Qtの同じ取得owner/履歴/共有FFT/line・heatmapへ接続した。
backendはrequestで明示選択し、旧requestはCPALを維持する。製品設定UI/現行AudioEngineは対象外。
unsafe/PortAudio v19 ABI/library寿命は専用crateへ隔離し、libloading 0.8.9をCargo.lockへ追加した。
元fixture/係数/許容差、製品DSP/GUIは変更していない。

| 検証 | 結果・証拠 |
| --- | --- |
| PortAudio native callback/両Qt | BlackHole論理2/4/8ch×両Qtの6実行・18取得世代成功。計233,472取得frame、元f32/独立FFT/選択port・tone、共有表示/遅いGUI/世代/停止回収を照合。全stream close/terminate成功、status/XRUN/拒否なし |
| CPAL/両Qt回帰 | 同じsource/binaryで2/4/8ch×両Qtの6実行・18取得世代成功。元bytes/共有result/stream・graph回収を確認 |
| 保存共通入力の回帰 | 4/8ch f32/f64×両backend binding×正逆port×boxcar/Hannの32条件成功。元bytes/共有FFT/全相対列/unknown/JSON・CSV/停止後pin・回収を照合 |
| Rust | workspace186件成功（追加9件）。callback元bits、XRUN/不正block、library/clock/backend拒否、旧request、開始/abort/close/terminate失敗とcontext寿命を検査 |
| Python/静的検査/参照verify | Qt関連285件+共通入力45件の330件成功。workspace Clippy/Rust fmt、Mypy116 source、Ruff lint/format698 files、Markdown lint236 files、diff check成功。FFT14/core4 FFT・27契約・4保存/filter21・6 rateのverify成功 |

reportは`.migration-local/2026-10-03-native-callback/portaudio-qt-v2/report.json`と同階層の`cpal-qt/report.json`。
両方式で95 native sourceと2実行物のhashが一致し、各比較前後も一致した。PortAudio library hashも保持した。
初回6実行は`PaStreamInfo.structVersion=0`を拒否して失敗した。公式v19.7の初期化実装もこのfieldを設定しないため、
ABIは`Pa_GetVersion`のv19で照合し、fieldは診断値として保持。実48 kHz検査を維持して再build/全6条件再取得した。
初回の失敗reportは`portaudio-qt/report.json`に残し、合格には数えない。
保存回帰reportは同階層の`saved-backend-input/report.json`。成功reportに対応する120 source/3実行物とPortAudio libraryを
`source-snapshot/`と`binaries/`へ固定保存し、各artifact/logとともに`evidence-audit.json`でhashを照合した。
初回失敗版のsource/binary実体は未保存で、report内のhashとlogだけを保持する。
Pythonの初回検査は存在しないtest pathの指定で収集前に停止した。存在するQt関連testを列挙して330件を再検査し、この停止を合格には数えない。
CI定義へdevice不要のnative callback/lifetime/拒否テストを追加した。remote CI、全体Pytest、全言語UIサイズは今回未実施。
レイアウト/翻訳の変更はない。buildのduplicate rpathとQt生成archiveのranlib警告は残るが、build/Clippyは終了コード0。

## 前回の共通入力評価

[共通入力境界](../native/backend-input.md)と[決定0033](decisions/0033-common-backend-input.md)を追加した。
`InputBinding`/`InputWriter<T>`で実backend/device/精度/ID/port/rate/世代を固定し、
既存CPAL callbackとPortAudio評価workerを同じtyped queue/取得owner/共有FFTへ通す。
この前回試験のPortAudioはblocking入力worker→binary pipe経由。今回追加したnative callbackとは別のtransport。
この段階では現行製品DSP/GUI、Cargo.lock、元fixture/係数/許容差は変更していない。

| 検証 | 結果・証拠 |
| --- | --- |
| 保存入力 | 4/8ch f32/f64×両backend binding×正逆port×boxcar/Hannの32条件成功。元bytes/共有FFT/全相対列/unknown/JSON・CSV/停止後pin・回収を照合 |
| 実PortAudio | BlackHoleの論理2/4/8chで3実行、各98,304 frame/96共有窓成功。元bytes/NumPy FFT/選択tone、overflow/statusなし、stream closeを確認 |
| CPAL/両Qt回帰 | BlackHole2/4/8ch×両方式の6実行成功。共有result/元bytes/寿命とstream回収を確認 |
| Rust/Python | workspace177件（新規3件）、関連Python116件と追加2件成功。新規境界45件を補強後に全件再検査 |
| 静的検査・参照verify | workspace Clippy/Rust fmt、Mypy116 source、Ruff lint/format696 files、Markdown lint234 files、台帳41件/20プリミティブ、diff check成功。FFT14/core4 FFT・27契約・4保存/filter21・6 rateのverify成功 |

前回reportは`.migration-local/2026-10-03-backend-input-final-v2/report.json`（result ID検査の補強後に全条件再取得・成功）。
source/binary/fixture/元bytes/全窓/出力hashとコマンドを保持し、比較前後のsource/binary一致を確認した。
CPAL reportは`.migration-local/2026-10-03-backend-input-cpal-qt/report.json`。
logの共通prefixは`2026-10-03-backend-input-`。Rust/Pythonは`workspace-final.log`/`python-final.log`、追加検査は`python-identity-final.log`。
`evidence-audit.json`で100 source/3実行物/343 artifact/18 logを照合。`source-snapshot/`と`binaries/`へ固定実体を保持した。
初回の保存比較は検証harnessのhistory status期待名で失敗し、修正後の32条件は成功。
途中のharness構文誤りも修正済み。Rust全体の初回はQt test実行物のframework探索で停止し、
`DYLD_FRAMEWORK_PATH`へ分離SDKを指定して再検査した。これらの失敗を合格には数えない。
レイアウト/翻訳の変更はなく、全体Pytest/全言語UIサイズ/GitHub CIはこの段階では未実施。

実backendはf32。ローカルsounddeviceは`float64`指定を内部で`float32`へ変更するため、
実streamのdtype/rate/channel数を確認する。保存f64の成功をdevice f64対応の根拠にしない。
最初のfilter候補はf64因果3-tap `[0.25,0.5,0.25]`、48→24 kHzのまま。
明示f32→f64境界は[今回の手順](../native/filter-input.md)で追加した。filterのQt接続は次の単位で決める。

## 未完了と着手順

依存と完了条件の正本は[残工程表](remaining-to-mig008.md)、各再実行は[作業票](tasks.md)。
保存試験・現在のIntel/BlackHoleで進められる作業と、別環境/人の操作が必要な作業を分ける。

| 優先・作業 | 状態と次の具体的な作業 | 必要な条件 |
| --- | --- | --- |
| 1. 005-A-common | PortAudio native callback/両Qt requestによる選択まで検証済み。動的route ack/世代、購読tapのgraph統合、製品backend設定UI/永続profileが残る | 保存入力/Intel/BlackHoleで着手可能 |
| 2. 006-Dの統合範囲 | 固定一段filterの両Qt派生表示/手動Trigger/保存を追加。親Trigger adapter、f32演算/chain/SOS gap回復は別単位。008-Aには検証済みの固定構成を使う | 現環境で着手可能。暗黙変換はしない |
| 3. 008-A統合 | 未着手。生成→明示route→取得/Timebase→波形/共有FFT→line/heatmap→基本V/FS校正→CSV/JSONを一つの2chフローへ統合。仮想4/8ch回帰とAC対応表を残す | 1〜2の対象backend/dtype/tapを固定する |
| 4. import/profile | import結果のline/heatmap/cursor/再保存、取得profileの再起動維持が未実装 | 現環境で独立して着手可能 |
| 5. 007-B/008-B性能 | 未着手。統合物を固定し、2/4/8chの30秒warmup+10分×3回、単独/複数view/保存/遅いGUI/負荷超過を同条件Pythonと比較 | 3の固定後。測定中に他build/GUI試験を走らせない |
| 6. 005-B/008-B音声 | 短い比較のみ済み。時刻写像/絶対遅延、排他/開始失敗/XRUN位置、USB/スリープ復帰/長時間が未確認 | 通常はBlackHole。物理試験には実機/配線、USB操作には人が必要 |
| 7. 004-B/008-B配布・操作 | Intel/Linuxの模擬probeは済み。実graph統合配布物、ARM/Windows/clean環境、window manager操作/High DPIは未確認 | 各実行環境と手動操作が必要 |
| 8. CI・証拠整理 | 保存比較とnative callback/拒否/寿命テストをNative CIへ追加済み。Linux ICU修正後と新規比較のremote実行は未確認 | 対象変更の公開時にcommitとCI結果を照合 |
| 9. 008-C判断 | 未着手。AC01〜16の証拠/未達、性能/反復/実機/配布/保守費用を四案へ集約 | 材料が揃った時点で理由/未確認/次の範囲/再評価条件を記録 |

残るtapは`input.calibrated`、`output.mixed/post_dut/device_buffer`。結果への後段ID校正を
input.calibrated tapの実装と混同しない。DUT未実装をmixed/post_dutの同一tap扱いにしない。
f32 filter/chain/SOS gap回復、全校正map/SPL、外部Trigger実機adapter、全機器保証も未実装/未確認。
rendererはwgpu候補約29〜30 Hz、基準100万点のJSON/QML境界はSIGBUSを3回再現。
採用・個別widget実装・native GPU texture共有の合格には使わない。

## 次の作業と再開

1. `git status --short --branch`とこのファイルを確認し、未コミット変更を保護する。
2. [環境手順](environment.md)と[native環境](../native/README.md#このworktreeで使う)で参照版/保存先/ツールを確認する。
3. [作業票のverify手順](tasks.md)で既存FFT/core/filterを検査する。期待値/許容差を変更せず、別環境だけ`--portable`を明示する。
4. 上の優先1〜2から008-Aへ進める。独立probeの成功だけで統合・性能・他OSを完了にしない。
5. 結果/失敗/未実施とreport/hashを記録する。新しい詳細は専用手順/決定/reportへ置き、このファイルは現状と次の作業に絞る。

共通入力の再実行:

```bash
./.venv/bin/python scripts/migration_backend_input.py --output .migration-local/backend-input-new
./.venv/bin/python scripts/migration_backend_input.py --virtual-device --output .migration-local/backend-input-live-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_backend_input.py
```

## 証拠と履歴の入口

| 対象 | 参照先 |
| --- | --- |
| 今回のfilter/両Qt/派生Trigger/保存 | [手順](../native/filter-qt.md)、[決定0036](decisions/0036-filter-qt-integration.md)、上記report |
| 前回のf32 filter精度境界 | [手順](../native/filter-input.md)、[決定0035](decisions/0035-explicit-filter-input.md)、上記保存/実入力report |
| 前回のnative callback/Qt backend | [手順](../native/callback-input.md)、[決定0034](decisions/0034-native-portaudio-callback.md)、上記report |
| 前回の共通入力 | [手順](../native/backend-input.md)、[決定0033](decisions/0033-common-backend-input.md)、前回report |
| 保存f64 filter取得 | [手順](../native/filter-acquisition.md)、[詳細結果](status-history-2026-10-03.md#mig-006-d-integration-保存f64のfilter取得scheduler) |
| 両Qt/取得中保存 | [Qt保存](../native/qt-save.md)、[取得中保存](../native/live-save.md)、[詳細履歴](status-history-2026-10-03.md) |
| 製品互換/import | [native codec](../native/product-codec.md)、[native import](../native/product-import.md)、[Qt import](../native/qt-import.md) |
| 過去の全試験/失敗/hash | [詳細履歴](status-history-2026-10-03.md)。元本文SHA-256 `099ed2ae6ec57c11a77c0073896c12ac9520ac3e5934ba4cc9fb5b014f577a62` |
| Linux/別環境の再開 | [環境手順](environment.md#linuxでの再開)、[比較protocol](benchmarks/protocol.md) |

## mainとの同期・変更の統合

週1回と各段階の終了時を目安に、変更を保護してfetch/diff/mergeする。[評価計画の運用ルール](../guide/RUST_QML_MIGRATION_PLAN.md)を参照。
共有長期branchは通常rebaseしない。同期時は競合解消だけでなく台帳/参照/fixture/契約を照合し、対象テスト/Ruffと取込commitを記録する。
独立変更は`codex/migration-<task>`へ分岐し、PRの比較先は`codex/next-core-evaluation`。
PR依頼時は[CI Pre-checker](../.agents/skills/ci-prechecker/SKILL.md)を実施し、Ready for reviewで作成する。プレビューは安定版更新へ接続しない。
