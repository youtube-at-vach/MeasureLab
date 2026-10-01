# MIG-007-A セッションID校正の取得・Qt接続

2026-10-02。[006-Eの不変result/校正](result-candidate.md)を、保存replayとBlackHoleの
通常/Trigger結果へ接続する。[決定0022](../migration/decisions/0022-session-calibration-display.md)と
[進捗](../migration/status.md)を参照。診断係数による境界評価で、実deviceの物理校正ではない。

## 設定・所有境界

`MEASURELAB_DISPLAY_REQUEST` のJSONへ任意の `calibration` 配列を追加する。
省略時は従来の全チャンネル未校正。各要素は次の型で、未知fieldは拒否する。

```json
{
    "channel_id": "input.logical.0",
    "revision": "diagnostic.profile.1",
    "device_binding": {"device": "BlackHole 16ch", "port": 15},
    "is_calibrated": true,
    "v_per_fs": 2.0
}
```

入力は最大16ch、profile件数は入力数以下。重複/未知ChannelId、空白または256 bytes超のrevision、
非正/非有限係数、device/port不一致をstream開始前に拒否する。
liveのdeviceは完全一致名、保存入力は `saved:<stream_id>`。portはそのChannelIdの
`format.input_ports` と一致させる。配列順を信号順や校正対応として扱わない。

解析ownerが既存の共有raw FFTへ後段校正を適用する。通常の各購読は同じraw Arcを受け、
一つの不変result/projectionを両viewへ渡す。Triggerの履歴/共有raw/cache/FFT件数は変更しない。
各profileの `applied_interval` は実際の結果区間で、profileの有効期限を推定した値ではない。
校正係数の正しさや期限は、このセッション設定境界では検証しない。

FS/nominal Hzは保持し、V RMS/dBV/PSD V²/HzだけをID校正する。
未指定または `is_calibrated:false` は絶対値をnull/uncalibratedにする。SPLも未校正のまま。
未知clock原点/写像やhost時刻を推定しない。invalid/nonfiniteの理由は維持する。

共通QMLは選択チャンネルのV RMS/dBVとprofile revision/V/FS/portを表示する。
線とheatmapは引き続きFS。表示文言は既存翻訳JSONの `tr()` で9言語を管理する。
保持/分離/履歴失効/停止/新世代/Backend破棄でも完成resultは不変。
初期設定は次セッションにも使う。取得中のQt編集・適用mailboxは[後続の検証単位](calibration-edit.md)で追加した。

## 診断保存と再検査

`evidence` を明示した場合、最初の通常結果と完成Trigger結果を既存v1 JSONへ保存する。
保存replayは校正配列がある時に同じ完全resultのCSVも保存する。liveは停止後に全saved snapshotのCSVを保存する。表示間引きを保存しない。
既存 `save_new` のno-clobber/atomicな一ファイル公開を使い、失敗はworker failureとして返す。
JSON/CSVの一組のatomic commitではない。保存replayでは解析owner上の同期診断I/O。liveの通常/Trigger JSONは
[編集・適用の検証](calibration-edit.md)で容量を限定したsnapshot/bytes保持と停止後保存へ移した。
CSVはstream/graph停止後にJSONの完全snapshotを一件ずつ再読込して保存する。
CSVの重いencodeを取得queueの時間予算へ持ち込まない。CSV失敗は終了時にも失敗として報告する。
製品の非同期保存UIではない。

[Rust/Qt環境](README.md#このworktreeで使う)を設定し、新規出力先を使う。

```bash
export QMAKE="$PWD/.tools/qt/6.11.2/macos/bin/qmake"
cargo +1.98.1 build --offline --locked --manifest-path native/Cargo.toml -p cxxqt-display -p qtbridge-display
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p display-core -p graph-core
./.venv/bin/python scripts/migration_qt_calibration.py --qt-prefix .tools/qt/6.11.2/macos --all-inputs --output .migration-local/007-calibration-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_calibration.py tests/logic_verification/test_migration_qt_trigger.py tests/logic_verification/test_migration_qt_display.py tests/logic_verification/test_migration_qt_live.py
```

保存4/8ch f32/f64×9言語×両Qt。port逆順、profile逆順、異なる係数、disabled/未指定profileを検査する。
通常/Trigger全resultの全相対配列とV/dBV/PSDを元bytesの独立NumPy oracleへ比較する。
CSVは独立Python reader、Rustの停止後再読込testで完全metadata/全値/null/reasonを往復する。
pending/gap非数値、共有raw/追加FFT件数、hold/分離/解除/再開/破棄は既存Trigger検査を維持する。
実ラベルの翻訳/表示値/revision、非切詰め、1180×690 px上限とPNGも検査する。

BlackHoleの同じ解析ownerへの短い診断は、他の音声/build/GUI検査と同時実行しない。

```bash
./.venv/bin/python scripts/migration_qt_calibration.py --virtual-device --qt-prefix .tools/qt/6.11.2/macos --repeat 3 --output .migration-local/007-calibration-live-new
```

2→2/4-from-16/8-from-16×両Qt。device完全一致、48 kHz/256 frame/f32、default deviceは変更しない。
元取得窓bytesから全数値列を再計算し、閉じたstream/error/XRUN/gapを確認する。
reportへsource/runner/binary/request/result/bytes/CSV/PNGのhashと実行出力を保存する。
異なる参照環境での比較は明示 `--portable`。元fixture/許容差は変更しない。

Qtのprofile編集・適用は[別作業票](calibration-edit.md)を参照。製品保存操作/互換/非同期化、校正期限/周波数・位相・SPL map、
物理校正、長時間/負荷下/他OS/実window manager、AC15/16、Rust/QML採用判断は後続。
