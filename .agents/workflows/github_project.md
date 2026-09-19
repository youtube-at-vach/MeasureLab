# GitHub Issue・Project 共通手順

Issue 登録・計画・実装スキルから必要な場面で読む。依頼されたフローの範囲で書き込みを行い、調査だけの依頼では読み取りに留める。承認済みの操作に追加確認を挟まない。

## 対象と現状

* `gh repo view --json nameWithOwner,owner,url` でリポジトリを確定し、Project は `gh project list --owner <owner> --format json` で確認する。通常は `Agents: MeasureLab` を使う。
* `gh project item-list <number> --owner <owner> --limit <件数> --format json` で項目を取得する。既定件数で打ち切られていないか総件数を確認し、必要なら取得上限を増やす。Project・Issue の検索は全ページを確認する。
* 新規登録前は `gh issue list --state all --search ...` と必要な `gh issue view` で、タイトルだけでなく対象・目的も照合する。閉じた Issue も解決済み・却下などの理由を確認する。
* 計画・実装対象は指定 Issue を優先する。指定がなければ、対象 Status の中から Priority、計画の有無、測定への寄与で選ぶ。決められなければ候補と差を示して対象を確認し、未選択の Issue を変更しない。
* 対象 Issue の本文・コメント・ラベル・担当者・URL と Project item ID・Status を確認する。指定 Issue が想定 Status と異なる場合は依頼との整合を確認し、黙って状態を戻したり進めたりしない。認証診断はアクセスに失敗した場合だけ行う。

## 書き込み

書き込み直前に対象 URL と現在の Status を再確認する。想定と変わっていたら最新状態に合わせて判断し、他者の更新を上書きしない。Status フィールドと選択肢 ID は対象 Project の `gh project field-list` から取得し、固定値にしない。

新規 Issue の登録順序:

```bash
gh issue create --repo <owner>/<repo> --title '<title>' --body-file <body-file> --label <existing-label>
gh project item-add <number> --owner <owner> --url <issue-url> --format json
gh project field-list <number> --owner <owner> --format json
gh project item-edit --id <item-id> --field-id <status-field-id> --single-select-option-id <option-id> --project-id <project-id>
```

* 複数行の本文・コメントは作業ツリー外の一時ファイルに書き、`--body-file` で渡す。投稿後に一時ファイルを削除する。
* 既存 Issue・Project 項目を再利用できる場合は作り直さない。計画コメントや PR が状態変更の前提なら、それが成功した後にだけ Status を進める。
* 担当者・ラベル・Priority など依頼やスキルで扱わないフィールドは保持する。存在しない Project・選択肢・ラベルを勝手に新設しない。

## 再開と完了確認

操作結果が不明なら、再実行前に Issue・コメント・PR・Project を読み直す。成功済みの作成操作を繰り返さず、失敗した段階だけ再開する。権限不足など同じ原因で再試行しても改善しない場合は、成功済み URL と必要な対応を報告する。

`gh issue view`、`gh pr view`、Project の項目取得で最終状態を確認する。Issue URL と item ID を照合し、同名の PR 項目を誤って更新しない。PR を作成したら、利用可能な場合は Codex の `attach_artifact` でタスクへ添付する。
