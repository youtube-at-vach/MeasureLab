# CI/CD and Build System

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/actionlint.yml](../../.github/workflows/actionlint.yml)
- [.github/workflows/build_appimage.yml](../../.github/workflows/build_appimage.yml)
- [.github/workflows/build_macos.yml](../../.github/workflows/build_macos.yml)
- [.github/workflows/build_macos_intel.yml](../../.github/workflows/build_macos_intel.yml)
- [.github/workflows/build_windows.yml](../../.github/workflows/build_windows.yml)
- [.github/workflows/ci.yml](../../.github/workflows/ci.yml)
- [.github/workflows/deploy_docs.yml](../../.github/workflows/deploy_docs.yml)
- [.github/workflows/deploy_download_site.yml](../../.github/workflows/deploy_download_site.yml)
- [.github/workflows/pdf_draft.yml](../../.github/workflows/pdf_draft.yml)
- [.github/workflows/release.yml](../../.github/workflows/release.yml)
- [.github/workflows/scorecard.yml](../../.github/workflows/scorecard.yml)
- [.github/workflows/virustotal.yml](../../.github/workflows/virustotal.yml)

</details>



MeasureLab employs a robust automated pipeline to ensure code quality, multi-platform compatibility, and secure distribution. The system leverages GitHub Actions for Continuous Integration (CI), automated builds for Windows, Linux, and macOS, and a comprehensive release process that includes security auditing and documentation deployment.

## Build Pipeline Overview

The build system is designed to transform the Python source into standalone executables across three major operating systems. It uses `pyinstaller` as the primary engine, supplemented by platform-specific scripts for packaging (e.g., AppImage for Linux, DMG for macOS).

### Platform Build Matrix

| Platform | Target Format | Tooling | Key Features |
| :--- | :--- | :--- | :--- |
| **Windows** | `.exe` (Onefile/Onedir) | PyInstaller, ImageMagick | ICU DLL bundling, ASIO support scripts |
| **Linux** | `.AppImage` | PyInstaller, `build_appimage.sh` | Headless verification via `xvfb-run` |
| **macOS** | `.dmg` | PyInstaller, `create-dmg`, `sips` | Apple Silicon/Intel support, Entitlements |

For detailed information on the packaging logic and platform-specific requirements, see **[Multi-Platform Build Workflows](#7.1)**.

**Sources:**
- `.github/workflows/build_windows.yml:60-93`
- `.github/workflows/build_appimage.yml:64-75`
- `.github/workflows/build_macos.yml:51-120`

---

## Continuous Integration and Quality Assurance

Every pull request and push to the `main` branch triggers a suite of validation tools. This ensures that the code remains maintainable and that the translation system is synchronized.

### Automated Checks
1.  **Linting & Formatting:** `ruff` is used to enforce coding standards `.github/workflows/ci.yml:154-156`.
2.  **Type Checking:** `mypy` validates static types for the core library and GUI `.github/workflows/ci.yml:158-160`.
3.  **Translation Integrity:** A custom script `check_trn_keys.py` ensures that all localized strings are present and correctly formatted `.github/workflows/ci.yml:162-164`.
4.  **Logic Verification:** `pytest` runs the headless test suite `.github/workflows/ci.yml:167-169`.

For details on the CI implementation and the documentation build process, see **[CI, Documentation Deployment, and Release](#7.2)**.

**Sources:**
- `.github/workflows/ci.yml:1-170`
- `scripts/check_trn_keys.py:1-20`

---

## Release and Security Lifecycle

The release process is triggered by version tags (e.g., `v1.0.0`). It aggregates artifacts from all platform builds, generates documentation, and performs security audits.

### Release Asset Flow
The following diagram illustrates how source code is transformed into verified release assets:

```mermaid
graph TD
    "Tag: v*" --> "CI Pipeline"
    subgraph "Build Jobs"
        "CI Pipeline" --> "Win Build"
        "CI Pipeline" --> "Linux Build"
        "CI Pipeline" --> "macOS Build"
    end
    "Win Build" --> "MeasureLab.exe"
    "Linux Build" --> "MeasureLab.AppImage"
    "macOS Build" --> "MeasureLab.dmg"
    
    "MeasureLab.exe" --> "VirusTotal Audit"
    "MeasureLab.AppImage" --> "VirusTotal Audit"
    "MeasureLab.dmg" --> "VirusTotal Audit"
    
    "VirusTotal Audit" --> "GitHub Release"
    "SHA256 Generation" --> "GitHub Release"
    "MkDocs Build" --> "GitHub Pages"
```

### Supply Chain Security
MeasureLab integrates **OpenSSF Scorecard** to monitor supply-chain security `.github/workflows/scorecard.yml:5-23`. Additionally, the `virustotal.yml` workflow automatically scans release binaries and zips, providing transparency regarding false positives often associated with PyInstaller-generated executables `.github/workflows/virustotal.yml:14-140`.

**Sources:**
- `.github/workflows/release.yml:1-114`
- `.github/workflows/virustotal.yml:1-181`
- `.github/workflows/scorecard.yml:1-79`

---

## Documentation and Download Site

The project maintains a dual-purpose web presence via GitHub Pages:
1.  **Technical Manuals:** Built using `mkdocs`, including PDF exports generated by `WeasyPrint` with CJK font support for Japanese and Chinese documentation `.github/workflows/deploy_docs.yml:43-44`.
2.  **Download Portal:** A Vite-based frontend located in `download-site/` that serves the latest version metadata and download links `.github/workflows/deploy_download_site.yml:20-33`.

### Workflow Integration Diagram

```mermaid
graph LR
    subgraph "Documentation Source"
        "docs/*.md"
        "mkdocs.yml"
    end
    
    subgraph "Build Process"
        "mkdocs.yml" --> "mkdocs build"
        "ENABLE_PDF_EXPORT" --> "WeasyPrint"
        "download-site/" --> "npm run build"
    end
    
    "mkdocs build" --> "site/"
    "WeasyPrint" --> "site/pdf/"
    "npm run build" --> "site/download/"
    
    "site/" --> "github-pages deploy"
```

**Sources:**
- `.github/workflows/deploy_docs.yml:35-57`
- `.github/workflows/pdf_draft.yml:45-63`
- `.github/workflows/deploy_download_site.yml:1-34`

---

## Child Pages
*   **[Multi-Platform Build Workflows](#7.1)**: PyInstaller configurations, macOS signing, and AppImage construction.
*   **[CI, Documentation Deployment, and Release](#7.2)**: Linting, type checking, PDF generation, and the VirusTotal auditing process.

---
