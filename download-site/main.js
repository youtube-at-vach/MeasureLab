import {
  DOWNLOADS,
  downloadUrl,
  hasWindowsInstaller,
  loadRustRelease,
} from "./release-assets.js";
import { rustMessages } from "./rust-messages.js";
import { pageMessages } from "./page-messages.js";
import { detectDesktopOS } from "./platform-detection.js";
import plannedRustRelease from "../rust-release.json" with { type: "json" };

import publishedVersion from "../version.json" with { type: "json" };

const FALLBACK_VERSION = `v${publishedVersion.version}`;
const SUPPORTED_LANGS = ["ja", "zh", "en"];

let currentEdition = "python";
let currentVersion = FALLBACK_VERSION;
let rustRelease = { ...plannedRustRelease, published: false };
let currentVariantKey = null;
let variantSelectedByUser = false;
let currentLang = "en";
let currentOsName = "macOS";
let windowsInstallerAvailable = false;
const recommendedOsName = detectDesktopOS(window.navigator);

const translations = {
  ja: {
    htmlLang: "ja",
    title: "MeasureLab - オーディオ測定ツール",
    metaDescription:
      "MeasureLabは高精度なオーディオ分析と測定を行うためのオープンソースツールです。macOS、Windows、Linuxに対応。",
    docsLink: "Python v0.9.1 マニュアル",
    requirementData: {
      macOS: {
        lead: "macOS 13以降が必要です。お使いのMacに合うDMGを選んでください。",
        items: [
          "Apple Silicon は arm64、Intel Mac は x64 を選択してください。",
          "未署名アプリのため、初回起動時は右クリックの「開く」または「システム設定 > プライバシーとセキュリティ」から許可が必要な場合があります。",
        ],
      },
      Windows: {
        lead: "Windows 10 / 11（x64）向けです。",
        installerHint:
          "インストーラーを実行すると、管理者権限なしでインストールできます。",
        items: ["ZIP版は展開して MeasureLab.exe を実行してください。"],
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
        defaultVariant: "arm64",
        variants: {
          arm64: {
            label: "Apple Silicon",
            size: "約 90 MB",
          },
          x64: {
            label: "Intel",
            size: "約 90 MB",
          },
        },
      },
      Windows: {
        name: "Windows",
        defaultVariant: "installer",
        variants: {
          installer: {
            label: "インストーラー（推奨）",
            size: "サイズはリリースページを参照",
          },
          onedir: {
            label: "ZIP版 (onedir)",
            size: "約 120 MB",
          },
        },
      },
      Linux: {
        name: "Linux",
        defaultVariant: "appimage",
        variants: {
          appimage: {
            label: "AppImage",
            size: "約 150 MB",
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
    docsLink: "Python v0.9.1 文档",
    requirementData: {
      macOS: {
        lead: "需要 macOS 13 或更高版本。请选择与你的 Mac 匹配的 DMG。",
        items: [
          "Apple Silicon 请选择 arm64，Intel Mac 请选择 x64。",
          "由于应用未签名，首次启动时可能需要通过右键菜单选择“打开”，或在“系统设置 > 隐私与安全性”中允许。",
        ],
      },
      Windows: {
        lead: "适用于 Windows 10 / 11（x64）。",
        installerHint: "运行安装程序，无需管理员权限即可安装。",
        items: ["使用 ZIP 版时，解压后运行 MeasureLab.exe。"],
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
        defaultVariant: "arm64",
        variants: {
          arm64: {
            label: "Apple Silicon",
            size: "约 90 MB",
          },
          x64: {
            label: "Intel",
            size: "约 90 MB",
          },
        },
      },
      Windows: {
        name: "Windows",
        defaultVariant: "installer",
        variants: {
          installer: {
            label: "安装程序（推荐）",
            size: "大小请参阅发布页面",
          },
          onedir: {
            label: "ZIP 版 (onedir)",
            size: "约 120 MB",
          },
        },
      },
      Linux: {
        name: "Linux",
        defaultVariant: "appimage",
        variants: {
          appimage: {
            label: "AppImage",
            size: "约 150 MB",
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
    docsLink: "Python v0.9.1 manual",
    requirementData: {
      macOS: {
        lead: "Requires macOS 13 or later. Choose the DMG that matches your Mac.",
        items: [
          "Select arm64 for Apple Silicon and x64 for Intel Macs.",
          'Because the app is unsigned, first launch may require using "Open" from the context menu or allowing it in System Settings > Privacy & Security.',
        ],
      },
      Windows: {
        lead: "For Windows 10 / 11 (x64).",
        installerHint:
          "Run the installer to install for your account without administrator privileges.",
        items: ["For ZIP builds, extract the archive and run MeasureLab.exe."],
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
        defaultVariant: "arm64",
        variants: {
          arm64: {
            label: "Apple Silicon",
            size: "~90 MB",
          },
          x64: {
            label: "Intel",
            size: "~90 MB",
          },
        },
      },
      Windows: {
        name: "Windows",
        defaultVariant: "installer",
        variants: {
          installer: {
            label: "Installer (recommended)",
            size: "See release for size",
          },
          onedir: {
            label: "ZIP (onedir)",
            size: "~120 MB",
          },
        },
      },
      Linux: {
        name: "Linux",
        defaultVariant: "appimage",
        variants: {
          appimage: {
            label: "AppImage",
            size: "~150 MB",
          },
        },
      },
    },
  },
};

function getMessages() {
  const extra = rustMessages[currentLang];
  return {
    ...translations[currentLang],
    ...pageMessages[currentLang],
    releaseDetails: extra.releaseDetails,
    ...(currentEdition === "rust"
      ? {
          docsLink: extra.docsLink,
          requirementData: extra.requirementData,
        }
      : {}),
  };
}

function getOsData() {
  const data = translations[currentLang].osData;
  if (currentEdition === "python") return data;
  const messages = rustMessages[currentLang];
  return Object.fromEntries(
    Object.entries(data).map(([osName, os]) => [
      osName,
      {
        ...os,
        variants: Object.fromEntries(
          Object.keys(DOWNLOADS.rust[osName]).map((key) => [
            key,
            {
              label: messages.labels[key],
              size: messages.releaseSize,
            },
          ]),
        ),
      },
    ]),
  );
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
    const response = await fetch(getVersionJsonUrl(), {
      cache: "no-cache",
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    return data.version === publishedVersion.version
      ? normalizeVersionTag(data.version)
      : FALLBACK_VERSION;
  } catch (error) {
    console.warn("Failed to load version.json, using fallback version.", error);
    return FALLBACK_VERSION;
  }
}

function getVariantEntries(osName) {
  const data = getOsData()[osName];
  if (!data) {
    return [];
  }

  return Object.entries(data.variants).filter(
    ([key]) =>
      currentEdition === "rust" ||
      osName !== "Windows" ||
      key !== "installer" ||
      windowsInstallerAvailable,
  );
}

function selectVariant(osName, requestedVariantKey) {
  const data = getOsData()[osName];
  if (!data) {
    return null;
  }

  const availableKeys = getVariantEntries(osName).map(([key]) => key);
  if (availableKeys.includes(requestedVariantKey)) {
    return requestedVariantKey;
  }

  return availableKeys.includes(data.defaultVariant)
    ? data.defaultVariant
    : availableKeys[0];
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

  document.getElementById("manual-link").href =
    currentEdition === "rust"
      ? currentLang === "en"
        ? "/MeasureLab/rust/en/"
        : "/MeasureLab/rust/"
      : currentLang === "en"
        ? "/MeasureLab/en/"
        : "/MeasureLab/";
  document.querySelectorAll(".edition-manual-link").forEach((link) => {
    link.href = document.getElementById("manual-link").href;
  });
  document.querySelectorAll(".rust-manual-link").forEach((link) => {
    link.href =
      currentLang === "en" ? "/MeasureLab/rust/en/" : "/MeasureLab/rust/";
  });
  document.querySelectorAll("[data-i18n-aria]").forEach((element) => {
    element.setAttribute("aria-label", messages[element.dataset.i18nAria]);
  });
  document.body.dataset.edition = currentEdition;
  document.body.dataset.rustPublished = String(rustRelease.published);
  document.getElementById("hero-release-status").textContent =
    rustRelease.published ? messages.available : messages.preparing;
  document.getElementById("hero-version").textContent =
    `v${rustRelease.version}`;
  document.getElementById("hero-download-label").textContent =
    rustRelease.published
      ? messages.heroRustAction.replace("{version}", `v${rustRelease.version}`)
      : messages.heroAction;
  document.getElementById("python-edition-version").textContent =
    currentVersion;
  document.getElementById("rust-edition-version").textContent =
    `v${rustRelease.version}`;
  document.getElementById("rust-edition-status").textContent =
    rustRelease.published ? messages.rustAvailable : messages.unavailable;
  document.getElementById("edition-notice-text").textContent =
    currentEdition === "python"
      ? messages.legacyNotice
      : rustRelease.published
        ? rustMessages[currentLang].publishedNotice
        : messages.rustNotice;
  document.getElementById("experimental-note").hidden =
    currentEdition !== "rust" || rustRelease.published;
  document.querySelectorAll(".edition-btn").forEach((button) => {
    const active = button.dataset.edition === currentEdition;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });

  document.querySelectorAll(".lang-btn").forEach((button) => {
    const isActive = button.dataset.lang === currentLang;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
}

function renderVariantPicker(osName) {
  const picker = document.getElementById("variant-picker");
  const variantEntries = getVariantEntries(osName);
  const focusedVariant = picker.contains(document.activeElement)
    ? document.activeElement.dataset.variant
    : null;
  picker.innerHTML = "";

  variantEntries.forEach(([variantKey, variant]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "variant-btn";
    let [label, ...details] = variant.label.split(" · ");
    if (osName !== "macOS" && details.length) {
      const architecture = label;
      label = details.join(" · ");
      details = [architecture];
    }
    const name = document.createElement("span");
    name.className = "variant-label";
    name.textContent = label;
    button.appendChild(name);
    if (details.length) {
      const detail = document.createElement("span");
      detail.className = "variant-detail";
      detail.textContent = details.join(" · ");
      button.appendChild(detail);
    }
    button.dataset.variant = variantKey;
    button.setAttribute("aria-label", variant.label);

    button.setAttribute(
      "aria-pressed",
      String(variantKey === currentVariantKey),
    );
    if (variantKey === currentVariantKey) {
      button.classList.add("is-active");
    }

    button.addEventListener("click", () => {
      variantSelectedByUser = true;
      updateMainDisplay(osName, variantKey);
    });

    picker.appendChild(button);
  });

  picker.hidden = false;
  if (focusedVariant)
    picker.querySelector(`[data-variant="${focusedVariant}"]`)?.focus();
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

  const items =
    currentEdition === "python" &&
    osName === "Windows" &&
    windowsInstallerAvailable
      ? [requirement.installerHint, ...requirement.items]
      : requirement.items;
  items.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    list.appendChild(li);
  });
}

function detectOS() {
  return recommendedOsName ?? "Windows";
}

function renderPackageHelp(osName) {
  const messages = getMessages();
  let text = messages.packageHelpData[osName];
  if (
    osName === "Windows" &&
    currentEdition === "python" &&
    !windowsInstallerAvailable
  ) {
    text = messages.windowsZipHelp;
  } else if (osName === "Linux" && currentEdition === "rust") {
    text = messages.linuxRustHelp;
  }
  document.getElementById("package-help-text").textContent = text;
}

function updateMainDisplay(osName, requestedVariantKey = null) {
  const data = getOsData()[osName];
  if (!data) {
    return;
  }

  currentOsName = osName;
  currentVariantKey = selectVariant(osName, requestedVariantKey);
  const variant = data.variants[currentVariantKey];
  const url = downloadUrl(
    currentEdition,
    currentEdition === "rust" ? rustRelease : publishedVersion,
    osName,
    currentVariantKey,
  );

  document.getElementById("main-download-version").textContent =
    currentEdition === "rust" ? `v${rustRelease.version}` : currentVersion;
  document.getElementById("main-variant").textContent = variant.label;
  document.getElementById("main-size").textContent =
    currentEdition === "rust" && !rustRelease.published ? "" : variant.size;
  renderVariantPicker(osName);
  renderRequirements(osName);
  renderPackageHelp(osName);

  const mainBtn = document.getElementById("main-download-btn");
  mainBtn.disabled = !url;
  document.getElementById("download-action").textContent = url
    ? getMessages().downloadFor.replace("{os}", data.name)
    : getMessages().unavailable;
  document.getElementById("download-arrow").toggleAttribute("hidden", !url);
  document.querySelectorAll(".os-button").forEach((button) => {
    const active = button.dataset.os === osName;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
    button.querySelector(".os-recommendation").hidden =
      button.dataset.os !== recommendedOsName;
    button.setAttribute(
      "aria-label",
      button.dataset.os === recommendedOsName
        ? `${button.dataset.os} ${getMessages().recommended.replace("✓ ", "")}`
        : button.dataset.os,
    );
  });
  mainBtn.onclick = url
    ? () => {
        window.location.href = url;
      }
    : null;
  const releaseDetails = document.getElementById("release-details");
  releaseDetails.hidden = !url;
  releaseDetails.href = url
    ? `https://github.com/youtube-at-vach/MeasureLab/releases/tag/${currentEdition === "rust" ? `v${rustRelease.version}` : currentVersion}`
    : "";
}

function setLanguage(lang, osName, requestedVariantKey = null) {
  currentLang = SUPPORTED_LANGS.includes(lang) ? lang : "en";
  syncLanguageQuery(currentLang);
  applyStaticTranslations();
  updateMainDisplay(osName, requestedVariantKey ?? currentVariantKey);
}

document.addEventListener("DOMContentLoaded", async () => {
  currentLang = detectLanguage();
  currentEdition =
    new URLSearchParams(window.location.search).get("edition") === "rust"
      ? "rust"
      : "python";
  currentOsName = detectOS();
  applyStaticTranslations();
  updateMainDisplay(currentOsName);

  // Edition, language and platform controls remain responsive while metadata loads.
  function selectEdition(edition) {
    currentEdition = edition;
    variantSelectedByUser = false;
    const url = new URL(window.location.href);
    url.searchParams.set("edition", currentEdition);
    window.history.replaceState({}, "", url);
    applyStaticTranslations();
    updateMainDisplay(currentOsName);
  }
  document.querySelectorAll(".edition-btn").forEach((button) => {
    button.addEventListener("click", () =>
      selectEdition(button.dataset.edition),
    );
  });
  document
    .getElementById("hero-download-link")
    .addEventListener("click", () => {
      // A download CTA always leads to an available edition, even from a Rust preview URL.
      selectEdition(rustRelease.published ? "rust" : "python");
    });
  document.querySelectorAll(".os-button").forEach((button) => {
    button.addEventListener("click", () => {
      variantSelectedByUser = false;
      updateMainDisplay(button.dataset.os);
    });
  });
  document.querySelectorAll(".lang-btn").forEach((button) => {
    button.addEventListener("click", () => {
      setLanguage(button.dataset.lang, currentOsName, currentVariantKey);
    });
  });

  [currentVersion, rustRelease, windowsInstallerAvailable] = await Promise.all([
    loadVersionTag(),
    loadRustRelease(
      new URL("../rust-release.json", window.location.href),
      plannedRustRelease,
    ),
    hasWindowsInstaller(FALLBACK_VERSION),
  ]);
  applyStaticTranslations();
  updateMainDisplay(
    currentOsName,
    variantSelectedByUser ? currentVariantKey : null,
  );
});
