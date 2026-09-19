---
name: release-manager
description: MeasureLab のリリース用に変更履歴・文書・バージョンを更新し、検証済みの準備 PR を作る。タグ付けや公開は含まない。
---

# リリースを準備

## 対象を決める

リリース予定のバージョンと基点タグを確認する。バージョン指定がなければ質問し、その間に履歴・文書を調査する。`git describe --tags --abbrev=0` は現在の HEAD から到達できるタグなので、対象リリースの基点と一致するか確認する。タグがなければ比較範囲を明示する。

`codex/release-v<version>` ブランチで作業する。ユーザー指定のブランチ名があればそれを優先する。

## 更新する

* 基点から HEAD までのコミットと実装差分を確認し、未記載の変更を `CHANGELOG.md` に既存形式で記載する。
* 変更した機能に対応する `docs/` の日英文書を更新する。画面が変わり画像更新が必要な場合は、`scripts/capture_widget_screenshots.py` の使い方を確認して対象を更新する。
* `pyproject.toml` の `project.version`、`src/core/version.py` の `__version__`、`version.json` の `version` を同じ値に更新する。

履歴にない機能や、実行していない検証を変更履歴へ記載しない。

## 検証して PR を作る

[CI Pre-checker](../ci-prechecker/SKILL.md)を実行し、3か所のバージョン一致と `git diff --check` を確認する。対象変更だけをコミット・push し、既存の準備 PR を更新するか、`Release v<version>` の PR を作成する。

PR 本文に主な変更、バージョン、検証結果、未確認事項を記載する。[Agent Guide](../../../AGENTS.md#pull-request)に従って Draft 状態を確認する。タグ push はリリースワークフローを起動するため、この準備フローでは行わない。マージ・タグ付け・公開は別の依頼として扱う。

## 完了

バージョン、比較したタグ、PR URL、検証結果と未確認事項を報告する。リモートのビルドやマージ可否を確認していない場合、確認済みとも今後監視するとも報告しない。
