---
description: MeasureLabの環境構築、起動、開発ツールと検証コマンド
---

# Tool Usage Guide

共通ルールと作業別スキルの入口は [AGENTS.md](../../AGENTS.md) を参照してください。
以下はリポジトリのルートで実行するコマンドです。POSIXシェル（Linux・macOS）向けの表記です。

## 環境構築

Python 3.12以降を使用します。仮想環境がない場合は作成し、アプリと開発ツールの依存関係を導入します。
`requirements.txt` だけではRuff・Mypyなどが揃わないため、`dev` extrasもインストールします。

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -U pip
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m pip install -c constraints.txt -e '.[dev]'
```

以後はシステムの同名コマンドではなく、次の実行ファイルを使います。

| ツール | 実行ファイル |
| --- | --- |
| Python | `./.venv/bin/python` |
| Pytest | `./.venv/bin/pytest` |
| Ruff | `./.venv/bin/ruff` |
| Mypy | `./.venv/bin/mypy` |

Markdown lintにはNode.jsとnpmが必要です。OSの依存ライブラリなどは
[開発ガイド](../../docs/development.en.md)を参照してください。
`PyWavelets` のPythonでのimport名は `pywt` です。

## 起動とデバッグ

```bash
./.venv/bin/python main_gui.py
```

* Linuxのオーディオ環境では、必要に応じてJACK / PipeWireと `ConfigManager` の `pipewire_jack_resident` 設定を確認します。
* `MEASURELAB_DEBUG_WINDOWS=1` でウィンドウ挙動のログを出力します。
* `MEASURELAB_DEBUG_WINDOWS_TRACE=1` でウィンドウ出現時のスタックトレースを出力します。

## 開発中の検証

作業終了時には、変更の種類にかかわらず両方を実行します。

```bash
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
```

失敗した場合は今回の変更が原因か確認します。整形が必要なら変更したファイルだけを
`./.venv/bin/ruff format <変更したファイル>` で整形し、全体フォーマットは専用PRに分けます。

型チェック:

```bash
./.venv/bin/mypy src main_gui.py
```

Markdown変更時:

```bash
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

### 翻訳キー

CIと同じ厳格な検査を使います。重複キーなど終了コードに反映されない警告も確認してください。

```bash
./.venv/bin/python scripts/check_trn_keys.py --strict
```

修正方法は [翻訳スキル](../skills/multilingual-translator/SKILL.md)を参照してください。

### テスト

最小スモークテスト:

```bash
./.venv/bin/python -m pytest -q tests/logic_verification/core/test_config_manager.py tests/logic_verification/core/test_utils.py
```

メインウィンドウ周辺のテスト:

```bash
./.venv/bin/python -m pytest -q tests/logic_verification/gui/test_main_window_activity.py
```

全体テスト:

```bash
./.venv/bin/pytest -q
```

移行ブランチではRust候補の実行テストも含まれます。固定ツールチェーンを用意し、初回は
`native/`で `cargo fetch --locked` を実行してください。候補runnerは取得済みの依存を使って
`--offline --locked` でビルドします。
PythonのみのCIとRust候補のCIは次の範囲に分けます。両方の成功を全体の合格条件とします。

```bash
./.venv/bin/pytest -q -m "not native"
./.venv/bin/pytest -q -m native tests/logic_verification/test_migration_*candidate.py tests/logic_verification/test_migration_audio_graph.py tests/logic_verification/test_migration_audio_route.py
```

`native` はRust実行ファイルを使うテストのmarkerです。Pythonだけで完結する参照・破損検出の
テストは通常CIに残します。別OSの保存fixture比較にはrunnerの `--portable` を使い、元の
fixture・source hash・許容差は変更しません。固定環境の再現検証では従来どおり指定を省略します。

#### Native evaluation の手動実行

リモートの `Native evaluation` は、開発中の push・PR 作成・PR 更新では自動実行しません。
通常の Python CI は従来どおり実行します。
MIG-008までの検証範囲は[評価計画](../../guide/RUST_QML_MIGRATION_PLAN.md)に従い、
対象変更のテストと代表フローを優先します。Windows・ARMと長時間試験は実行しません。
Native CIは対象変更の確認に必要な場合に明示的に実行してください。
自動実行を省略していても、未実施の Native 検証を合格扱いにはしません。

* PR では `run-native-evaluation` ラベルを付けると`probe-core`・`audio-backend`・`qt-boundary`を実行します。
    ラベルを残したまま push しても再実行しません。最新コミットを再検証するには、
    ラベルを外して付け直してください。他のラベルでは検証ジョブを実行しません。
* ワークフローが既定ブランチに存在する場合は、GitHub の Actions → Native evaluation →
    Run workflow で対象ブランチと `suite` を選べます。`all` は上の3ジョブ、
    `probe-core`・`audio-backend`・`qt-boundary` は指定ジョブだけを実行します。
    延期した描画試作は`renderer-spike`を個別指定した場合だけ実行します。
    既定ブランチへの統合前は PR ラベルによる実行を使ってください。

CLI での手動実行例（`--ref` を検証対象のブランチに置き換えます）:

```bash
gh workflow run native-evaluation.yml --ref codex/next-core-evaluation -f suite=all
gh workflow run native-evaluation.yml --ref codex/next-core-evaluation -f suite=qt-boundary
```

同じブランチで明示的に再実行すると、先に動いていた Native evaluation をキャンセルします。
ジョブの上限は `probe-core` が30分、`audio-backend`・`renderer-spike` が15分、
`qt-boundary` が60分です。QML 検証は代表2ch条件とし、ステップは10分で打ち切ります。
上限で終了した検証は失敗として調査し、合格扱いにはしません。

ハードウェアテストは通常スキップされます。対応機器を使用して明示的に検証する場合だけ
`--hardware` を指定してください。このオプションではハードウェア以外のテストがスキップされるため、全体テストの代わりにはなりません。

### UIサイズ検証

レイアウト・翻訳の変更時、新規モジュールのリリース前、CI相当の最終確認では全言語を検証します。
サイズ上限と超過時の対処は [AGENTS.md](../../AGENTS.md#uiサイズの上限) を参照してください。
QApplicationやC拡張の競合を避けるため、Pytestとは独立して実行します。

```bash
./.venv/bin/python scripts/check_ui_size_limits.py
```

成功時は `Verification Passed!` と終了コード `0`、超過時は対象モジュールの詳細と終了コード `1` を返します。
実装中に英語だけを確認する場合は次を使えますが、最終確認は引数なしで実行してください。

```bash
./.venv/bin/python scripts/check_ui_size_limits.py --quick
```

## PR前の検証

次の順で実行し、各段階の終了コードと結果を確認します。コマンドは上記の各節を正本とします。

1. [開発中の検証](#開発中の検証)の Ruff lint と Ruff format。
2. 同節の Mypy。
3. [翻訳キー](#翻訳キー)の厳格な検査。
4. [開発中の検証](#開発中の検証)の Markdown lint。
5. [テスト](#テスト)の全体テスト。
6. [UIサイズ検証](#uiサイズ検証)の全言語検証。Pytest とは別プロセスで実行。

GUI を表示できない環境では `QT_QPA_PLATFORM=offscreen` を設定します。CI の環境変数と
実行条件は [.github/workflows/ci.yml](../../.github/workflows/ci.yml) で確認してください。
CI は変更パスによりジョブを省略しますが、ローカルで CI 相当の最終確認を依頼された場合は全項目を実行します。

失敗時の修正範囲と再実行の判断は [CI Pre-checker](../skills/ci-prechecker/SKILL.md)、
PR の作成条件は [AGENTS.md](../../AGENTS.md#pull-request) に従います。
