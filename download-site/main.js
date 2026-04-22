const FALLBACK_VERSION = 'v0.6.3';
const RELEASE_BASE_URL = 'https://github.com/youtube-at-vach/MeasureLab/releases/download';
let currentVersion = FALLBACK_VERSION;
let currentVariantKey = null;

const requirementData = {
  macOS: {
    lead: 'macOS 13以降が必要です。お使いのMacに合うDMGを選んでください。',
    items: [
      'Apple Silicon は arm64、Intel Mac は x64 を選択してください。',
      '未署名アプリのため、初回起動時は右クリックの「開く」または「システム設定 > プライバシーとセキュリティ」から許可が必要な場合があります。'
    ]
  },
  Windows: {
    lead: 'Windows 10 / 11 向けのZIP版です。',
    items: [
      'ZIP を展開して MeasureLab.exe を実行してください。',
      '通常版 (onedir) と単一EXE版 (onefile) を選べます。'
    ]
  },
  Linux: {
    lead: 'Linux 版は x86_64 向け AppImage です。',
    items: [
      '初回起動前に chmod +x で実行権限を付与してください。',
      '位相連続性が重要な測定では、環境に応じて JACK / PipeWire の利用が推奨されます。'
    ]
  }
};

// OSに応じた情報
const osData = {
  macOS: {
    name: 'macOS',
    icon: '🍎',
    defaultVariant: 'arm64',
    variants: {
      arm64: {
        label: 'Apple Silicon',
        size: '約 90 MB',
        assetName: 'MeasureLab-{tag}-macos-arm64.dmg'
      },
      x64: {
        label: 'Intel',
        size: '約 90 MB',
        assetName: 'MeasureLab-{tag}-macos-x64.dmg'
      }
    }
  },
  Windows: {
    name: 'Windows',
    icon: '🪟',
    defaultVariant: 'onedir',
    variants: {
      onedir: {
        label: '通常版 (onedir)',
        size: '約 120 MB',
        assetName: 'MeasureLab-{tag}-windows-x64-onedir.zip'
      },
      onefile: {
        label: '単一EXE版 (onefile)',
        size: '約 120 MB',
        assetName: 'MeasureLab-{tag}-windows-x64-onefile.zip'
      }
    }
  },
  Linux: {
    name: 'Linux',
    icon: '🐧',
    defaultVariant: 'appimage',
    variants: {
      appimage: {
        label: 'AppImage',
        size: '約 150 MB',
        assetName: 'MeasureLab-{tag}-linux-x86_64.AppImage'
      }
    }
  }
};

function normalizeVersionTag(version) {
  const trimmed = String(version ?? '').trim();
  if (!trimmed) {
    return FALLBACK_VERSION;
  }

  return trimmed.startsWith('v') ? trimmed : `v${trimmed}`;
}

function getVersionJsonUrl() {
  return new URL('../version.json', window.location.href);
}

async function loadVersionTag() {
  try {
    const response = await fetch(getVersionJsonUrl(), { cache: 'no-cache' });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    return normalizeVersionTag(data.version);
  } catch (error) {
    console.warn('Failed to load version.json, using fallback version.', error);
    return FALLBACK_VERSION;
  }
}

function buildReleaseUrl(versionTag, assetNameTemplate) {
  const assetName = assetNameTemplate.replace('{tag}', versionTag);
  return `${RELEASE_BASE_URL}/${versionTag}/${assetName}`;
}

function getVariantEntries(osName) {
  const data = osData[osName];
  if (!data) {
    return [];
  }

  return Object.entries(data.variants);
}

function selectVariant(osName, requestedVariantKey) {
  const data = osData[osName];
  if (!data) {
    return null;
  }

  if (requestedVariantKey && data.variants[requestedVariantKey]) {
    return requestedVariantKey;
  }

  return data.defaultVariant;
}

function renderVariantPicker(osName) {
  const picker = document.getElementById('variant-picker');
  const variantEntries = getVariantEntries(osName);
  picker.innerHTML = '';

  if (variantEntries.length <= 1) {
    picker.hidden = true;
    return;
  }

  variantEntries.forEach(([variantKey, variant]) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'variant-btn';
    button.textContent = variant.label;
    button.dataset.variant = variantKey;

    if (variantKey === currentVariantKey) {
      button.classList.add('is-active');
    }

    button.addEventListener('click', () => {
      updateMainDisplay(osName, variantKey);
    });

    picker.appendChild(button);
  });

  picker.hidden = false;
}

function renderRequirements(osName) {
  const requirement = requirementData[osName];
  if (!requirement) {
    return;
  }

  const lead = document.getElementById('requirements-lead');
  const list = document.getElementById('requirements-list');
  lead.textContent = requirement.lead;
  list.innerHTML = '';

  requirement.items.forEach((item) => {
    const li = document.createElement('li');
    li.textContent = item;
    list.appendChild(li);
  });
}

// ユーザーのOSを判定
function detectOS() {
  const userAgent = window.navigator.userAgent;
  let os = 'Windows'; // デフォルト

  if (userAgent.indexOf('Mac') !== -1) {
    os = 'macOS';
  } else if (userAgent.indexOf('Linux') !== -1 || userAgent.indexOf('X11') !== -1) {
    os = 'Linux';
  }
  
  return os;
}

// 画面の情報を更新
function updateMainDisplay(osName, requestedVariantKey = null) {
  const data = osData[osName];
  if (!data) return;
  currentVariantKey = selectVariant(osName, requestedVariantKey);
  const variant = data.variants[currentVariantKey];
  const downloadUrl = buildReleaseUrl(currentVersion, variant.assetName);

  document.getElementById('main-os-icon').textContent = data.icon;
  document.getElementById('main-os-name').textContent = data.name;
  document.getElementById('main-version').textContent = currentVersion;
  document.getElementById('main-variant').textContent = variant.label;
  document.getElementById('main-size').textContent = variant.size;
  renderVariantPicker(osName);
  renderRequirements(osName);
  
  // メインボタンのリンク設定
  const mainBtn = document.getElementById('main-download-btn');
  mainBtn.onclick = () => {
    window.location.href = downloadUrl;
  };
}

// 初期化
document.addEventListener('DOMContentLoaded', async () => {
  currentVersion = await loadVersionTag();

  // 自動判定して表示
  const detectedOS = detectOS();
  updateMainDisplay(detectedOS);

  // その他のOSボタンのイベントリスナー
  const smallBtns = document.querySelectorAll('.btn-small');
  smallBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      const selectedOS = e.currentTarget.getAttribute('data-os');
      updateMainDisplay(selectedOS);
      
      // クリック後、少しアニメーションをリセットして目立たせる
      const mainBtn = document.getElementById('main-download-btn');
      mainBtn.classList.remove('pulse');
      void mainBtn.offsetWidth; // リフローを強制
      mainBtn.classList.add('pulse');
    });
  });
});
