# Rust core段階導入の評価計画

更新: 2026-10-04。[MIG-008の判断](../migration/decisions/0037-mig008-integrated-evaluation.md)により、
Rust/QMLの一括展開を見送り、現行Python/PyQt GUIへのRust core段階導入を評価する。
MIG-008の統合・短い比較・四案の判断は完了。製品への組込み・切替は未実施。
現在地と保存済みの記録は[進捗](../migration/status.md)、buildは[native手順](../native/README.md)。

## 次の対象と完了条件

対象は現行Spectrum Analyzer一つへのRust FFT／共有resultの接続評価。
現行の音声I/Oとrendererを使い、同じ入力・窓・精度・区間・更新条件で利益を判断する。
Python bindingはまだ実装していない。今回の掃除では新しいbindingや製品機能を追加しない。

| 確認すること | 完了条件 |
| --- | --- |
| 数値と来歴 | FFT・peak/RMS/PSD、ChannelId、区間、Timebase、世代、校正revision、validityが境界を通って一致する。f32/f64を暗黙に変換しない |
| 所有権と停止 | 配列のcopy・寿命・結果の不変性、停止・再開・終了、失敗時の回収を確認する |
| 校正付き保存 | 元値・精度・単位・校正・区間を保存し、再読込で一致する |
| 実測の利益 | 同じ現行rendererでCPU/RSS、更新・応答、copy費用を短く比較し、導入するか現行Pythonを継続するか判断する |

利益を示せなければ現行Pythonを継続し、共有解析・履歴・不変snapshotの設計改善だけを取り込む。
数値・時刻・保存の誤りを性能改善で相殺しない。
[コア契約](../migration/contracts/core.md)と[数値基準](../migration/contracts/numerics.md)は意味・許容差の参照とし、
そこに記載された全機能・全構成の実装を、この評価の必須条件にしない。

## 残すもの

RustのDSP／共有graphと、そこから使う容量制限付きqueue、履歴、Timebase、Trigger、校正、保存codecを残す。
coreの回帰テストと[固定FFT fixture](../migration/fixtures/README.md)18条件を維持する。
元の入力・期待値・係数・許容差を変更せず、直接libraryを検証する。
MIG-008の判断と圧縮reportを保持し、終了したQt/QML・renderer・backend試作、評価CLI／runner、
台帳検査、重複計画・手順・中間生成物を除去する。過去のコードと詳細記録はGit履歴から復元できる。

## 現在の対象に含めないもの

- QML画面の全面展開、renderer追加比較、41機能の移行計画。
- CPAL／PortAudioの製品backend化、全MonitorTap、動的route、永続profile、VST／ネットワーク音声の先行試作。
- Windows・ARM、clean環境の配布、全機器・全rate・全校正構成の網羅検証。
- 長時間連続運転・耐久試験、10分×3回、全backend×全Qt×全言語×全chの反復。

これらは未確認のまま保持し、必要になった時点で目的と順序を決める。

## 検証と記録

変更した挙動の対象テストを実行する。通った検証は関連変更・新たな失敗がなければ繰り返さない。
MIG-008の完了済み2ch統合や全fixture再監査を、再開時の必須手順に戻さない。
固定fixtureのhash検査とcodecの入力検査は維持する。
Rust coreのCIは明示した手動実行だけとし、Python CIは通常どおり実行する。
Ruff lint/formatと、Markdown変更時のlintは[共通手順](../.agents/workflows/tool_usage.md)に従う。
UIサイズ検証はレイアウト・翻訳の変更時、またはCI相当の最終確認を依頼された場合に行う。

工程は本書、現在地は進捗、MIG-008の測定条件・四案の理由は判断0037に集約する。
小変更ごとの新規手順書・決定記録、source/binaryの複製、全artifactの再hash監査は追加しない。
