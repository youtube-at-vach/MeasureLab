# MIG-007-A 共有FFTの表示境界

保存済み入力を`audio-core` queue → `graph-core`取得履歴 → 共有FFT → 不変resultへ通し、
同じprojectionをSpectrumとSpectrogramへ表示する。模擬カウンターだけの004-Aとは別の実行物。
実音声デバイスを開かない。採用・性能・007-A全体の完了は未決定。

## ビルドと保存比較

[Qt環境](qt-probe.md#導入とビルド)のCargo/Rust/SDK環境を設定して実行する。
既存の依存版は更新せず、Cargo.lockへローカル3 crateだけを追加した。

```bash
cargo +1.98.1 build --offline --locked --manifest-path native/Cargo.toml -p cxxqt-display -p qtbridge-display
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p display-core
./.venv/bin/python scripts/migration_qt_display.py --qt-prefix .tools/qt/6.11.2/macos --repeat 3 --output .migration-local/007-display-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_display.py
```

runnerは新しい出力ディレクトリを要求し、既存結果を上書きしない。
003-Bの元bytes 4/8ch × f32/f64を両方式へ渡す。N/hop=4096、boxcar、48 kHz。
Qtのoffscreen/software/Basic styleを使い、SDK版、元manifest、source、runner、実行物のhashを記録する。
PythonはNumPy以外のGUI・音声・FFT依存をimportしない。CIの最小環境では`--portable`を明示する。

各実行には準備中cancel、注入した開始失敗、重複開始/停止、遅いGUI、旧世代拒否、
2view→1view→sessionだけ→最後の解除、Backend/表示再生成、動作中終了を含む。
終了コードに加え全marker、PNGのCRC/寸法/両plotの色付き画素、3世代分の完全なresultを要求する。
保存resultの全peak配列と軸を既存の理論/現行期待値へ照合する。期待値は再生成しない。

## 手動起動

runnerが生成した`request.json`を再利用できる。証拠保存先の`evidence`を`null`にしたコピーを作るか、
新しい空ディレクトリを指定する。同じprocessの世代番号で古いresultを上書きしない。
[Qt実行環境](qt-probe.md#共通画面と自動検証)のframework/plugin/QMLパスを設定する。

```bash
export MEASURELAB_DISPLAY_REQUEST="$PWD/.migration-local/manual-display-request.json"
native/target/debug/cxxqt-display
native/target/debug/qtbridge-display
```

Start replay/Stopは保存入力の反復取得を制御する。ch選択、クリックcursor、wheel zoom、Reset zoomは各viewで独立。
PNG pathを入力しSave imageを押す。画像取得中は表示snapshotを保持し、workerの解析は継続する。
失敗時は保存失敗を表示する。相対時刻はsample区間と公称rateから計算し、host時刻・物理clockとみなさない。

## 所有権・容量・表示の意味

- [display-core](display-core/src/lib.rs)は解析threadを所有し、Qtへ容量1の最新mailboxから通知する。
  mutex/JSON/ファイルI/Oは制御・解析側だけで使用する。音声callback向けの設計ではない。
- 最大16需要tokenを実graphの購読へ反映する。各完成窓の全購読が同じ`Arc<FftResult>`を受けたことを確認し、
  一度だけresult/projectionを作る。最後の需要解除で停止し、node/subscription/cache/in-flightの回収を検査する。
- 入力は最大4096 frame × 16ch、履歴は2N、queueは2048 frame。GUI履歴は最新32表示snapshot。
  最新mailbox・各projectionの容量は制限されるが、外部保持snapshotやprocess RSSの上限保証ではない。
- GUIは全binのf64値をJSONで受け、cursorは元値を読む。描画だけが画素列ごとの最大値へ縮約する。
  非有限/invalidは`null`とreasonを保持し、正常なzeroへ置換しない。dBFS peakの描画下限は−120 dB。
- heatmapは取得sample区間で行を配置する。GUIが表示しなかった区間を空白にし、取得gapと区別する。
  再開世代で表示履歴を消去する。line/heatmapが同じ不変projectionを参照する。
- QML文言は既存評価プローブと同じ`qsTr()`。英語のimplicit layout由来の最小サイズを検査する。
  製品`tr()`/翻訳JSONとの接続と9言語QML評価は未実装。

実音声/Qt接続、trigger UI、基本校正の操作と製品save互換、分離window、9言語、GPU描画、
10分性能/CPU/RSS、QML編集反復、他OS/配布は未確認。
AC05とAC07/13の保存replay表示境界までの結果であり、AC08のtrigger表示やAC15/16の合格ではない。
[決定0016](../migration/decisions/0016-shared-result-display.md)と[進捗](../migration/status.md)を参照。
