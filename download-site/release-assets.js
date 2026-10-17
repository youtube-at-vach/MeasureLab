export const RELEASE_BASE_URL =
  "https://github.com/youtube-at-vach/MeasureLab/releases/download";

// Keep filenames independent of translated labels. Python's final packages and
// the Rust packages intentionally use different Intel Mac / Windows ZIP names.
export const DOWNLOADS = {
  python: {
    macOS: { arm64: "macos-arm64.dmg", x64: "macos-x64.dmg" },
    Windows: { installer: "windows-x64-setup.exe", onedir: "windows-x64-onedir.zip" },
    Linux: { appimage: "linux-x86_64.AppImage" },
  },
  rust: {
    macOS: { arm64: "macos-arm64.dmg", x86_64: "macos-x86_64.dmg" },
    Windows: { installer: "windows-x64-setup.exe", zip: "windows-x64.zip" },
    Linux: { appimage: "linux-x86_64.AppImage", targz: "linux-x86_64.tar.gz" },
  },
};

export function validRustRelease(release) {
  const match = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?$/.exec(release?.version);
  return release?.schema_version === 1 && typeof release.published === "boolean" && typeof release.version === "string"
    && Boolean(match && (Number(match[1]) > 0 || Number(match[2]) >= 10));
}

export function downloadUrl(edition, release, osName, variant) {
  if (!Object.hasOwn(DOWNLOADS, edition) || !Object.hasOwn(DOWNLOADS[edition], osName)
    || !Object.hasOwn(DOWNLOADS[edition][osName], variant)) return null;
  const suffix = DOWNLOADS[edition]?.[osName]?.[variant];
  if (!suffix) return null;
  if (edition === "rust" && (!validRustRelease(release) || !release.published)) return null;
  if (edition === "python" && release?.version !== "0.9.1") return null;
  const tag = `v${release.version}`;
  return `${RELEASE_BASE_URL}/${tag}/MeasureLab-${tag}-${suffix}`;
}

export async function loadRustRelease(url, fallback, fetchRelease = fetch) {
  try {
    const response = await fetchRelease(url, { cache: "no-cache", signal: AbortSignal.timeout(5000) });
    if (!response.ok) throw new Error("Rust release metadata unavailable");
    const release = await response.json();
    if (!validRustRelease(release)) throw new Error("Invalid Rust release metadata");
    return release;
  } catch {
    // Never enable an unpublished, withdrawn or unknown release from cached JS.
    return { ...fallback, published: false };
  }
}

export function windowsInstallerName(versionTag) {
  return `MeasureLab-${versionTag}-windows-x64-setup.exe`;
}

// The website can deploy before the first installer release. Only offer Setup
// when GitHub confirms that the selected release actually contains it.
export async function hasWindowsInstaller(versionTag, fetchRelease = fetch) {
  try {
    const response = await fetchRelease(
      `https://api.github.com/repos/youtube-at-vach/MeasureLab/releases/tags/${encodeURIComponent(versionTag)}`,
      { signal: AbortSignal.timeout(5000) },
    );
    if (!response.ok) return false;
    const release = await response.json();
    return Array.isArray(release.assets) && release.assets.some(
      (asset) => asset.name === windowsInstallerName(versionTag),
    );
  } catch {
    // Offline, timeout, and API rate limits keep the existing ZIP downloads.
    return false;
  }
}
