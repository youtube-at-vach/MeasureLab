# CI Pre-checker Extension

PR前の検証手順は [CI Pre-checkerスキル](../../.agents/skills/ci-prechecker/SKILL.md) を参照してください。
環境構築とコマンドの詳細は [Tool Usage Guide](../../.agents/workflows/tool_usage.md) にまとめています。

このディレクトリの [拡張定義](ci-prechecker.extension.js) は、コマンドと検証ワークフローを定義しています。
利用できるコマンドは、使用するクライアントの拡張対応状況に依存します。
拡張を使用しない場合も、上記ガイドから検証を実行できます。

拡張定義は翻訳チェックに `python3` を指定しています。手動で検証するときはガイドに従って
`./.venv/bin/python` を使用し、CIと同じ厳格なチェックには `--strict` を指定してください。
