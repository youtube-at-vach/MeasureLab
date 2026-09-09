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
