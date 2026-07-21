---
name: multilingual-translator
description: >
  Detect missing translation keys, fix untranslated placeholders, and update
  multilingual language files (src/assets/lang/*.json). Use when the user asks
  for 多言語翻訳, translation updates, i18n, tr() keys, missing translations,
  localization, 翻訳漏れ, or runs /multilingual-translator.
metadata:
  short-description: "Detect and fix translation key gaps"
---

# Multilingual Translator

MeasureLab の翻訳キー整合性を保ち、翻訳漏れを検知・修正する。

## 前提

- 作業ディレクトリはリポジトリルート（`MeasureLab/`）
- Python は `./.venv/bin/python` を使う
- 言語ファイル: `src/assets/lang/*.json`（`en.json` がソース・オブ・トゥルース）
- GUI 文字列は `tr("key")` で囲む

## 手順

### 1. 翻訳漏れの検証 (Check)

```bash
./.venv/bin/python scripts/check_trn_keys.py
```

この検証はキー欠落に加え、**英語の値のまま放置されている未翻訳プレースホルダー**も検出する（Check 5）。

| 結果 | 対応 |
|------|------|
| `TEST PASSED` かつ WARNING なし | 完了。終了する |
| WARNING または FAIL | 内容を確認し、次のステップへ |

CI 相当の厳格チェックが必要な場合:

```bash
./.venv/bin/python scripts/check_trn_keys.py --strict
```

### 2. 翻訳キーの追加・修正 (Fix Keys)

#### A. `en.json` にキーがない

コード内の `tr()` にあり `src/assets/lang/en.json` にない場合:

1. `src/assets/lang/en.json` にキーを追加する（英語では通常 Key = Value）
2. または不足キーを埋めるため次を実行する:

```bash
./.venv/bin/python scripts/update_translations.py
```

`update_translations.py` は `src/` と `main_gui.py` の `tr()` を走査し、`en.json` と他言語ファイルを同期する。

#### B. 他言語ファイルにキーがない

`en.json` にはあるが `ja.json` 等にない場合も同じ:

```bash
./.venv/bin/python scripts/update_translations.py
```

**注意**: 不足キーには **英語の値をプレースホルダーとして** 入れる。その後 Step 3 で翻訳する。

### 3. 未翻訳部分の翻訳 (Translate)

プレースホルダー（英語のままの値）を各言語に翻訳する。

- 主要言語（特に `ja.json`）は UI 文脈に合わせて訳す
- 単位・記号・専門略語で英語のままで正しいものはホワイトリストへ

#### ホワイトリスト（英語同一で妥当なキー）

パス: `scripts/translation_whitelist.json`

| 方式 | フィールド | 例 |
|------|------------|-----|
| 完全一致 | `exact_keys` | `None`, `IDLE`, `dB`, `Hz` |
| 正規表現 | `regex_patterns` | 数値+単位の組み合わせ |

### 4. 最終検証 (Verify)

```bash
./.venv/bin/python scripts/check_trn_keys.py
```

`TEST PASSED` かつ WARNING なしになるまで修正を繰り返す。

### 5. 完了

検証が通ったらタスク終了。変更をコミットする場合はユーザーに確認してから行う。

## 関連ファイル

| パス | 役割 |
|------|------|
| `src/assets/lang/en.json` | 英語（ソース・オブ・トゥルース） |
| `src/assets/lang/{ja,de,es,fr,ko,pt,ru,zh}.json` | 各言語 |
| `scripts/check_trn_keys.py` | キー整合・プレースホルダー検査 |
| `scripts/update_translations.py` | 不足キーの一括追加 |
| `scripts/translation_whitelist.json` | 英語同一で可の除外リスト |
| `scripts/translation_utils.py` | 共通ユーティリティ |
| `scripts/check_trn_keys.py` のキー整合チェック | CI でも利用 |

## 注意

- 翻訳ファイル以外のリファクタや機能変更はしない
- プレースホルダーを英語のまま残さない（ホワイトリスト対象を除く）
- `update_translations.py` は未使用キーを `en.json` から削除することがある。出力を確認してから進める
