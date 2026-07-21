---
name: documentation-reflector
description: >
  Reflect recent implementation and spec changes into project docs (Markdown
  under docs/). Use when the user asks to update documentation, sync docs with
  code, ドキュメント反映, widget docs, or runs /documentation-reflector.
metadata:
  short-description: "Sync docs/ with recent code changes"
---

# Documentation Reflector

実装・仕様変更を `docs/` 配下の説明書に正確に反映する。

## 手順

### 1. 変更の確認 (Identify Changes)

最近の実装や仕様変更を把握する。

- **Git log**: 直近コミットを確認。ウィジェットの新機能・挙動変更を優先
  - 例: `git log --oneline --since="1 week ago"`
  - 例: `git log --grep="feat" --since="1 week ago"`
- **ユーザー指定**: 特定ウィジェットの指示がある場合、そのソースと関連 diff を確認

### 2. 対象ドキュメントの特定 (Locate Docs)

| 種類 | パス |
|------|------|
| ウィジェット説明書 | `docs/widgets/[widget].md` と `[widget].en.md` |
| ウィジェット一覧 | `docs/widget_guide.md` / `widget_guide.en.md` |
| トップ | `docs/index.md` / `index.en.md` |
| その他 | `docs/quickstart*.md`, `docs/calibration*.md` など関連があれば更新 |

### 3. ドキュメントの更新 (Update Docs)

- **必須**: ユーザー向けの操作・UI・仕様変更は `docs/widgets/*.md`（日英）に反映
- **省略可**: 内部リファクタなどユーザーに見えない変更
- 新規ウィジェットなら一覧・index への追記も行う
- 既存の文体・見出し構造に合わせる

### 4. リンティング

```bash
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

エラーがあれば修正する。

### 5. 完了

更新ファイル一覧と要点をユーザーに報告して終了。コミットはユーザー確認後のみ。

## 注意

- 日英ペアがある場合は両方を更新する
- ドキュメント専用変更に留め、無関係なコード修正はしない
