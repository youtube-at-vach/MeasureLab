const FALLBACK_VERSION = "v0.6.3";
const RELEASE_BASE_URL =
  "https://github.com/youtube-at-vach/MeasureLab/releases/download";
const SUPPORTED_LANGS = ["ja", "zh", "en"];

let currentVersion = FALLBACK_VERSION;
let currentVariantKey = null;
let currentLang = "en";
let currentOsName = "macOS";
let versionLoaded = false;

const translations = {
  ja: {
    htmlLang: "ja",
    title: "MeasureLab - オーディオ測定ツール",
    metaDescription:
      "MeasureLabは高精度なオーディオ分析と測定を行うためのオープンソースツールです。macOS、Windows、Linuxに対応。",
    subtitle: "オーディオ測定ツール",
    downloadFor: "Download for",
    heroDescription: "高精度なオーディオ分析と測定を、あなたのPCで。",
    otherPlatforms: "その他のプラットフォーム",
    requirementsTitle: "ダウンロード前に確認",
    docsLink: "ドキュメント",
    loading: "読み込み中...",
    requirementData: {
      macOS: {
        lead: "macOS 13以降が必要です。お使いのMacに合うDMGを選んでください。",
        items: [
          "Apple Silicon は arm64、Intel Mac は x64 を選択してください。",
          "未署名アプリのため、初回起動時は右クリックの「開く」または「システム設定 > プライバシーとセキュリティ」から許可が必要な場合があります。",
        ],
      },
      Windows: {
        lead: "Windows 10 / 11 向けのZIP版です。",
        items: [
          "ZIP を展開して MeasureLab.exe を実行してください。",
          "通常版 (onedir) と単一EXE版 (onefile) を選べます。",
        ],
      },
      Linux: {
        lead: "Linux 版は x86_64 向け AppImage です。",
        items: [
          "初回起動前に chmod +x で実行権限を付与してください。",
          "位相連続性が重要な測定では、環境に応じて JACK / PipeWire の利用が推奨されます。",
        ],
      },
    },
    osData: {
      macOS: {
        name: "macOS",
        icon: "🍎",
        defaultVariant: "arm64",
        variants: {
          arm64: {
            label: "Apple Silicon",
            size: "約 90 MB",
            assetName: "MeasureLab-{tag}-macos-arm64.dmg",
          },
          x64: {
            label: "Intel",
            size: "約 90 MB",
            assetName: "MeasureLab-{tag}-macos-x64.dmg",
          },
        },
      },
      Windows: {
        name: "Windows",
        icon: "🪟",
        defaultVariant: "onedir",
        variants: {
          onedir: {
            label: "通常版 (onedir)",
            size: "約 120 MB",
            assetName: "MeasureLab-{tag}-windows-x64-onedir.zip",
          },
          onefile: {
            label: "単一EXE版 (onefile)",
            size: "約 120 MB",
            assetName: "MeasureLab-{tag}-windows-x64-onefile.zip",
          },
        },
      },
      Linux: {
        name: "Linux",
        icon: "🐧",
        defaultVariant: "appimage",
        variants: {
          appimage: {
            label: "AppImage",
            size: "約 150 MB",
            assetName: "MeasureLab-{tag}-linux-x86_64.AppImage",
          },
        },
      },
    },
  },
  zh: {
    htmlLang: "zh-CN",
    title: "MeasureLab - 音频测量工具",
    metaDescription:
      "MeasureLab 是一款开源工具，可在 macOS、Windows 和 Linux 上进行高精度音频分析与测量。",
    subtitle: "音频测量工具",
    downloadFor: "下载适用于",
    heroDescription: "在你的电脑上进行高精度音频分析与测量。",
    otherPlatforms: "其他平台",
    requirementsTitle: "下载前请确认",
    docsLink: "文档",
    loading: "加载中...",
    requirementData: {
      macOS: {
        lead: "需要 macOS 13 或更高版本。请选择与你的 Mac 匹配的 DMG。",
        items: [
          "Apple Silicon 请选择 arm64，Intel Mac 请选择 x64。",
          "由于应用未签名，首次启动时可能需要通过右键菜单选择“打开”，或在“系统设置 > 隐私与安全性”中允许。",
        ],
      },
      Windows: {
        lead: "适用于 Windows 10 / 11 的 ZIP 包。",
        items: [
          "解压 ZIP 文件后运行 MeasureLab.exe。",
          "可选择标准版 (onedir) 或单文件 EXE 版 (onefile)。",
        ],
      },
      Linux: {
        lead: "Linux 版为面向 x86_64 的 AppImage。",
        items: [
          "首次启动前请执行 chmod +x 赋予可执行权限。",
          "对于需要相位连续性的测量，根据环境可能建议使用 JACK / PipeWire。",
        ],
      },
    },
    osData: {
      macOS: {
        name: "macOS",
        icon: "🍎",
        defaultVariant: "arm64",
        variants: {
          arm64: {
            label: "Apple Silicon",
            size: "约 90 MB",
            assetName: "MeasureLab-{tag}-macos-arm64.dmg",
          },
          x64: {
            label: "Intel",
            size: "约 90 MB",
            assetName: "MeasureLab-{tag}-macos-x64.dmg",
          },
        },
      },
      Windows: {
        name: "Windows",
        icon: "🪟",
        defaultVariant: "onedir",
        variants: {
          onedir: {
            label: "标准版 (onedir)",
            size: "约 120 MB",
            assetName: "MeasureLab-{tag}-windows-x64-onedir.zip",
          },
          onefile: {
            label: "单文件 EXE 版 (onefile)",
            size: "约 120 MB",
            assetName: "MeasureLab-{tag}-windows-x64-onefile.zip",
          },
        },
      },
      Linux: {
        name: "Linux",
        icon: "🐧",
        defaultVariant: "appimage",
        variants: {
          appimage: {
            label: "AppImage",
            size: "约 150 MB",
            assetName: "MeasureLab-{tag}-linux-x86_64.AppImage",
          },
        },
      },
    },
  },
  en: {
    htmlLang: "en",
    title: "MeasureLab - Audio Measurement Tool",
    metaDescription:
      "MeasureLab is an open-source tool for high-precision audio analysis and measurement on macOS, Windows, and Linux.",
    subtitle: "Audio Measurement Tool",
    downloadFor: "Download for",
    heroDescription:
      "High-precision audio analysis and measurement on your computer.",
    otherPlatforms: "Other platforms",
    requirementsTitle: "Before you download",
    docsLink: "Documentation",
    loading: "Loading...",
    requirementData: {
      macOS: {
        lead: "Requires macOS 13 or later. Choose the DMG that matches your Mac.",
        items: [
          "Select arm64 for Apple Silicon and x64 for Intel Macs.",
          'Because the app is unsigned, first launch may require using "Open" from the context menu or allowing it in System Settings > Privacy & Security.',
        ],
      },
      Windows: {
        lead: "ZIP package for Windows 10 / 11.",
        items: [
          "Extract the ZIP archive and run MeasureLab.exe.",
          "You can choose between the standard build (onedir) and the single EXE build (onefile).",
        ],
      },
      Linux: {
        lead: "The Linux build is an x86_64 AppImage.",
        items: [
          "Run chmod +x before the first launch to make it executable.",
          "For measurements where phase continuity matters, JACK / PipeWire may be recommended depending on your environment.",
        ],
      },
    },
    osData: {
      macOS: {
        name: "macOS",
        icon: "🍎",
        defaultVariant: "arm64",
        variants: {
          arm64: {
            label: "Apple Silicon",
            size: "~90 MB",
            assetName: "MeasureLab-{tag}-macos-arm64.dmg",
          },
          x64: {
            label: "Intel",
            size: "~90 MB",
            assetName: "MeasureLab-{tag}-macos-x64.dmg",
          },
        },
      },
      Windows: {
        name: "Windows",
        icon: "🪟",
        defaultVariant: "onedir",
        variants: {
          onedir: {
            label: "Standard (onedir)",
            size: "~120 MB",
            assetName: "MeasureLab-{tag}-windows-x64-onedir.zip",
          },
          onefile: {
            label: "Single EXE (onefile)",
            size: "~120 MB",
            assetName: "MeasureLab-{tag}-windows-x64-onefile.zip",
          },
        },
      },
      Linux: {
        name: "Linux",
        icon: "🐧",
        defaultVariant: "appimage",
        variants: {
          appimage: {
            label: "AppImage",
            size: "~150 MB",
            assetName: "MeasureLab-{tag}-linux-x86_64.AppImage",
          },
        },
      },
    },
  },
};

function getMessages() {
  return translations[currentLang];
}

function getOsData() {
  return getMessages().osData;
}

function normalizeVersionTag(version) {
  const trimmed = String(version ?? "").trim();
  if (!trimmed) {
    return FALLBACK_VERSION;
  }

  return trimmed.startsWith("v") ? trimmed : `v${trimmed}`;
}

function getVersionJsonUrl() {
  return new URL("../version.json", window.location.href);
}

async function loadVersionTag() {
  try {
    const response = await fetch(getVersionJsonUrl(), { cache: "no-cache" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    return normalizeVersionTag(data.version);
  } catch (error) {
    console.warn("Failed to load version.json, using fallback version.", error);
    return FALLBACK_VERSION;
  }
}

function buildReleaseUrl(versionTag, assetNameTemplate) {
  const assetName = assetNameTemplate.replace("{tag}", versionTag);
  return `${RELEASE_BASE_URL}/${versionTag}/${assetName}`;
}

function getVariantEntries(osName) {
  const data = getOsData()[osName];
  if (!data) {
    return [];
  }

  return Object.entries(data.variants);
}

function selectVariant(osName, requestedVariantKey) {
  const data = getOsData()[osName];
  if (!data) {
    return null;
  }

  if (requestedVariantKey && data.variants[requestedVariantKey]) {
    return requestedVariantKey;
  }

  return data.defaultVariant;
}

function getLanguageFromQuery() {
  const params = new URLSearchParams(window.location.search);
  const lang = params.get("lang");
  return SUPPORTED_LANGS.includes(lang) ? lang : null;
}

function normalizeLanguage(lang) {
  const normalizedLang = String(lang || "").toLowerCase();

  if (normalizedLang.startsWith("ja")) {
    return "ja";
  }

  if (normalizedLang.startsWith("zh")) {
    return "zh";
  }

  if (normalizedLang.startsWith("en")) {
    return "en";
  }

  return null;
}

function detectLanguage() {
  const queryLang = getLanguageFromQuery();
  if (queryLang) {
    return queryLang;
  }

  const browserLangs = [
    ...(window.navigator.languages || []),
    window.navigator.language,
  ];

  for (const browserLang of browserLangs) {
    const lang = normalizeLanguage(browserLang);
    if (lang) {
      return lang;
    }
  }

  return "en";
}

function syncLanguageQuery(lang) {
  const url = new URL(window.location.href);
  url.searchParams.set("lang", lang);
  window.history.replaceState({}, "", url);
}

function applyStaticTranslations() {
  const messages = getMessages();

  document.documentElement.lang = messages.htmlLang;
  document.title = messages.title;

  const metaDescription = document.querySelector('meta[name="description"]');
  if (metaDescription) {
    metaDescription.setAttribute("content", messages.metaDescription);
  }

  document.querySelectorAll("[data-i18n]").forEach((element) => {
    const key = element.dataset.i18n;
    if (key && messages[key]) {
      element.textContent = messages[key];
    }
  });

  const versionElement = document.getElementById("main-version");
  if (versionElement && !versionLoaded) {
    versionElement.textContent = messages.loading;
  }

  document.querySelectorAll(".lang-btn").forEach((button) => {
    const isActive = button.dataset.lang === currentLang;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
}

function renderVariantPicker(osName) {
  const picker = document.getElementById("variant-picker");
  const variantEntries = getVariantEntries(osName);
  picker.innerHTML = "";

  if (variantEntries.length <= 1) {
    picker.hidden = true;
    return;
  }

  variantEntries.forEach(([variantKey, variant]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "variant-btn";
    button.textContent = variant.label;
    button.dataset.variant = variantKey;

    if (variantKey === currentVariantKey) {
      button.classList.add("is-active");
    }

    button.addEventListener("click", () => {
      updateMainDisplay(osName, variantKey);
    });

    picker.appendChild(button);
  });

  picker.hidden = false;
}

function renderRequirements(osName) {
  const requirement = getMessages().requirementData[osName];
  if (!requirement) {
    return;
  }

  const lead = document.getElementById("requirements-lead");
  const list = document.getElementById("requirements-list");
  lead.textContent = requirement.lead;
  list.innerHTML = "";

  requirement.items.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    list.appendChild(li);
  });
}

function detectOS() {
  const userAgent = window.navigator.userAgent;
  let os = "Windows";

  if (userAgent.indexOf("Mac") !== -1) {
    os = "macOS";
  } else if (
    userAgent.indexOf("Linux") !== -1 ||
    userAgent.indexOf("X11") !== -1
  ) {
    os = "Linux";
  }

  return os;
}

function updateMainDisplay(osName, requestedVariantKey = null) {
  const data = getOsData()[osName];
  if (!data) {
    return;
  }

  currentOsName = osName;
  currentVariantKey = selectVariant(osName, requestedVariantKey);
  const variant = data.variants[currentVariantKey];
  const downloadUrl = buildReleaseUrl(currentVersion, variant.assetName);

  document.getElementById("main-os-icon").textContent = data.icon;
  document.getElementById("main-os-name").textContent = data.name;
  document.getElementById("main-version").textContent = currentVersion;
  document.getElementById("main-variant").textContent = variant.label;
  document.getElementById("main-size").textContent = variant.size;
  renderVariantPicker(osName);
  renderRequirements(osName);

  const mainBtn = document.getElementById("main-download-btn");
  mainBtn.onclick = () => {
    window.location.href = downloadUrl;
  };
}

function setLanguage(lang, osName, requestedVariantKey = null) {
  currentLang = SUPPORTED_LANGS.includes(lang) ? lang : "en";
  syncLanguageQuery(currentLang);
  applyStaticTranslations();
  updateMainDisplay(osName, requestedVariantKey ?? currentVariantKey);
}

document.addEventListener("DOMContentLoaded", async () => {
  currentLang = detectLanguage();
  applyStaticTranslations();

  currentVersion = await loadVersionTag();
  versionLoaded = true;

  const detectedOS = detectOS();
  updateMainDisplay(detectedOS);

  document.querySelectorAll(".btn-small").forEach((button) => {
    button.addEventListener("click", (event) => {
      const selectedOS = event.currentTarget.getAttribute("data-os");
      updateMainDisplay(selectedOS);

      const mainBtn = document.getElementById("main-download-btn");
      mainBtn.classList.remove("pulse");
      void mainBtn.offsetWidth;
      mainBtn.classList.add("pulse");
    });
  });

  document.querySelectorAll(".lang-btn").forEach((button) => {
    button.addEventListener("click", () => {
      setLanguage(button.dataset.lang, currentOsName, currentVariantKey);
    });
  });
});
