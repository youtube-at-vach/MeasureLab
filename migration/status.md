# 次期コア検証の進捗

更新: 2026-09-29。計画の正本は[評価計画](../guide/RUST_QML_MIGRATION_PLAN.md)。
Rust/QMLの採用は未決定。最初の作業はMIG-001に限定し、現行版を比較対象として動かす環境を整える。

## 作業場所と基準

| 項目 | 値 |
| --- | --- |
| 現行版 | `/Users/vach/MeasureLab`、`main` |
| 検証用worktree | `/Users/vach/.codex/worktrees/next-core-evaluation/MeasureLab`（Codex管理） |
| 検証用ブランチ | `codex/next-core-evaluation` |
| 作業開始・Python参照コミット | `9fd79958`（MeasureLab 0.9.0、開始時のローカルmain） |
| 計画書の調査コミット | `68cbdabc3ecd542d9d73fa0aa86bf9159f44d811` |
| 最終main同期 | 2026-09-29、`9fd79958`から分岐 |
| 統合担当 | 当面、この検証ブランチを担当する単一の作業者 |
| リモート | 初回作業はローカル。push・PR・Issue・Project更新・配布は未実施 |

調査コミットから開始時mainまでの差分には計画書、設計ガイド、Measurement Consoleのレイアウト、
Goniometerのテーマ対応、翻訳と対応テストがある。数値fixtureはまだ作成していない。
MIG-002の棚卸しでは開始時mainを確認し、MIG-003で参照コミットを入力・期待値と一緒に固定する。

## タスク

| タスク | 状態 | 成果・次の判断 |
| --- | --- | --- |
| MIG-001 | 完了 | 管理されたworktree、専用Python環境、状態を分離したオフライン起動、Rust/C++ビルドツール、再開・同期手順 |
| MIG-002 | 未着手・次に実施 | 41機能と共通機能の台帳、プリミティブ台帳、言語非依存のコア契約・比較基準 |
| MIG-003 | 未着手 | MIG-002に沿った参照ランナー、仮想4/8ch、理論値付きfixture |
| MIG-004 | 未着手 | Qt開発用SDKの導入・版固定、CXX-Qt/Qt Bridge比較、GUIと配布経路 |
| MIG-005〜008 | 未着手 | 計画にある依存関係に従う。採用判断までの検証範囲 |

`native/`にはツールチェーンの固定と準備手順のみを置いた。
Cargo workspace、クレート、Cargo.lock、QML、音声backendは未作成。
MIG-002の契約より先に公開型や仮のDSP実装を固定しない。

## 最後に確認したこと

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
3. MIG-002を機能台帳、プリミティブ対応、信号・時刻・validity契約、数値・反復速度基準に分割する。
4. 41モジュールのキーと共通・外部連携を現行コードから棚卸しする。全項目を未着手として登録し、サブ機能・参照テストを追記する。
5. 最初の生成→取得→共有FFT→複数表示→校正情報付き保存と、仮想4/8chの終了条件を先に定める。
6. ChannelId、Stream世代、Timebase、Trigger、Routing/MonitorTap、validity・FFT共有の契約を記録する。
7. 契約ごとに後続タスクを切り、MIG-003/004へ進む。MIG-002完了とRust/QML採用決定を混同しない。

長時間の自動実行や定期通知は設定していない。次回もこのworktreeを再利用できる。
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
