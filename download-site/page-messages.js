// Presentation copy is shared by both editions; release status comes from metadata.
export const pageMessages = {
  ja: {
    navDownload: "ダウンロード",
    navManual: "マニュアル",
    skipLink: "ダウンロードへ移動",
    heroTitle: "オーディオ信号の",
    heroAccent: "測定と解析",
    heroIntro: "波形と周波数成分を、ひとつの環境で。",
    heroBody:
      "MeasureLabは、PCのオーディオ入力を使って信号を観測・解析する、オープンソースのソフトウェアです。",
    heroAction: "Python v0.9.1 をダウンロード",
    heroRustAction: "Rust {version} をダウンロード",
    pythonAvailable: "公開中・最終版",
    rustAvailable: "公開中・プロトタイプ",
    heroSecondary: "Rust版の概要",
    preparing: "Rust版は公開準備中",
    available: "Rustプロトタイプ公開中",
    previews: {
      python: {
        title: "Python版・画面紹介",
        note: "Python最終版のREADME掲載バナー",
        alt: "Python版MeasureLabの複数の測定画面を掲載した旧READMEのバナー",
      },
      rust: {
        title: "Rust版・開発画面",
        note: "Scope / Spectrum · 内部テスト信号",
        alt: "内部テスト信号をScopeとSpectrumに表示したRust版の開発画面",
      },
    },
    resourcesLabel: "資料・プロジェクト情報",
    resourceManual: "マニュアル",
    resourceManualBody: "操作方法、測定条件、既知の制限を確認できます。",
    resourceReleases: "リリース情報",
    resourceReleasesBody: "配布ファイルと変更内容をGitHubで公開しています。",
    resourceSourceBody: "ソースコード、開発状況、不具合の報告先。",
    editionLabel: "エディション",
    platformLabel: "プラットフォーム",
    formatLabel: "CPU・パッケージ",
    recommended: "この端末",
    packageHelp: "パッケージの選び方",
    packageHelpData: {
      macOS:
        "メニュー →「このMacについて」で確認できます。「チップ」がApple Mシリーズなら Apple Silicon、「プロセッサ」がIntelなら Intel を選んでください。",
      Windows:
        "通常はインストーラーを選んでください。インストールせずに使う場合は、ZIP版を展開して起動します。いずれもx64向けです。",
      Linux:
        "AppImageに実行権限を付けて起動してください。x86_64向けのパッケージです。",
    },
    windowsZipHelp:
      "ZIP版を展開し、MeasureLab.exeを起動してください。Windows x64向けのパッケージです。",
    linuxRustHelp:
      "通常はAppImageを選んで実行権限を付けてください。FUSEが使えない場合はtar.gzを展開し、MeasureLab/AppRunを起動します。いずれもx86_64向けです。",
    footerLinks: "関連リンク",
    downloadFor: "{os}版をダウンロード",
    unavailable: "公開準備中",
    requirementsTitle: "動作環境と初回起動について",
    legacyNotice: "Python最終版 v0.9.1 をダウンロードします。",
    rustNotice: "Rust版は準備中です。バイナリはまだ公開していません。",
    rustExperimental:
      "プロトタイプでは、Generator・Lock-in・同期2ch比較は実験段階です。",
    sourceLink: "ソースコード",
    languageLabel: "表示言語",
  },
  en: {
    navDownload: "Download",
    navManual: "Manual",
    skipLink: "Skip to downloads",
    heroTitle: "Audio measurement",
    heroAccent: "and analysis",
    heroIntro: "Waveforms and spectra in one workspace.",
    heroBody:
      "MeasureLab is open-source software for observing and analysing signals from your computer’s audio inputs.",
    heroAction: "Download Python v0.9.1",
    heroRustAction: "Download Rust {version}",
    pythonAvailable: "Available · final edition",
    rustAvailable: "Available · prototype",
    heroSecondary: "Rust edition overview",
    preparing: "Rust edition in preparation",
    available: "Rust prototype available",
    previews: {
      python: {
        title: "Python edition · Overview",
        note: "Banner from the final Python README",
        alt: "Banner from the Python README showing multiple MeasureLab instruments",
      },
      rust: {
        title: "Rust edition · Development screen",
        note: "Scope / Spectrum · Internal test signals",
        alt: "Rust development screen showing Scope and Spectrum with internal test signals",
      },
    },
    resourcesLabel: "Documentation and project information",
    resourceManual: "Documentation",
    resourceManualBody: "Operation, measurement conditions and known limitations.",
    resourceReleases: "Releases",
    resourceReleasesBody: "Distribution files and release notes on GitHub.",
    resourceSourceBody: "Source, development status and issue tracking.",
    editionLabel: "Edition",
    platformLabel: "Platform",
    formatLabel: "CPU & package",
    recommended: "This device",
    packageHelp: "Which package should I choose?",
    packageHelpData: {
      macOS:
        "Open the Apple menu → About This Mac. Choose Apple Silicon if Chip shows an Apple M-series chip, or Intel if Processor shows Intel.",
      Windows:
        "Choose the installer for a standard installation. To use the app without installing it, extract the ZIP package and launch it. Both are for x64.",
      Linux:
        "Make the AppImage executable before launching it. This package is for x86_64.",
    },
    windowsZipHelp:
      "Extract the ZIP package and launch MeasureLab.exe. This package is for Windows x64.",
    linuxRustHelp:
      "Choose AppImage and make it executable. If FUSE is unavailable, extract tar.gz and launch MeasureLab/AppRun. Both are for x86_64.",
    footerLinks: "Explore",
    downloadFor: "Download for {os}",
    unavailable: "In preparation",
    requirementsTitle: "System requirements & first launch",
    legacyNotice: "You’re downloading the final Python edition, v0.9.1.",
    rustNotice:
      "The Rust edition is in preparation. Binaries are not available yet.",
    rustExperimental:
      "Generator, Lock-in and synchronous 2ch comparison are experimental in the prototype.",
    sourceLink: "Source code",
    languageLabel: "Display language",
  },
  zh: {
    navDownload: "下载",
    navManual: "手册",
    skipLink: "跳转至下载",
    heroTitle: "音频信号的",
    heroAccent: "测量与分析",
    heroIntro: "在同一环境中观察波形与频谱。",
    heroBody:
      "MeasureLab 是一款开源软件，可通过电脑的音频输入观察和分析信号。",
    heroAction: "获取 Python v0.9.1",
    heroRustAction: "获取 Rust {version}",
    pythonAvailable: "已发布 · 最终版",
    rustAvailable: "已发布 · 原型",
    heroSecondary: "Rust 版概述",
    preparing: "Rust 版正在准备发布",
    available: "Rust 原型已发布",
    previews: {
      python: {
        title: "Python 版 · 界面概览",
        note: "Python 最终版 README 中的横幅",
        alt: "Python 版旧 README 中展示 MeasureLab 多个测量界面的横幅",
      },
      rust: {
        title: "Rust 版 · 开发画面",
        note: "Scope / Spectrum · 内部测试信号",
        alt: "Rust 版开发画面，使用内部测试信号显示 Scope 和 Spectrum",
      },
    },
    resourcesLabel: "文档与项目信息",
    resourceManual: "使用手册",
    resourceManualBody: "查看操作方法、测量条件及已知限制。",
    resourceReleases: "发布信息",
    resourceReleasesBody: "在 GitHub 上查看软件包及更新内容。",
    resourceSourceBody: "源代码、开发状态及问题反馈。",
    editionLabel: "版本",
    platformLabel: "平台",
    formatLabel: "CPU 与软件包",
    recommended: "当前设备",
    packageHelp: "应该选择哪个软件包？",
    packageHelpData: {
      macOS:
        "打开苹果菜单 →“关于本机”。“芯片”显示 Apple M 系列时请选择 Apple Silicon；“处理器”显示 Intel 时请选择 Intel。",
      Windows:
        "通常请选择安装程序。如需免安装使用，请解压 ZIP 软件包后启动。两种软件包均适用于 x64。",
      Linux: "请先为 AppImage 添加执行权限后再启动。此软件包适用于 x86_64。",
    },
    windowsZipHelp:
      "请解压 ZIP 软件包并启动 MeasureLab.exe。此软件包适用于 Windows x64。",
    linuxRustHelp:
      "通常请选择 AppImage 并添加执行权限。无法使用 FUSE 时，请解压 tar.gz 并启动 MeasureLab/AppRun。两种软件包均适用于 x86_64。",
    footerLinks: "相关链接",
    downloadFor: "下载 {os} 版",
    unavailable: "正在准备发布",
    requirementsTitle: "系统要求与首次启动",
    legacyNotice: "你将下载 Python 最终版本 v0.9.1。",
    rustNotice: "Rust 版正在准备中，尚未提供二进制下载。",
    rustExperimental:
      "原型中的 Generator、Lock-in 和同步双通道比较处于实验阶段。",
    sourceLink: "源代码",
    languageLabel: "显示语言",
  },
};
