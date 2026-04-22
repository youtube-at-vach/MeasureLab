const FALLBACK_VERSION = 'v0.6.3';
const RELEASE_BASE_URL = 'https://github.com/youtube-at-vach/MeasureLab/releases/download';
let currentVersion = FALLBACK_VERSION;

// OSに応じた情報
const osData = {
  macOS: {
    name: 'macOS',
    icon: '🍎',
    size: '約 90 MB',
    assetName: 'MeasureLab-{tag}-macos-arm64.dmg'
  },
  Windows: {
    name: 'Windows',
    icon: '🪟',
    size: '約 120 MB',
    assetName: 'MeasureLab-{tag}-windows-x64-onefile.zip'
  },
  Linux: {
    name: 'Linux',
    icon: '🐧',
    size: '約 150 MB',
    assetName: 'MeasureLab-{tag}-linux-x86_64.AppImage'
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
function updateMainDisplay(osName) {
  const data = osData[osName];
  if (!data) return;
  const downloadUrl = buildReleaseUrl(currentVersion, data.assetName);

  document.getElementById('main-os-icon').textContent = data.icon;
  document.getElementById('main-os-name').textContent = data.name;
  document.getElementById('main-version').textContent = currentVersion;
  document.getElementById('main-size').textContent = data.size;
  
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
