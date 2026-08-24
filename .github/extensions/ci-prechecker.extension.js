// CI Pre-checker Skill Extension
// Copilot CLI 統合スキル

const SKILL_MANIFEST = {
  name: 'ci-prechecker',
  displayName: 'CI Pre-checker',
  description: 'PRを送る前に変更がCIを通るかどうかを確認するスキル',
  version: '1.0.0',
  author: 'MeasureLab Team',
  
  // スラッシュコマンド登録
  commands: {
    'ci-prechecker': {
      description: 'CIチェック（Ruff lint/format, Mypy, 翻訳キー, Markdown lint, Pytest）を実行します',
      usage: '/ci-prechecker [--fix] [--strict]',
      options: [
        {
          name: 'fix',
          description: '自動修正を有効にする（Ruff）',
          type: 'boolean',
          default: false
        },
        {
          name: 'strict',
          description: '厳格モード（翻訳キーチェック）',
          type: 'boolean',
          default: false
        },
        {
          name: 'skip-tests',
          description: 'Pytestをスキップ',
          type: 'boolean',
          default: false
        }
      ]
    }
  },
  
  // ツール依存関係
  requiredTools: [
    'bash',
    'venv'  // 仮想環境
  ],
  
  // スキル実行ワークフロー
  workflow: [
    {
      step: 'ruff-check',
      description: 'Pythonコードのリンティング',
      tool: 'bash',
      command: '.venv/bin/ruff check .',
      critical: true
    },
    {
      step: 'ruff-format-check',
      description: 'Pythonコードのフォーマット確認',
      tool: 'bash',
      command: '.venv/bin/ruff format --check .',
      critical: true
    },
    {
      step: 'mypy-check',
      description: '型チェック',
      tool: 'bash',
      command: '.venv/bin/mypy src main_gui.py',
      critical: true
    },
    {
      step: 'translation-check',
      description: '翻訳キーの整合性確認',
      tool: 'bash',
      command: 'python3 scripts/check_trn_keys.py',
      critical: true
    },
    {
      step: 'markdown-lint',
      description: 'Markdownドキュメントのチェック',
      tool: 'bash',
      command: 'npx markdownlint-cli2 "**/*.md" "#node_modules"',
      critical: false  // 警告レベル
    },
    {
      step: 'pytest',
      description: 'ユニットテストの実行',
      tool: 'bash',
      command: '.venv/bin/pytest',
      critical: true
    }
  ]
};

module.exports = SKILL_MANIFEST;
