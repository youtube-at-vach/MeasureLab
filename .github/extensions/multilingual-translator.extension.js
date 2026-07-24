// Multilingual Translator Skill Extension
// Copilot CLI 統合スキル

const SKILL_MANIFEST = {
  name: 'multilingual-translator',
  displayName: 'Multilingual Translator',
  description: '翻訳漏れの検知、修正、および多言語ファイルの更新を行うスキル',
  version: '1.0.0',
  author: 'MeasureLab Team',
  
  // スラッシュコマンド登録
  commands: {
    'multilingual-translator': {
      description: '翻訳キーの検証・修正・更新を行います',
      usage: '/multilingual-translator [--check] [--fix] [--strict]',
      options: [
        {
          name: 'check',
          description: '翻訳状態のチェックのみ実施',
          type: 'boolean',
          default: true
        },
        {
          name: 'fix',
          description: '翻訳キーを自動修正',
          type: 'boolean',
          default: false
        },
        {
          name: 'strict',
          description: '厳格モード（プレースホルダーをエラーとして検出）',
          type: 'boolean',
          default: false
        }
      ]
    }
  },
  
  // ツール依存関係
  requiredTools: [
    'bash',
    'python'
  ],
  
  // スキル実行ワークフロー
  workflow: [
    {
      step: 'check-translations',
      description: '翻訳漏れを検出',
      tool: 'bash',
      command: 'python3 scripts/check_trn_keys.py',
      critical: true
    },
    {
      step: 'update-translations',
      description: '不足キーを一括追加',
      tool: 'bash',
      command: 'python3 scripts/update_translations.py',
      critical: false,
      conditional: 'if-missing-keys'
    },
    {
      step: 'verify-translations',
      description: '翻訳状態を最終検証',
      tool: 'bash',
      command: 'python3 scripts/check_trn_keys.py',
      critical: true
    }
  ],
  
  // 設定
  config: {
    // 言語ファイルの場所
    languageDir: 'src/assets/lang/',
    
    // サポートされている言語
    supportedLanguages: [
      { code: 'en', name: 'English', file: 'en.json' },
      { code: 'ja', name: '日本語', file: 'ja.json' }
    ],
    
    // チェックスクリプトの位置
    checkScript: 'scripts/check_trn_keys.py',
    updateScript: 'scripts/update_translations.py',
    whitelistFile: 'scripts/translation_whitelist.json'
  }
};

module.exports = SKILL_MANIFEST;
