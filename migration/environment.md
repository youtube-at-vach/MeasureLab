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
| C++ / build | Apple Clang 16.0.0、CMake 4.4.3 / Ninja 1.13.2、`.tools/build-venv/` |
| Qt SDK | 6.11.2、`.tools/qt/6.11.2/macos/`。PyQt runtimeとは分離 |
| Qt接続 | CXX-Qt 0.10.0 / Qt Bridge 0.3.0、Cargo.lockで固定 |
| 音声 | BlackHole 2ch / 16ch。MIG-008主経路は2ch、48 kHz / 256 frames / f32 |

SDK・toolchain・依存cacheと主workspaceのbuild cacheは保持する。
再生成できるHello world、SDK download archive、独立rendererのbuild、中間試験・配布コピーは削除した。

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
