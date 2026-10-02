# 検証環境と再開手順

MIG-001、2026-09-29。Qt欄はMIG-004-A（2026-09-30）で更新。
[進捗・作業場所](status.md)と[評価計画](../guide/RUST_QML_MIGRATION_PLAN.md)を参照。
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
| Qt開発用SDK | 6.11.2、`.tools/qt/6.11.2/macos/`へ分離導入。qmake/moc/headers/private headers/frameworksを確認 |
| CXX-Qt / Qt Bridge | 0.10.0 / 0.3.0。共通QML・模擬workerでIntelの基本境界を検証。採用は未選定 |

PyQt6 wheelのQt runtimeをC++開発用SDKとして扱わない。
Qt接続の必要条件は[CXX-Qt公式ガイド](https://kdab.github.io/cxx-qt/book/getting-started/index.html)を確認し、
MIG-004-Aの[組合せ・起動手順](../native/qt-probe.md)と[SDK導入記録](qt/2026-09-30-intel-sdk.json)を参照。
Apple Clang 16/Apple SDK 15.2のCommand Line Toolsで試し、full Xcodeは未導入。
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

## Linuxでの再開

2026-10-02、`/home/hotstaff/MeasureLab`、Ubuntu 26.04.1 / x86_64へ開発環境を移した。
macOSのパスと上表は前回の記録。最新の実施範囲は[進捗](status.md)を参照。
Rust 1.98.1とQt SDK 6.11.2は同じ固定仕様で`.tools/`へ新規導入した。
SDKにはLinux専用の`icu` archiveを含め、`env -i .../bin/qmake -query QT_VERSION`で6.11.2を確認した。
システムQtやPyQt runtimeを開発SDKの代用にしない。

引き継いだPython 3.14.4 / NumPy 2.2.6では、filter参照の大きな配列が途中で変更され、
polyphase toneの理論出力が0になった。既存fixtureとの比較を失敗として残した。
[NumPyの既知問題](https://github.com/numpy/numpy/issues/28681)と一致する挙動を再現し、
[Python 3.14対応の2.3.3](https://numpy.org/doc/2.3/release/2.3.3-notes.html)へ更新した。
`constraints.txt`はPython 3.12/3.13の2.2.6を維持し、3.14以降に2.3.3を指定する。
Linux以外のPython 3.14環境の動作確認は含まない。

旧`.venv`の依存はroot所有で更新できなかったため、`.tools/venv-before-linux-os/`へそのまま保管した。
新しいユーザー所有の`.venv/`を作り、既存の導入版一覧からNumPyだけを置き換えて再導入した。
editable installはこのcheckoutを参照し、`pip check`は成功した。旧venvは実行環境の切替用に自動参照しない。
導入前後の全依存、SDK archive hashと失敗logは`.migration-local/2026-10-02-linux-os/`へ保存した。
SciPy 1.17.0 / Ruff 0.16.7等は引継ぎ版であり、`constraints.txt`全体との一致は主張しない。

システムにはGCC 15.2.0、ALSA headers、OpenGL runtimeがあるが、`libGL.so`の開発用リンクがなかった。
管理者権限を使わず、`.tools/system-lib/libGL.so`をシステムの`libGL.so.1`へリンクし、
ビルドだけに`LIBRARY_PATH`を指定した。Rust付属の`ld.lld`も`.tools/build-venv/bin/`へリンクした。
システムパッケージ、シェル設定、ユーザー共通Rust設定は変更していない。
通常の新規環境ではNative CIが指定する開発パッケージを導入し、この補助リンクは不要。

```bash
export CARGO_HOME="$PWD/.tools/cargo"
export RUSTUP_HOME="$PWD/.tools/rustup"
export PATH="$CARGO_HOME/bin:$PWD/.tools/build-venv/bin:$PATH"
export QMAKE="$PWD/.tools/qt/6.11.2/gcc_64/bin/qmake"
export CARGO_BUILD_JOBS=4
export LIBRARY_PATH="$PWD/.tools/system-lib"
export LD_LIBRARY_PATH="$PWD/.tools/qt/6.11.2/gcc_64/lib"
cargo +1.98.1 build --locked --offline --manifest-path native/Cargo.toml --workspace
cargo +1.98.1 test --locked --offline --manifest-path native/Cargo.toml --workspace
cargo +1.98.1 clippy --locked --offline --manifest-path native/Cargo.toml --workspace --all-targets -- -D warnings
```

Python参照起動とportable比較は、Qt SDK用の`LD_LIBRARY_PATH`等を外した別processで実行する。
Rust/Qtテスト実行物にはSDKのruntimeパスが必要で、指定しなかった初回はloaderのexit 127で失敗した。
GUI self-testは分離した設定を使う。BlackHoleはmacOS専用なので、このLinux環境の実音声試験には使わない。

## 音声テストの引き継ぎ

2026-09-30のユーザー指示: UAC-232でひとまず動作を確認済み。以後はBlackHole 16ch／2ch経由でよい。
通常の音声回帰、route／port対応、mute、start／stop、再オープンではこの2台を優先する。
UAC-232は物理ADC/DAC、hardware gain／電圧／配線、USB切断／復帰、物理遅延など、
実機でしか確認できない条件を検証するときだけ使う。
実機の未確認項目は残し、仮想deviceや保存fixtureで進められる工程を止めない。

```bash
./.venv/bin/python scripts/migration_audio_virtual.py --virtual-device --output .migration-local/blackhole-new-run
```

BlackHole 2ch／16chを完全一致で指定し、fallbackしない。48 kHz／256 frame／f32の短い診断。
指定したBlackHoleのrate／frame sizeを変更しうるが、system default deviceは変更しない。
2chは現行AudioEngine、16chは直接PortAudioとの比較で、製品engineの16ch対応とは区別する。
詳細とraw結果の所在は[決定0010](decisions/0010-blackhole-virtual-audio.md)と[進捗](status.md)を参照。

検証側では上の専用スクリプトから起動する。直接`main_gui.py`を起動すると、従来のユーザーデータ保存先が使われる。
将来のネイティブ版は、この参照版とも別のアプリ名・保存先・スキーマを使う。

## ネイティブ開発ツール

導入と確認は[nativeの準備手順](../native/README.md)を参照する。
`.tools/`にRustとCMake/Ninjaを置き、シェルの設定ファイルやOSの既定ツールを変更していない。
新しいシェルでは環境変数の設定が必要になる。
Qtプローブを実行するときは、その手順で開発SDKのframework/plugin/QMLパスも指定する。
Python参照起動のコマンドへQt開発SDKの環境変数を引き継がない。

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
