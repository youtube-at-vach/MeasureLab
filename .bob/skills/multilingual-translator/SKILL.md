---
name: multilingual-translator
description: Use when the user wants to add, fix, or verify translation keys in the multilingual language files (src/assets/lang/*.json) — detects missing keys, placeholder leaks, and updates all language files.
---

# Multilingual Translator Skill

このスキルは、プロジェクトの翻訳キーの整合性を保ち、翻訳漏れを修正するための手順を自動化します。

## 概要

`scripts/check_trn_keys.py` を使用して翻訳漏れを検出し、`scripts/update_translations.py` を使用して言語ファイルを更新します。

## 手順

### 1. 翻訳漏れの検証 (Check)

`execute_command` で以下を実行してください。

```bash
./.venv/bin/python scripts/check_trn_keys.py
```

- **"TEST PASSED"** かつ警告（WARNING）もゼロ → タスク完了です。終了してください。
- 警告（WARNING）またはエラー（FAIL）が出ている場合 → 内容を確認して次のステップへ進みます。

> CIなど厳格な環境でプレースホルダーをエラーとして扱いたい場合は `--strict` を追加してください。

### 2. 翻訳キーの追加・修正 (Fix Keys)

#### A. `en.json` にキーがない場合

コード中で `tr()` で参照されているが `src/assets/lang/en.json` に定義されていないキーがある場合：

1. `read_file` で `src/assets/lang/en.json` を開き、対象キーを追加します（Key = Value で英語値を設定）。

#### B. 他言語ファイルにキーがない場合

`en.json` にはあるが他言語ファイルに不足しているキーがある場合：

1. `execute_command` で以下を実行して一括追加します。

```bash
./.venv/bin/python scripts/update_translations.py
```

> **注意**: このスクリプトは不足キーに対して**英語の値をプレースホルダー**として追加します。

### 3. 未翻訳部分の翻訳 (Translate)

`update_translations.py` で追加されたキーについて、各言語ファイルを `apply_diff` または `search_and_replace` で更新し、適切な翻訳を行ってください。

- `ja.json` などの主要言語は文脈に合わせた翻訳が必要です。

#### ホワイトリストによる除外

単位・記号・略語（例: `dB`, `Hz`, `IDLE`, `None`）のように英語と同一のままで正しいキーは、チェックスクリプトの警告から除外できます。

- **ホワイトリストファイル**: `scripts/translation_whitelist.json`
    - `exact_keys` — 完全一致で除外するキー（英語の値）を列挙
    - `regex_patterns` — 正規表現パターンで除外（数値＋単位の組み合わせなど）

### 4. 最終検証 (Verify)

すべての修正が終わったら再度実行します。

```bash
./.venv/bin/python scripts/check_trn_keys.py
```

すべて PASS するまで手順 2〜3 を繰り返してください。

### 5. 完了

"TEST PASSED" を確認したらタスク終了です。
