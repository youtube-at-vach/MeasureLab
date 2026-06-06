---
name: PR Submitter
description: 作業完了後に検証を行い、Pull Request (PR) を作成・送付する一連の流れを定義したスキル
---

# PR Submitter Skill

このスキルは、実装作業が完了した後に、ローカルでの厳格な検証（各種Lint、型チェック、翻訳キー、サイズ制限、ユニットテスト）を実行し、リモートリポジトリへプッシュしてPull Request (PR) を作成するまでのプロトコルを定めたものです。

このスキルを使用することで、CIの失敗を未然に防ぎ、適切なコマンド実行許可を得た上で安全にPRを送付できます。

## ワークフロー

### 1. 最新の main ブランチの同期

開発中のブランチに最新の main ブランチの変更を取り込み、コンフリクトがないことを確認します。

```bash
git fetch origin main
git merge origin/main
```

### 2. ローカルでの品質検証 (CI Pre-check)

リモートのCI基盤に送る前に、ローカルで以下のコマンドを順番に実行し、すべてが正常にパスすることを確認してください。
各開発用ツールは仮想環境のもの（`.venv/bin/` 以下）を使用します。詳細は [.agent/workflows/tool_usage.md](file:///Users/vach/MeasureLab/.agent/workflows/tool_usage.md) を参照してください。

#### ① コードのリンティング・フォーマット確認 (Ruff)

```bash
.venv/bin/ruff check .
```

警告やエラーが検出された場合は、自動修正を行ってください。

```bash
.venv/bin/ruff check --fix .
```

#### ② 静的型チェック (Mypy)

```bash
.venv/bin/mypy src main_gui.py
```

#### ③ 翻訳キーの整合性チェック

多言語対応の翻訳キー（`src/assets/lang/*.json`）に不足や重複、未翻訳箇所がないかを確認します。

```bash
.venv/bin/python3 scripts/check_trn_keys.py
```

#### ④ UIサイズ制限の検証

低解像度ディスプレイやノートPCでのUIはみ出しを防ぐため、MainWindowおよび各ウィジェットの最小サイズ上限（MainWindowは 1290x740 px、各モジュールコンテンツは 1070x690 px）に収まっているかを確認します。

```bash
.venv/bin/python scripts/check_ui_size_limits.py
```

#### ⑤ ドキュメントのリンティング (Markdown lint)

プロジェクト内の全Markdownファイルのスタイルと整合性をチェックします。

```bash
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

#### ⑥ ユニットテストの実行 (Pytest)

```bash
.venv/bin/pytest
```

---

### 3. コミットとプッシュ

すべての検証をパスしたら、変更内容をコミットし、リモートリポジトリにプッシュします。

1. 差分をステージングします。

   ```bash
   git add .
   ```

2. コミットメッセージには、変更の目的と内容を明確に記述します。

   ```bash
   git commit -m "feat/fix: [概要]"
   ```

3. ブランチをリモートにプッシュします。

   ```bash
   git push origin [ブランチ名]
   ```

---

### 4. Pull Request の作成

GitHub API または MCP ツール、あるいは GitHub CLI を用いてPull Requestを作成します。

#### GitHub MCP ツールを使用する場合

- ツール: `mcp_github-mcp-server_create_pull_request` を呼び出します。
- 引数:
    - `title`: `[PRの簡潔なタイトル]`
    - `body`: 変更内容の概要、テストした内容、関連するIssue番号（`Closes #123` など）を含めます。
    - `head`: `[開発ブランチ名]`
    - `base`: `main`

#### GitHub CLI (`gh`) コマンドを使用する場合

```bash
gh pr create --title "[PRの簡潔なタイトル]" --body "[PRの詳細な説明。関連Issue: Closes #Issue番号]" --base main --head [開発ブランチ名]
```

---

### 5. 完了報告

PRの作成が完了したら、生成されたPRのURLをユーザーに報告し、検証結果（すべてのチェックがパスしたこと）を伝えてください。
これでPR送付プロセスは完了です。
