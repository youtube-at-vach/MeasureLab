# MIG-007-A 取得中のQt校正profile編集・適用

[セッションID校正](calibration-display.md)の次の検証単位。
[決定0023](../migration/decisions/0023-qt-calibration-edit.md)と[進捗](../migration/status.md)を参照。
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

## 診断証拠と再検査

`evidence` 指定時は各完了操作のreceiptと、適用後最初の通常resultを追加保存する。
既存Triggerの完全result/取得窓bytesも保存する。BlackHoleの通常結果には実取得窓bytesを追加する。
既存fileを上書きしない。JSON/CSVは診断v1形式で、一組のatomic commitではない。
保存replayのJSON/CSVは同期診断I/O。liveでは通常結果を最大8件、Trigger診断を最大8件の
owned snapshot/receiptと取得窓bytesとして保持し、stream/graph停止後に完全JSONを保存する。
同じTrigger世代/revision/statusのretry診断は最初の一件にまとめる。
容量超過は `live_evidence_capacity` / `live_trigger_evidence_capacity` のfailureにする。
小さな校正操作receiptは取得中に保存する。CSVは停止後に保存済みJSONを再読込する。
最終profileが空になっても旧snapshotの校正情報を捨てない。
診断I/O失敗は従来どおりworker failureであり、長時間・定常性能の合格には数えない。

先に[両Qtのbuild](qt-probe.md#導入とビルド)を行う。

```bash
./.venv/bin/python scripts/migration_qt_calibration_edit.py --qt-prefix .tools/qt/6.11.2/macos --all-inputs --output .migration-local/007-calibration-edit-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_calibration_edit.py tests/logic_verification/test_migration_qt_calibration.py tests/logic_verification/test_migration_qt_trigger.py tests/logic_verification/test_migration_qt_workspace.py
```

既定は保存4/8ch f32/f64×9言語×両Qt。単一言語には `--language ja` を使う。
初期校正→係数変更→誤binding拒否→無効化→未指定ChannelIdへの追加を検査する。
通常/Triggerの全相対・絶対配列を元bytesの独立NumPy oracleへ比較し、CSVを完全再読込する。
同じ区間のraw ID/追加FFT件数、両viewの保持/分離、GUI停止中の取得継続、停止/再開/Backend破棄も確認する。
元fixture/許容差を変更せず、期待配列はQtへ送らない。QMLのJSONでは整数値のfloatが整数表記になるため、
期待型がfloatのfieldだけを同じ数値へ正規化する。ID/世代/revision/sampleの整数型と全値の比較は維持する。
実翻訳ラベル、非切詰め、ダイアログ/主画面のサイズ、主画面と編集contentのPNGを記録する。

```bash
./.venv/bin/python scripts/migration_qt_calibration_edit.py --virtual-device --qt-prefix .tools/qt/6.11.2/macos --repeat 3 --output .migration-local/007-calibration-edit-live-new
```

BlackHoleは2→2/4-from-16/8-from-16。ほかのGUI/build試験が終了してから実行する。
system default deviceは変更しない。元取得bytesを比較し、callback error/XRUN/rejected/gapとstream回収を検査する。
係数は診断用であり、物理校正の証拠ではない。製品保存UI/互換/async、profile期限/周波数・位相/SPL map、
実window manager、他OS、負荷下・長時間性能、採用判断は後続。
