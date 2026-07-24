# Multilingual Translator Skill

## 概要

Multilingual Translator スキルは、プロジェクトの翻訳キーの整合性を保ち、翻訳漏れを自動検出・修正するために設計されています。
このスキルは `.agent/skills/multilingual_translator/SKILL.md` で定義された仕様に基づいており、プロジェクトレベルで利用可能になりました。

## 使用方法

```bash
/slash-command multilingual-translator [--check] [--fix] [--strict]
```

または、以下のコマンドを個別に実行：

```bash
# 1. 翻訳漏れを検出
python3 scripts/check_trn_keys.py

# 2. 翻訳キーを更新
python3 scripts/update_translations.py

# 3. 最終検証
python3 scripts/check_trn_keys.py
```

## 実装の場所

- **仕様書**: `.agent/skills/multilingual_translator/SKILL.md`
- **プロジェクト拡張**: `.github/extensions/` (このファイル)

## ワークフロー

### 1. 翻訳漏れの検証 (Check)

現在の翻訳状態を確認します。

```bash
python3 scripts/check_trn_keys.py
```

- **成功**: "TEST PASSED" と表示
- **警告/エラー**: 内容を確認して修正

### 2. 翻訳キーの追加・修正 (Fix Keys)

不足しているキーをすべての言語ファイルに一括追加します。

```bash
python3 scripts/update_translations.py
```

### 3. 未翻訳部分の翻訳 (Translate)

特に主要言語（`ja.json` など）の翻訳を確認・修正します。

### 4. ホワイトリスト設定（オプション）

英語と同一表記が正しいキー（例: `dB`, `Hz`, `None` など）をホワイトリストに登録：

- ファイル: `scripts/translation_whitelist.json`
- 除外方法:
  - **完全一致**: `exact_keys` リストに登録
  - **パターン**: `regex_patterns` に正規表現を定義

### 5. 最終検証 (Verify)

```bash
python3 scripts/check_trn_keys.py
```

## 言語ファイル

- 基本言語: `src/assets/lang/en.json`
- 日本語: `src/assets/lang/ja.json`
- その他言語: `src/assets/lang/*.json`

## 完了条件

"TEST PASSED" が表示され、警告（WARNING）が出ていない状態が目標です。
