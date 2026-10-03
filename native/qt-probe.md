# Qt SDKと初期probeの起動

現在の主経路はCXX-Qt。Qt Bridgeの既存結果を比較へ利用する。
SDK/toolchain設定とbuildは[共通native手順](README.md#このworktreeで使う)を参照。
Qt SDK 6.11.2 / CXX-Qt 0.10.0 / Qt Bridge 0.3.0は固定済みで、再導入は不要。

## 共通画面

[初期QML](qml/Main.qml)と[模擬worker](probe-core/src/lib.rs)で、通知とStart/Stop/終了を試作した。
このprobeの成功は音声・共有解析・校正・保存を統合したMIG-008の結果には置き換えない。
初期probeを変更した場合だけ[runner](../scripts/migration_qt_probe.py)を使う。

```bash
./.venv/bin/python scripts/migration_qt_probe.py --qt-prefix .tools/qt/6.11.2/macos --report .migration-local/qt-probe-new.json
```

## 手動起動

native環境を設定したシェルでplugin/QMLパスを指定する。

```bash
export QT_PLUGIN_PATH="$PWD/.tools/qt/6.11.2/macos/plugins"
export QML_IMPORT_PATH="$PWD/.tools/qt/6.11.2/macos/qml"
export QT_QUICK_CONTROLS_STYLE=Basic
native/target/debug/cxxqt-probe
```

実入力の主画面は[BlackHole表示](live-display.md)を使う。
[MIG-008計画](../guide/RUST_QML_MIGRATION_PLAN.md)に従い、Windows・ARM、配布環境構築、長時間試験は行わない。
