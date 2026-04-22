const VERSION = 'v0.6.3'; // GitHub Actionsなどで自動更新される想定
const UPDATE_DATE = '2026-04-16 更新';

// OSに応じた情報
const osData = {
  macOS: {
    name: 'macOS',
    icon: '🍎',
    size: '約 90 MB',
    link: `https://github.com/youtube-at-vach/MeasureLab/releases/download/${VERSION}/MeasureLab_macOS.zip` // 例
  },
  Windows: {
    name: 'Windows',
    icon: '🪟',
    size: '約 120 MB',
    link: `https://github.com/youtube-at-vach/MeasureLab/releases/download/${VERSION}/MeasureLab_Windows.zip` // 例
  },
  Linux: {
    name: 'Linux',
    icon: '🐧',
    size: '約 150 MB',
    link: `https://github.com/youtube-at-vach/MeasureLab/releases/download/${VERSION}/MeasureLab_Linux.AppImage` // 例
  }
};

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

  document.getElementById('main-os-icon').textContent = data.icon;
  document.getElementById('main-os-name').textContent = data.name;
  document.getElementById('main-version').textContent = VERSION;
  document.getElementById('main-size').textContent = data.size;
  document.getElementById('main-date').textContent = UPDATE_DATE;
  
  // メインボタンのリンク設定
  const mainBtn = document.getElementById('main-download-btn');
  mainBtn.onclick = () => {
    window.location.href = data.link;
  };
}

// 初期化
document.addEventListener('DOMContentLoaded', () => {
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
