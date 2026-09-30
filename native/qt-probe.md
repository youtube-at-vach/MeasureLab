# MIG-004-A Qt接続プローブ

この実行物はQt境界の比較用で、音声デバイス・測定DSP・共有Analysis Graphを含まない。
採用判断は[評価計画](../guide/RUST_QML_MIGRATION_PLAN.md)のMIG-008で行う。
実施結果は[進捗](../migration/status.md)と[比較記録](../migration/decisions/0005-qt-boundary-probes.md)を参照。

## 固定する組合せ

| 対象 | 固定値 |
| --- | --- |
| Rust | [rust-toolchain.toml](rust-toolchain.toml)の1.98.1 |
| Qt開発SDK | [qt-sdk.toml](qt-sdk.toml)の6.11.2、qtbase/declarative/tools/svg/translations |
| CXX-Qt | 0.10.0 |
| Qt Bridge | 0.3.0（公式リリースの位置付けはbeta） |
| CXX | 1.0.202。生成器cxx-gen 0.7.202と揃える |
| 全Cargo依存 | [Cargo.lock](Cargo.lock)を保存、通常buildは`--locked` |
| 導入・ビルド道具 | [build-requirements.txt](build-requirements.txt)、aqtinstall 3.3.0 |

[QtのmacOS要件](https://doc.qt.io/qt-6/macos.html)はXcode 15/macOS 14 SDK以上、実行先macOS 13以上。
このIntel MacはmacOS 14.8.9、Apple Clang 16/SDK 15.2のCommand Line Toolsで試す。
完全なXcodeは未導入なので、公式の開発環境要件をすべて満たしたとの扱いにはしない。
[Qt Bridge 0.3のREADME](https://github.com/qt/qtbridge-rust/blob/d9a89bc1767a444f280e0548edddbd5b2023104c/crates/qtbridge/README.md)は
Rust 1.88以上・Qt 6.10以上とQt private headersを要求する。macOSの記載はarm64 experimentalで、Intelは未掲載。
Intelで動いても、ARM・Windows・Linuxへの外挿はしない。

## 導入とビルド

リポジトリルートから実行する。SDKはPyQtのruntimeと別の`.tools/qt/`へ置く。
次はmacOS用。aqtinstallはQtの配布アーカイブを取得する外部ツールで、Qt公式インストーラーではない。
既に導入済みならinstallは繰り返さない。シェル設定やシステムQtは変更しない。

```bash
.tools/build-venv/bin/python -m pip install -r native/build-requirements.txt
.tools/build-venv/bin/aqt install-qt mac desktop 6.11.2 clang_64 --outputdir .tools/qt --archives qtbase qtdeclarative qttools qtsvg qttranslations --keep --archive-dest .tools/downloads/qt-6.11.2
export CARGO_HOME="$PWD/.tools/cargo"
export RUSTUP_HOME="$PWD/.tools/rustup"
export PATH="$CARGO_HOME/bin:$PWD/.tools/build-venv/bin:$PATH"
export QMAKE="$PWD/.tools/qt/6.11.2/macos/bin/qmake"
export CARGO_BUILD_JOBS=4
export MACOSX_DEPLOYMENT_TARGET=13.0
"$QMAKE" -query QT_VERSION
cargo +1.98.1 build --locked --manifest-path native/Cargo.toml
cargo +1.98.1 fmt --manifest-path native/Cargo.toml --all --check
cargo +1.98.1 test --locked --manifest-path native/Cargo.toml -p probe-core
cargo +1.98.1 clippy --locked --manifest-path native/Cargo.toml --workspace --all-targets -- -D warnings
```

初回のみ依存解決でCargo.lockを作る。更新は両接続方式の再検査と一緒に行う。
004-B以降はmacOSの最小対象を明示する。SDK版を最小OS版に使う既定値を避け、両方式の条件を揃える。
CXX本体とcxx-genの不一致はリンクエラーになるため、片方だけの更新はしない。
Qtのheaders、`libexec/moc`、`qmltyperegistrar`、frameworksがこのSDK内に存在することを確認する。

## 共通画面と自動検証

両実行物は[同じQML](qml/Main.qml)をファイルから読み、同じ[模擬ワーカー](probe-core/src/lib.rs)を使う。
GUIに公開するのは状態・世代・結果番号・表示更新の省略数と、2行のリストモデル。
数値処理、オーディオ取得、校正・保存は実装しない。
QML表示文言は`qsTr()`を使う。現行Pythonの`tr()`/翻訳JSONへの登録は、評価画面を製品へ統合するときに扱う。

```bash
./.venv/bin/python scripts/migration_qt_probe.py --qt-prefix .tools/qt/6.11.2/macos --repeat 3 --report .migration-local/qt-probe.json
```

runnerは明示された開発SDKを使い、offscreen/software/Basic styleで実行する。
SDK版、入力QML、Cargo.lockとRustソース、実行物のhashを記録する。
開始準備中のcancel、開始失敗、重複Start/Stop、list modelの通知、160 msのGUI停止中のworker継続、
通知の集約、旧世代拒否、動作中のBackend破棄・再生成、動作中の終了とworker/model回収を検査する。
2viewと模擬保存sessionが別tokenを持ち、一方のviewを閉じても残るviewへ同じモデルを供給する。
両viewを閉じた後はsessionだけで継続し、最後の解除で停止する。共有view windowの破棄・再生成も検査する。
終了コード0だけでは合格にせず、ready・全シナリオ完了・破棄完了のmarkerをすべて要求する。
timeoutや`PROBE_FAIL`も不合格にする。QMLのassertが失敗した後に正常終了しても合格にしない。

通常のウィンドウで試す場合は、自動検証と同じSDKを明示する。

```bash
export DYLD_FRAMEWORK_PATH="$PWD/.tools/qt/6.11.2/macos/lib"
export QT_PLUGIN_PATH="$PWD/.tools/qt/6.11.2/macos/plugins"
export QML_IMPORT_PATH="$PWD/.tools/qt/6.11.2/macos/qml"
export QT_QUICK_CONTROLS_STYLE=Basic
native/target/debug/cxxqt-probe
native/target/debug/qtbridge-probe
```

画像確認は実行物に`--snapshot <絶対パス.png>`を渡す。500 ms後にQML canvasを保存して終了する。
この画像はwindow frameを含まず、物理モニター上の操作確認の代わりにはならない。
生成物とSDKはGit管理外。配布用のbundleを作る手順ではない。
004-Bの反復測定・ローカルbundle起動は[別手順](qt-iteration.md)で行う。

## 所有権と今回の境界

- QObject/Qt BridgeのRust objectが`Probe`を所有する。破棄時はstopを設定し、workerをjoinしてから状態を解放する。
- workerはQtの表示データへ直接書かない。CXX-Qtは`CxxQtThread::queue`、Qt Bridgeは`QmlMethodInvoker`でGUIへ通知する。
- GUI向けmailboxは容量1で最新snapshotに置換し、未処理の通知があれば追加通知を省略する。
  snapshotとpending bitは同じmutexで管理し、Qtへの呼出し中はmutexを保持しない。
- generationの違う通知は新しいsnapshotとpending bitを変更しない。失敗・cancel・正常stopを別outcomeにする。
- tokenはプロセス内で一意に発行する。他のProbeのtokenや重複解除を拒否し、最後の需要がなくなるとstopする。
- このmutexとjoinは模擬worker/制御側のもの。実音声callbackへ適用できる設計・RT保証ではない。

Analysis Graphのnode/result所有権、実保存session、アプリ全体のwindow root再生成、例外注入、
10分連続・負荷・配布・他OS・全言語QMLは後続検証。
AC07全体やAC13の実デバイス/callback回収の合格には数えない。
runnerの時間は診断用の短時間試行で、[性能protocol](../migration/benchmarks/protocol.md)による方式の優劣判定には使わない。

Python CIから独立した[Native evaluation](../.github/workflows/native-evaluation.yml)を追加する。
pure coreの検査とQt SDKを使うLinux境界検査を分離する。GitHub上で実行されるまではCI成功と扱わない。
