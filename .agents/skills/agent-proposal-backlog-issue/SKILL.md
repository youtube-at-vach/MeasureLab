---
name: agent-proposal-backlog-issue
description: MeasureLab の設計指針とプロポーサルを比較し、次に実装する候補を GitHub Issue 化して Project の Backlog に登録するときに使用します。コード実装や既存 Issue の一般的な整理には使用しません。
---

# エージェント：プロポーサル Backlog Issue 化

MeasureLab の「次に実装するもの」を、測定器設計の原則と既存実装の事実に基づいて選定し、重複のない GitHub Issue として Project の Backlog に登録するためのプロトタイプです。

## 適用範囲

- ユーザーが、プロポーサルから次の実装候補を選び、Backlog に Issue 化するよう依頼した場合に使用する。
- 「次に実装するもの」は、個数の指定がなければ 1 件に絞る。複数件を求められた場合だけ指定数を選ぶ。
- Issue 作成と Project 更新は外部状態を変更するため、ユーザーの依頼がある場合だけ実行する。候補選定だけの依頼では Issue を作成しない。
- コードの実装、PR 作成、プロポーサル文書自体の改訂、既存 Issue の実装計画変更はこのスキルの範囲外とする。

## 選定前の読み取り

リポジトリのルートを確認し、次の資料を読む。

1. `guide/MEASUREMENT_INSTRUMENT_DESIGN_GUIDELINES.md` は省略せず全文を読む。
2. `guide/PROPOSED_FEATURES.md` の Overview、Status Legend、Selected Additions、Implemented/Covered、Conditional、On hold の各区分を読む。
3. `guide/CURRENT_DIRECTION.md`、対象ウィジェットのコード・テスト・ドキュメントが存在する場合は、提案がすでに実装済みでないか確認する。
4. `git status --short --branch` を読み取り、作業ツリーを変更しない。

GitHub の現状も、次の最小確認で読み取る。認証・スコープの確認は省略してよい。

- `gh repo view --json nameWithOwner,owner,url` で対象リポジトリを確定する。
- `gh project list --owner <owner> --format json` で対象 Project を確認する。MeasureLab では通常 `Agents: MeasureLab` を優先するが、存在を再確認してから使う。
- `gh project item-list <number> --owner <owner> --format json` と Issue 検索で、同じ提案や同じ目的の Issue が既にないか調べる。

### Blocked の提案を候補から除外する

- Project の項目一覧から `Status: Blocked` の Issue を抽出し、Issue のタイトル・本文と `guide/PROPOSED_FEATURES.md` の提案名、対象ウィジェット、目的を照合する。
- Blocked の Project 項目が代表しているプロポーサルは、未完了であっても現在の候補集合から除外する。Blocked であることを理由に、同じプロポーサルを再 Issue 化したり、重複する代替 Issue を作成したりしない。
- Blocked 項目がプロポーサル由来か判断できない場合は、Issue の目的と提案の対応を追加確認し、対応を確定できるまでその提案を候補から外す。
- 候補選定の記録には、除外したプロポーサル、対応する Issue、Project Status が `Blocked` であることを明記する。Blocked ではない既存 Issue も、従来どおり同じ提案・目的の重複確認で除外する。

## 選定基準

候補を次の順で比較する。

1. Measurement Integrity、過負荷・クリッピング・データ欠落の検知、測定値の妥当性表示など、誤測定防止に直結するか。
2. 44.1/48 kHz を含む一般的なオーディオ環境で意味のある測定結果になるか。
3. 既存機能の「Partially implemented」を完成させ、複数ウィジェットや共通測定基盤へ再利用できるか。
4. 測定条件の可視性、決定論的な状態遷移、校正状態、再現性、停止後の異常履歴を改善するか。
5. 自動テスト、GUI テスト、翻訳キー検査、UI サイズ検証で完了条件を機械的に定義できるか。
6. 現在のロードマップや既存 Project 項目と競合せず、実装範囲を 1 Issue に分解できるか。

`Implemented`、`Covered`、`On hold`、`Not suitable` の提案は原則選ばない。`Conditional` は必要な fixture・基準経路・用途が Issue 内で明確になる場合だけ選ぶ。機能追加の魅力だけで判断せず、測定結果の信頼性と実装可能性を優先する。

Blocked の既存 Issue が代表する提案は、上記の除外規則を優先し、実装の優先度や安全性が高く見えても選ばない。残りの候補から、既存 Issue と目的が重複しないものを比較する。

## Issue の作成内容

タイトルは、既存の MeasureLab の慣例に合わせて簡潔な英語の `[Feature] ...` とする。本文は日本語またはプロジェクトで通用する言語で、少なくとも次を含める。

- `背景`: 現状の実装と不足している測定上の問題。
- `選定理由`: 設計指針のどの原則と `guide/PROPOSED_FEATURES.md` のどの提案に基づくか。他候補より先にする理由。
- `実装範囲`: 対象モジュール、データモデル、UI、エクスポート、異常時の挙動。
- `完了条件`: 正常系、失敗系、停止後の状態、リセット、回帰テスト、翻訳、UI サイズを含む検証可能な条件。
- `参照`: 設計指針、プロポーサル、対象コード、関連テストへのパスまたは URL。

GUI の表示文字列を含む候補では、`tr()` による翻訳管理、全言語のキー整合、長い翻訳でのレイアウト検証を完了条件に入れる。測定系の候補では、コールバックのリアルタイム性、有限値、安全なクリッピング、異常履歴のラッチとリセットを明記する。

## GitHub への登録手順

書き込み直前に、既存 Issue の重複と対象 Project を再確認する。認証・スコープの確認は必要な場合だけ行う。

1. 既存 Issue のタイトル・目的が重複していないことを確認する。
2. Project 項目を再取得し、選定した提案が Blocked Issue の代表する提案に含まれていないことを確認する。確認できない場合は Issue 作成を止める。
3. `gh issue create --repo <owner>/<repo> --title ... --body ... --label enhancement` で Issue を作成する。Project の `--project` オプションに依存せず、Issue 作成と Project 追加を分離して検証する。
4. 作成結果の Issue URL を使い、`gh project item-add <number> --owner <owner> --url <issue-url> --format json` で Project に追加する。
5. `gh project field-list <number> --owner <owner> --format json` で Status フィールドと `Backlog` オプションの ID を取得し、`gh project item-edit` で Status を Backlog に設定する。ID はプロジェクトごとに取得し、固定値を使い回さない。
6. Priority フィールドがあり、候補が測定基盤・安全性に関わる最優先候補である場合は `P1` を設定してよい。ユーザーが優先度を指定した場合はそれを優先する。
7. `gh project item-list ... --jq` と `gh issue view ... --json` で、Issue URL、Project 名、Status、必要な Priority、ラベルを再確認する。

Issue 作成後に Project 追加だけが失敗した場合は、同じタイトルで再作成しない。作成済み Issue の URL を報告し、権限不足が原因なら必要に応じて `gh auth refresh -s project` を案内したうえで、Project 追加を再開する。

## 完了報告

選定した候補、選定理由の要点、Issue URL、Project 名、Status、Priority、ラベルを簡潔に報告する。Issue 作成は成功したが Backlog 登録に失敗した場合は、未完了であることを明示し、Issue が重複して作成されない再開手順を示す。
