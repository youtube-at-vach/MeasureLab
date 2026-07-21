---
name: release-manager
description: >
  Prepare a release: update CHANGELOG, bump version files, lint, optional
  screenshots, and open a release PR. Use when the user asks for a release,
  リリース準備, version bump, or runs /release-manager.
metadata:
  short-description: "CHANGELOG, version bump, release PR"
---

# Release Manager

新しいバージョンのリリース準備を行う。

## 手順

### 1. CHANGELOG の更新

1. 最新リリースタグ:

```bash
git describe --tags --abbrev=0
```

2. タグから HEAD までの差分:

```bash
git log "$(git describe --tags --abbrev=0)"..HEAD --oneline
```

3. `CHANGELOG.md` に未記載の変更があれば追記（既存フォーマットに合わせる）

### 2. ドキュメント記述漏れチェック

- 最新タグ以降の変更が `docs/`（特に `docs/widgets/*.md`）に反映されているか確認
- 未反映のユーザー向け変更があれば追記
- 必要なら `documentation-reflector` スキルの手順を使う

### 3. バージョン更新

1. **ユーザーにリリース予定バージョンを確認**（未指定なら必ず聞く）
2. 次を同じバージョンに更新する:
   - `pyproject.toml` の `version`
   - `src/core/version.py` の `__version__`
   - ルートの `version.json` の `version`

### 4. リンティング

```bash
./.venv/bin/ruff check --fix .
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

エラーがあれば修正する。

### 5. ドキュメント用スクリーンショット（任意）

大きな UI 変更がある場合のみ:

```bash
./.venv/bin/python scripts/capture_widget_screenshots.py
```

GUI スレッドのクリーンアップで落ちることがある。その場合は対象を絞って再実行する。

### 6. リリース準備 PR の作成

**ブランチ作成・コミット・プッシュ・PR 作成の前にユーザー確認を取る。**

1. ブランチ: `release/v[version]`
2. 変更をコミット
3. プッシュ後に PR 作成
   - タイトル: `Release v[version]`
   - 本文: リリース準備内容の要約（CHANGELOG 要点）

```bash
gh pr create --title "Release v[version]" --base main --body "$(cat <<'EOF'
## Release preparation
- version bump to [version]
- CHANGELOG update
- ...

EOF
)"
```

### 7. 完了

ユーザーに報告する内容:

- 更新したファイル一覧
- PR URL
- 「GitHub で PR が main にマージ可能か、ビルドが通るかを確認してください」

## 注意

- バージョン番号はユーザー確認なしに決め打ちしない
- タグ付け・GitHub Release 作成はこのスキルの範囲外（マージ後の作業）
