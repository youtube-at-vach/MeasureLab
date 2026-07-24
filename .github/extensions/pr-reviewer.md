# PR Reviewer Skill

## 概要

PR Reviewer スキルは、GitHub Pull Request のコード審査を自動化するために設計されています。
このスキルは `.agent/skills/pr_reviewer/SKILL.md` で定義された仕様に基づいており、プロジェクトレベルで利用可能になりました。

## 使用方法

```bash
/slash-command pr-reviewer --pr <PR_NUMBER>
```

または、GitHub MCP を通じてプログラム的に実行することもできます。

## 実装の場所

- **仕様書**: `.agent/skills/pr_reviewer/SKILL.md`
- **プロジェクト拡張**: `.github/extensions/` (このファイル)

## チェックリスト

実行時の確認項目：

- [ ] リポジトリ情報の取得
- [ ] PR情報の取得
- [ ] 変更ファイルの確認
- [ ] Diffの取得と分析
- [ ] コードレビューの実施
    - [ ] ロジックの正確性
    - [ ] スタイルと品質
    - [ ] テストとドキュメント
    - [ ] CI/安全性
- [ ] レビュー結果の投稿

## 注意

- **自身のPRの場合**: `APPROVE` ではなく `COMMENT` で投稿されます
- **テスト検証**: CIが全て通過していることを確認してから投稿します
