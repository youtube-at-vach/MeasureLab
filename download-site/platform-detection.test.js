import test from "node:test";
import assert from "node:assert/strict";
import { detectDesktopOS } from "./platform-detection.js";

test("recommends the detected desktop OS without inferring the Mac CPU", () => {
  assert.equal(
    detectDesktopOS({
      userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    }),
    "macOS",
  );
  assert.equal(
    detectDesktopOS({ userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" }),
    "Windows",
  );
  assert.equal(
    detectDesktopOS({ userAgent: "Mozilla/5.0 (X11; Linux x86_64)" }),
    "Linux",
  );
});

test("does not recommend desktop downloads for mobile devices or unknown platforms", () => {
  for (const userAgent of [
    "Mozilla/5.0 (Linux; Android 14)",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)",
    "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X)",
    "unknown",
  ]) {
    assert.equal(detectDesktopOS({ userAgent }), null);
  }
  assert.equal(
    detectDesktopOS({
      userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
      platform: "MacIntel",
      maxTouchPoints: 5,
    }),
    null,
  );
});
