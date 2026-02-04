---
name: Multilingual Translator
description: 翻訳漏れの検知、修正、および多言語ファイルの更新を行うスキル
---

# Multilingual Translator Skill

このスキルは、プロジェクトの翻訳キーの整合性を保ち、翻訳漏れを修正するための手順を自動化します。

## 概要

`scripts/check_trn_keys.py` を使用して翻訳漏れを検出し、`scripts/update_translations.py` を使用して言語ファイルを更新します。

## 手順

以下の手順に従って翻訳タスクを実行してください。

### 1. 翻訳漏れの検証 (Check)

まず、現在の翻訳状態を確認します。

```bash
python3 scripts/check_trn_keys.py
```

* **Result**: "TEST PASSED" と表示された場合、タスクは完了です。終了してください。
* **Result**: "TEST FAILED" の場合、エラー内容を確認し、次のステップへ進みます。

### 2. 翻訳キーの追加・修正 (Fix Keys)

翻訳漏れ（Missing keys）が見つかった場合、以下のように修正します。

#### A. 英語（en.json）にキーがない場合

コード内で使用されているが `en.json` に定義されていないキーがある場合：

1. `scripts/en.json` を開き、対象のキーを追加します。
    * 通常、英語では Key = Value とします。
2. または、`scripts/update_translations.py` の `MISSING_EN_KEYS` リストに対象キーを記述し、スクリプトを実行することも可能です。

#### B. 他言語ファイルにキーがない場合

`en.json` にはあるが、他の言語ファイル（ja.jsonなど）にないキーがある場合：

1. 以下のスクリプトを実行して、すべての言語ファイルに不足しているキーを一括追加します。

    ```bash
    python3 scripts/update_translations.py
    ```

    * **注意**: このスクリプトは、不足しているキーに対して **英語の値をプレースホルダーとして** 追加します。

### 3. 未翻訳部分の翻訳 (Translate)

`update_translations.py` で追加されたキー、または手動で追加したキーについて、適切な翻訳を行ってください。

* 特に `ja.json` などの主要言語については、文脈に合わせた翻訳を行ってください。
* 自動追加された場合、値が英語のままになっている箇所を修正する必要があります。

### 4. 最終検証 (Verify)

すべての修正が終わったら、再度検証スクリプトを実行します。

```bash
python3 scripts/check_trn_keys.py
```

* 全てがPASSするまで修正を繰り返してください。

### 5. 完了

"TEST PASSED" を確認したらタスク終了です。
