# 分離表示と9言語の検証

MIG-007-Aの[共有result表示](display-candidate.md)へ、共通の分離wrapperと既存の翻訳JSONを接続する。
評価画面の実装であり、製品のDetachable Wrapperや41モジュールの移植・技術採用ではない。

## 再実行

[Rust/Qt環境](README.md#このworktreeで使う)を設定する。依存版・fixture・数値許容差は変更しない。

```bash
export QMAKE="$PWD/.tools/qt/6.11.2/macos/bin/qmake"
cargo +1.98.1 build --offline --locked --manifest-path native/Cargo.toml -p cxxqt-display -p qtbridge-display
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p display-core --features live-audio
./.venv/bin/python scripts/migration_qt_workspace.py --qt-prefix .tools/qt/6.11.2/macos --all-inputs --output .migration-local/007-workspace-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_workspace.py tests/logic_verification/test_migration_qt_display.py tests/logic_verification/test_migration_qt_live.py
./.venv/bin/python scripts/check_trn_keys.py --strict
./.venv/bin/python scripts/check_ui_size_limits.py
```

既定は最大の8ch f64入力×9言語×両Qt方式の18実行。`--all-inputs`は4/8ch f32/f64の72実行。
`--language ja`などで限定でき、`--repeat`で反復する。常に新しいdirectoryを要求する。
各実行で4世代の完全result、メイン画面と2つの分離画面のPNG、実ラベル・最小サイズ・寿命を記録する。
元の全peak/軸を理論・現行fixtureへ照合し、PNGのCRC/寸法/実プロット領域の画素も要求する。

実入力回帰は[BlackHole手順](live-display.md)を使う。取得queueの負荷を変えないため、
他のQt・renderer・build試験と同時に実行しない。失敗したrunも保存し、成功扱いしない。
これは短い正しさ検査であり、負荷超過時の性能判断は007-Bで行う。

## 所有権と操作

- [PlotPane](qml/PlotPane.qml)がSpectrum/Spectrogramを包む。分離時は同じviewをWindowへreparentする。
  結果snapshot・購読token・ch/cursor/zoom・表示履歴は維持する。再接続で購読を増やさない。
- 分離Windowを閉じるとviewを破棄して実需要を解除する。他のview/sessionがあれば解析を継続する。
  最後の解除で取得workerとgraphを停止・回収する。「表示を開く」は通常表示で新たに購読する。
- Backend再生成は分離Windowを隠し、先にview需要を解除してから旧Backendを破棄する。
  viewは購読時のQObjectを保持し、そのQObjectへ解除する。分離中のアプリ終了も検査する。
- メインの「画像を保存」はメイン画面、各viewの同じボタンはそのviewを撮影する。
  PNG保存先は共通欄で指定する。撮影中は不変projectionを保持し、解析workerは継続する。
  分離画像にも背景を含める。表示の間引き配列を測定resultの保存へ流用しない。

## 翻訳とサイズ

[en.json](../src/assets/lang/en.json)を正本に35キーを9言語へ追加した。
[Rustのlocale境界](display-core/src/locale.rs)で各catalogを実行物へ埋め込み、Qt adapterのpropertyから
QMLの`tr()`へ渡す。読み込みはGUI側で行い、取得worker/音声callbackへ翻訳処理を加えない。
既定は英語、`--language en/de/es/fr/ja/ko/pt/ru/zh`で起動時に選ぶ。未知言語を暗黙に補完しない。

```bash
export MEASURELAB_DISPLAY_REQUEST="$PWD/.migration-local/manual-display-request.json"
native/target/debug/cxxqt-display --language ja
native/target/debug/qtbridge-display --language de
```

requestの用意は[保存表示](display-candidate.md#手動起動)または[実入力](live-display.md#手動表示と残る範囲)を参照する。
論理ID、状態code、結果・単位・reasonの保存値は翻訳しない。`%1`〜`%4`の置換fieldを全言語で維持する。
翻訳check/updateの双方が同じQML source inventoryを参照し、QMLだけのキーも未使用扱いで削除しない。
renderer spikeの既存SpectrumViewにも同じ英語catalogを供給し、描画領域・操作条件は維持する。

Qt SDKの既定font/offscreen/software/Basicで、mainと各分離Windowのlayout由来の最小サイズを1180×690以内とする。
実行物が表示したcatalog/ラベル・buttonの必要幅と実幅・PNGを照合する。
既存Python全言語UIのサイズ検査は別プロセスで行い、QMLの合格とは分ける。

## 残る範囲

AC05/07/13の保存入力と分離寿命、007表示画面の9言語まで。
offscreenでは実window managerの移動/最小化/focusや他OSのfont/DPI差を検証できない。
起動後の言語変更、他OS/package、全製品モジュール、trigger/校正/製品保存UI、10分性能は未確認。
最終結果と開発中の失敗は[進捗](../migration/status.md)へ記録する。
