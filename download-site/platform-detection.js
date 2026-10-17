// Recommend only a desktop platform we can identify; CPU selection stays explicit.
export function detectDesktopOS({
  userAgent = "",
  platform = "",
  maxTouchPoints = 0,
} = {}) {
  if (
    /Android|iPhone|iPad|iPod/i.test(userAgent) ||
    (platform === "MacIntel" && maxTouchPoints > 1)
  )
    return null;
  if (/Macintosh|Mac OS X/i.test(userAgent)) return "macOS";
  if (/Windows/i.test(userAgent)) return "Windows";
  if (/Linux|X11/i.test(userAgent)) return "Linux";
  return null;
}
