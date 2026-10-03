# MIG-008の参照環境

更新: 2026-10-04。再開は[進捗](status.md)と[native手順](../native/README.md#このworktreeで使う)を使う。
Windows・ARMの準備/検証はMIG-008後。別環境構築と過去のスモーク再実行を先行条件にしない。

## 導入済み環境

| 項目 | 現在の評価環境 |
| --- | --- |
| OS / CPU | macOS 14.8.9、Intel x86_64 |
| Python | 3.12.14（MacPorts）、worktree専用`.venv/` |
| Python依存 | `constraints.txt` + `.[dev]`、PyQt6 6.11.0 / Qt runtime 6.11.2 |
| Rust / Cargo | 1.98.1、`.tools/cargo/`と`.tools/rustup/` |
| C++ / build | Apple Clang 16.0.0。試作用CMake/Ninjaのbuild用venvは方針決定後に削除 |
| Qt SDK・接続試作 | MIG-008ではQt SDK 6.11.2、CXX-Qt 0.10.0 / Qt Bridge 0.3.0を使用。方針決定後にSDK・両adapterを削除 |
| 音声 | BlackHole 2ch / 16ch。MIG-008主経路は2ch、48 kHz / 256 frames / f32 |

Rust toolchain・依存cacheと現行GUIの`.venv/`は保持する。
Qt SDK・build用venvとQt依存を含む旧build cacheを削除し、検証に必要なcoreだけを再buildする。
評価結果と削除対象の未コミット差分の保存先は[進捗](status.md#方針決定後の整理)。

## Python参照版の起動

Qt開発SDKの環境変数を設定していない別processで、リポジトリルートから起動する。

```bash
./.venv/bin/python scripts/migration_reference.py
```

設定・校正・ログは`.migration-local/reference/`、wisdomはその`data/MeasureLab/wisdom/`へ分離する。
参照版は最初にofflineで起動する。比較に必要な音声設定はGUIで明示し、一方ずつ測定する。
直接`main_gui.py`を起動すると従来のユーザーデータ保存先を使うため、参照runnerを利用する。
過去の分離設定は今回のアーティファクト整理で削除した。起動時に再生成される。

参照の固定fixture/係数/許容差はGit管理の[fixture](fixtures/README.md)を使う。
保存済み期待値がある試験では毎回の再生成をしない。
GUIを表示できない対象テストだけ`QT_QPA_PLATFORM=offscreen`を使う。
