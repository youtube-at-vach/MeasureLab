# 次期コア検証の進捗

更新: 2026-09-30。計画の正本は[評価計画](../guide/RUST_QML_MIGRATION_PLAN.md)。
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
取得/Qtへのgraph統合と006-Eの校正/保存は未着手。

## 作業場所と基準

| 項目 | 値 |
| --- | --- |
| 現行版 | `/Users/vach/MeasureLab`、`main` |
| 検証用worktree | `/Users/vach/.codex/worktrees/next-core-evaluation/MeasureLab`（Codex管理） |
| 検証用ブランチ | 統合先`codex/next-core-evaluation`、今回の作業`codex/migration-006-d`（006-Cの`a0d1bdb6`から分岐） |
| 作業開始・Python参照コミット | `9fd79958`（MeasureLab 0.9.0、開始時のローカルmain） |
| 計画書の調査コミット | `68cbdabc3ecd542d9d73fa0aa86bf9159f44d811` |
| 最終main同期 | 2026-09-30にfetch。origin/mainは参照`9fd79958`のまま、取込み差分なし |
| 統合担当 | 当面、この検証ブランチを担当する単一の作業者 |
| リモート | 今回開始時は006-Cの`a0d1bdb6`がremote一致・clean。そこから006-D用ローカルブランチを分岐。今回の変更は未コミット。push・PR・Issue・Project更新・配布は未実施 |

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
| MIG-005 | 進行中（Aのpure境界とBの短い実機／仮想比較） | route/tap/queueの10契約例+4入力bytes、UAC-232の交互3回とBlackHoleの2／16ch・4／8ch route経路を追加。動的route配送、時刻写像、排他/USB復帰/長時間は残る |
| MIG-006 | 進行中（Aとpure graphのB/C/Dを完了） | FFT24ケース/共有18ケース/履歴13契約・4入力にfilter21ケース×5 chunk/6 rate境界を追加。graph Rust38テスト合格。Eの校正/保存と実取得/Qt統合は未着手 |
| MIG-007〜008 | 未着手 | 計画にある依存関係に従う。採用判断までの検証範囲 |

`native/`にツールチェーン/SDKの固定、Cargo workspace/lock、模擬workerと2方式のadapter、共通QMLを置いた。
006-Aの`dsp-core`へFFT/窓/単位/PSD、006-Bの`graph-core`へ固定DAG・共有/購読/独立平均/cacheを追加。
005-Aの`audio-core`とCPAL 0.18.2の`audio-probe`を追加した。
006-Cは`graph-core`内にworker所有履歴/有理数時刻/旧世代公開のfenceを追加した。
006-Dで同じgraphへf64の一段filter/rate stateと派生世代fenceを追加した。
現行PortAudioは比較基準。永続取得schedulerとgraph/Qt接続、製品backend共通化は未作成。
候補実装は契約v0.1を出発点とし、公開型・ABI・採用ライブラリは後続の検証で決める。

## MIG-006-Dの成果と検証

着手: 2026-09-30、HEAD `a0d1bdb6`、006-Cのブランチはremote一致・clean。
前回記録の「006-C未コミット」は古く、このcommitへ保存済みと確認した。
同じworktreeで`codex/migration-006-d`へ分岐。今回の変更は未コミット。
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
4. [作業票](tasks.md)の006-Eまたは005-A/Bの残る境界へ進める。006-Aの保存コーパス/Intel編集、006-B/C/Dのpure graph/履歴/filter、004-BのIntel反復は完了した。
   Linux CIのICU修正は004-Bの`e0b992ce`へcommit済み。修正後のGitHub実行は未確認。公開する段階で確認する。
   ARM/Windows/Linuxの反復測定、full Xcode、release/clean環境の配布起動は未確認のまま残す。
5. 003-A/B/Cの保存入力と期待値は揃った。候補実装へ同じbytesを通し、参照側の完了と実装のAC合格を分ける。
6. 006-Cのpure履歴/Timebaseは共有graphへ接続済み。005-Aのpure queue/route、005-Bの実機とBlackHoleの診断経路は追加済み。
   以後はBlackHole 16ch／2chで通常の回帰を行う。UAC-232は実機が必要な要件だけに使う。
   006-Dのfilter/rateもpure graphへ接続済み。次は校正/保存、または動的route配送・実取得のgraph接続を検証する。
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
