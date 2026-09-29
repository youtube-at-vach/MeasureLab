# 検証環境と再開手順

MIG-001、2026-09-29。[進捗・作業場所](status.md)と[評価計画](../guide/RUST_QML_MIGRATION_PLAN.md)を参照。
以下は検証worktreeのルートで実行する。既存mainのvenvを共有・コピーしない。

## 確認済み環境

| 項目 | 実測・導入状態 |
| --- | --- |
| OS / CPU | macOS 14.8.9、Intel x86_64 |
| Python | 3.12.14（MacPorts）、worktree専用`.venv/` |
| Python依存 | `constraints.txt` + `.[dev]`。PyQt6 6.11.0 / Qt runtime 6.11.2 |
| Rust / Cargo | 1.98.1、`native/rust-toolchain.toml`に固定 |
| Rust components | rustfmt、Clippy、host標準ライブラリ |
| C++ | Apple Clang 16.0.0、Command Line Tools |
| CMake / Ninja | 4.4.3 / 1.13.2、`.tools/build-venv/`へ分離 |
| Node.js / npm | 22.22.2 / 10.9.8（既存MacPorts環境） |
| Qt開発用SDK | 未導入。qmake未検出、pkg-configでQt6Core未検出 |
| CXX-Qt / Qt Bridge | 未導入・未選定。MIG-004で同じ条件により比較 |

PyQt6 wheelのQt runtimeをC++開発用SDKとして扱わない。
Qt接続の必要条件は[CXX-Qt公式ガイド](https://kdab.github.io/cxx-qt/book/getting-started/index.html)を確認し、
MIG-004でQt・接続ライブラリ・C++コンパイラの組合せを記録する。
本タスクのRust固定は評価環境の出発点であり、本格採用の判断ではない。

## Python参照環境

このworktreeでは導入済み。新しい環境で再構築する場合だけ実行する。

```bash
python3.12 -m venv .venv
./.venv/bin/python -m pip install -U pip
./.venv/bin/python -m pip install -c constraints.txt -e '.[dev]'
./.venv/bin/python -m pip check
./.venv/bin/python -m pip show MeasureLab
```

`Editable project location`が作業中のworktreeであることを確認する。
VSTの任意依存`pedalboard`はこの初回作業では導入していない。VST検証時に`.[dev,vst]`を使う。
全推移依存のlockではなく、既存プロジェクトのconstraints方式を踏襲している。
参照データ生成時にはMIG-003で実際の全依存バージョンもメタデータへ保存する。

参照版の起動:

```bash
./.venv/bin/python scripts/migration_reference.py --check
./.venv/bin/python scripts/migration_reference.py
```

表示を必要としない起動確認:

```bash
QT_QPA_PLATFORM=offscreen ./.venv/bin/python scripts/migration_reference.py --state-dir .migration-local/self-test --self-test
```

参照スクリプトは通常の`main_gui.main()`を呼ぶ。プロセス内に限定してConfigManagerの保存先を差し替え、
FFT用の`XDG_DATA_HOME`を設定する。`src/`と`main_gui.py`は変更していない。
GUIのテスト用スタブは使わず、`MEASURELAB_TESTING=0`として分離した設定を実際に読み書きする。
`--check`も専用設定の初期化を行う。単なる読み取り専用コマンドではない。

| データ | 既定の保存先 |
| --- | --- |
| 設定・校正・ログ | `.migration-local/reference/` |
| FFT wisdom | `.migration-local/reference/data/MeasureLab/wisdom/` |
| スクリーンショット | `.migration-local/reference/screenshots/` |
| 起動self-test | 明示した`.migration-local/self-test/`以下 |

毎回オフラインモードで起動し、PipeWire/JACK resident設定も無効にする。
既存のportable `config.json`を優先する経路も差し替えるため、mainやworktreeのportable設定を読み込まない。
旧版の設定・校正を自動でコピーしない。保存済みの参照版の言語等は維持する。
これは既定の保存先の分離であり、GUIから明示的に指定するエクスポート先等を制限する仕組みではない。
実機を使う場合はGUIで切り替え、現行版とデバイスを同時に開かず一方ずつ測定する。

検証側では上の専用スクリプトから起動する。直接`main_gui.py`を起動すると、従来のユーザーデータ保存先が使われる。
将来のネイティブ版は、この参照版とも別のアプリ名・保存先・スキーマを使う。

## ネイティブ開発ツール

導入と確認は[nativeの準備手順](../native/README.md)を参照する。
`.tools/`にRustとCMake/Ninjaを置き、シェルの設定ファイルやOSの既定ツールを変更していない。
新しいシェルでは環境変数の設定が必要になる。

## 今回の検証を再実行

```bash
./.venv/bin/python -m pytest -q tests/logic_verification/test_migration_reference.py tests/logic_verification/core/test_config_manager.py tests/logic_verification/core/test_utils.py tests/logic_verification/gui/test_main_window_activity.py
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

新しいテストは、別プロセスで設定・校正・wisdom等の分離先と、既存portable設定を上書きしないことを確認する。
GUI self-testは上記コマンドでPytestと別に実行する。
PR前には[CI Pre-checker](../.agents/skills/ci-prechecker/SKILL.md)の全項目を追加で実行する。
