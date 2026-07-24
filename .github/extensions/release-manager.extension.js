// Release Manager Skill Extension
// Copilot CLI 統合スキル

const SKILL_MANIFEST = {
  name: 'release-manager',
  displayName: 'Release Manager',
  description: 'リリース準備（CHANGELOG更新、バージョンアップ、Lint、PR作成）を行うスキル',
  version: '1.0.0',
  author: 'MeasureLab Team',
  
  // スラッシュコマンド登録
  commands: {
    'release-manager': {
      description: 'リリース準備を実行します',
      usage: '/release-manager [--version <VERSION>]',
      options: [
        {
          name: 'version',
          description: 'リリース予定のバージョン番号（例: 1.5.0）',
          type: 'string',
          required: false
        },
        {
          name: 'skip-screenshots',
          description: 'スクリーンショット更新をスキップ',
          type: 'boolean',
          default: false
        }
      ]
    }
  },
  
  // ツール依存関係
  requiredTools: [
    'bash',
    'venv',  // 仮想環境
    'git'
  ],
  
  // スキル実行ワークフロー
  workflow: [
    {
      step: 'check-latest-tag',
      description: '最新のリリースタグを確認',
      tool: 'bash',
      command: 'git describe --tags --abbrev=0',
      critical: false
    },
    {
      step: 'review-changes',
      description: '最新タグからの変更を確認',
      tool: 'bash',
      command: 'git log [latest_tag]..HEAD --oneline',
      critical: false
    },
    {
      step: 'update-changelog',
      description: 'CHANGELOG.mdを更新',
      tool: 'bash',
      command: 'manual-review',  // ユーザーレビュー必須
      critical: true
    },
    {
      step: 'check-docs',
      description: 'ドキュメントの記述漏れをチェック',
      tool: 'bash',
      command: 'manual-review',  // ユーザーレビュー必須
      critical: true
    },
    {
      step: 'update-version',
      description: 'バージョンを更新',
      tool: 'bash',
      command: 'manual-update',  // ユーザーが指定したバージョンで更新
      files: [
        'pyproject.toml',
        'src/core/version.py',
        'version.json'
      ],
      critical: true
    },
    {
      step: 'ruff-fix',
      description: 'コードを修正',
      tool: 'bash',
      command: '.venv/bin/ruff check --fix .',
      critical: false
    },
    {
      step: 'markdown-lint',
      description: 'Markdownをチェック',
      tool: 'bash',
      command: 'npx markdownlint-cli2 "**/*.md" "#node_modules"',
      critical: false
    },
    {
      step: 'update-screenshots',
      description: 'ドキュメント用スクリーンショットを更新',
      tool: 'bash',
      command: '.venv/bin/python3 scripts/capture_widget_screenshots.py',
      critical: false,
      optional: true
    },
    {
      step: 'create-release-pr',
      description: 'リリース準備PRを作成',
      tool: 'bash',
      command: 'git checkout -b release/v[VERSION]',
      critical: true
    }
  ],
  
  // 設定
  config: {
    // バージョンファイルの位置
    versionFiles: [
      { path: 'pyproject.toml', key: 'version' },
      { path: 'src/core/version.py', key: '__version__' },
      { path: 'version.json', key: 'version' }
    ],
    
    // CHANGELOG
    changelogPath: 'CHANGELOG.md',
    
    // ドキュメント
    docsPath: 'docs/',
    
    // スクリプト
    screenshotScript: 'scripts/capture_widget_screenshots.py'
  }
};

module.exports = SKILL_MANIFEST;
