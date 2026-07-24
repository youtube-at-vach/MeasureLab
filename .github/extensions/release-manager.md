# Release Manager Skill

## 概要

Release Manager スキルは、プロジェクトの新しいバージョンリリースのための準備作業を自動化するために設計されています。
このスキルは `.agent/skills/release_manager/SKILL.md` で定義された仕様に基づいており、プロジェクトレベルで利用可能になりました。

## 使用方法

```bash
/slash-command release-manager [--version <VERSION>]
```

## 実装の場所

- **仕様書**: `.agent/skills/release_manager/SKILL.md`
- **プロジェクト拡張**: `.github/extensions/` (このファイル)

## リリース準備のワークフロー

このスキルは以下のタスクを順番に実行します：

1. **CHANGELOG更新** — 最新のコミットをCHANGELOG.mdに反映
2. **ドキュメント確認** — docs/ 以下に新機能が記載されているか検証
3. **バージョン更新** — pyproject.toml, src/core/version.py, version.json を更新
4. **リンティング** — Ruff, Markdownlint でコードとドキュメントをチェック
5. **スクリーンショット更新** — UI変更時に必要に応じてドキュメント画像を更新
6. **リリースPR作成** — release/v[VERSION] ブランチでPRを作成

## 対象ファイル

- `CHANGELOG.md` — リリースノート
- `pyproject.toml` — プロジェクト設定
- `src/core/version.py` — バージョン定義
- `version.json` — バージョン情報
- `docs/` — ドキュメント一式

## 実行例

```bash
/slash-command release-manager --version 1.5.0
```

バージョンが指定されない場合は、ユーザーに確認を取ります。
