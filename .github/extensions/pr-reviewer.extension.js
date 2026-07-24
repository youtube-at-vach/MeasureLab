// PR Reviewer Skill Extension
// Copilot CLI 統合スキル

const SKILL_MANIFEST = {
  name: 'pr-reviewer',
  displayName: 'PR Reviewer',
  description: 'PRのレビュー、整合性検証、リスク評価を行うスキル',
  version: '1.0.0',
  author: 'MeasureLab Team',
  
  // スラッシュコマンド登録
  commands: {
    'pr-reviewer': {
      description: 'Pull Request をレビューします',
      usage: '/pr-reviewer <PR_NUMBER>',
      options: [
        {
          name: 'pr',
          description: 'PR番号',
          required: true,
          type: 'number'
        },
        {
          name: 'auto-approve',
          description: '問題がなければ自動承認する',
          type: 'boolean',
          default: false
        }
      ]
    }
  },
  
  // ツール依存関係
  requiredTools: [
    'github-mcp-server',
    'bash'
  ],
  
  // スキル実行ワークフロー
  workflow: [
    {
      step: 'fetch-pr-info',
      description: 'PR情報を取得',
      tool: 'github-mcp-server',
      action: 'get_pull_request'
    },
    {
      step: 'fetch-files',
      description: '変更ファイル一覧を取得',
      tool: 'github-mcp-server',
      action: 'get_pull_request_files'
    },
    {
      step: 'fetch-diff',
      description: '差分内容を取得',
      tool: 'github-mcp-server',
      action: 'get_pull_request_diff'
    },
    {
      step: 'analyze-code',
      description: 'コード分析を実施',
      tool: 'bash',
      action: 'run-analysis'
    },
    {
      step: 'submit-review',
      description: 'レビュー結果を投稿',
      tool: 'github-mcp-server',
      action: 'submit_review'
    }
  ]
};

module.exports = SKILL_MANIFEST;
