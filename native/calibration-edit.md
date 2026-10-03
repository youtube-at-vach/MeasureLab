# MIG-007-A 取得中のQt校正profile編集・適用

[セッションID校正の実装](display-core/src/calibration.rs)の次の検証単位。
[進捗・検証結果](../migration/status.md)を参照。
製品設定の永続化やRust/QML採用の決定ではない。

## 操作・所有境界

共通QMLの「校正を編集」からChannelId、V/FS、profile revision、電圧校正の有効/無効を編集する。
device/portは実取得設定から読み取り、表示結果の校正やprofile配列順で対応を決めない。
未指定チャンネルにもprofileを追加できる。他のチャンネルのprofileは維持する。
適用中・適用済み・拒否・停止によるキャンセルを実workerのreceiptから表示する。
停止中の適用は無効。未適用の編集値だけでは測定表示を変更しない。

両Qt adapterの `apply_calibration()` は最大16 KiBのtyped要求を一件だけmailboxへ渡す。
入力は `generation`、単調増加する操作 `revision`、全 `profiles` 配列。
未知field/不正JSON/容量超過、busy、旧世代、重複・逆順revision、停止中を同期的に拒否する。
`true` はenqueue成功であり、適用成功ではない。

解析ownerは一操作を原子的に検証・置換する。既存のChannelId/device/port/重複/係数/revision検証を使い、
一件でも不正なら全profileを維持して `rejected` を返す。取得をfailureにしない。
停止が先なら `cancelled`、適用が先なら `applied` を保つ。
操作revisionは拒否でも消費する。音声callback、queue容量、取得世代、履歴、FFT keyは変更しない。

適用後に生成する通常/Trigger結果だけが新profileを使う。旧区間への新しいTrigger要求も新profileを使うが、
完成済みの保持resultは再校正しない。同じ区間のraw FFTを再利用し、各結果の実区間を `applied_interval` に記録する。
Triggerは解析ownerのprofile providerを実取得区間で一度だけ呼び、未校正の完全resultを経由せず生成する。
pending/gapではproviderを呼ばず、既存の未校正APIとcapture metadata/raw共有を維持する。
FS/Hz/SPL/未知clockの既存契約は維持する。絶対値を作れない場合はnull/reasonを保持する。
この段階の編集はセッション内だけで、Stop→StartやBackend再生成では初期セッション設定へ戻る。
ダイアログにもこの範囲を表示する。製品用の保存・再起動維持は後続。

## 対象変更の検証

現在の範囲は[MIG-008計画](../guide/RUST_QML_MIGRATION_PLAN.md)に従う。
関連する変更がある場合だけ[対象テスト](../tests/logic_verification/test_migration_qt_calibration_edit.py)と[runner](../scripts/migration_qt_calibration_edit.py)を使う。
オプションは`./.venv/bin/python scripts/migration_qt_calibration_edit.py --help`で確認する。
全条件の再実行・長時間試験・他OS検証はMIG-008の前提にしない。
