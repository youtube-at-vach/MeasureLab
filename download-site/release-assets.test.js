import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { DOWNLOADS, downloadUrl, hasWindowsInstaller, loadRustRelease, validRustRelease, windowsInstallerName } from "./release-assets.js";
import { rustMessages } from "./rust-messages.js";

test("offers only the installer belonging to the selected release", async () => {
  const fetchRelease = async (url) => {
    assert.ok(url.endsWith("/tags/v0.8.8"));
    return { ok: true, json: async () => ({ assets: [
      { name: windowsInstallerName("v0.8.8") },
    ] }) };
  };
  assert.equal(await hasWindowsInstaller("v0.8.8", fetchRelease), true);
  const oldRelease = async () => ({ ok: true, json: async () => ({ assets: [
    { name: windowsInstallerName("v0.8.8") },
    { name: "MeasureLab-v0.8.7-windows-x64-onedir.zip" },
  ] }) });
  assert.equal(await hasWindowsInstaller("v0.8.7", oldRelease), false);
});

test("retains ZIP downloads for old releases and unavailable release metadata", async () => {
  for (const fetchRelease of [
    async () => ({ ok: false }),
    async () => ({ ok: true, json: async () => ({ assets: [] }) }),
    async () => ({ ok: true, json: async () => ({}) }),
    async () => { throw new Error("Network unavailable"); },
  ]) {
    assert.equal(await hasWindowsInstaller("v0.8.7", fetchRelease), false);
  }
});

// Verify the user-visible matrix, including the Python/Rust naming differences.
const pythonRelease = JSON.parse(await readFile(new URL("../version.json", import.meta.url)));
const rustRelease = JSON.parse(await readFile(new URL("../rust-release.json", import.meta.url)));

test("preserves every final Python download independently of Rust publication", () => {
  assert.equal(pythonRelease.version, "0.9.1");
  const expected = [
    ["macOS", "arm64", "macos-arm64.dmg"],
    ["macOS", "x64", "macos-x64.dmg"],
    ["Windows", "installer", "windows-x64-setup.exe"],
    ["Windows", "onedir", "windows-x64-onedir.zip"],
    ["Linux", "appimage", "linux-x86_64.AppImage"],
  ];
  for (const [os, variant, suffix] of expected) {
    assert.equal(downloadUrl("python", pythonRelease, os, variant),
      `https://github.com/youtube-at-vach/MeasureLab/releases/download/v0.9.1/MeasureLab-v0.9.1-${suffix}`);
  }
  assert.equal(downloadUrl("python", { version: "0.10.0" }, "Windows", "onedir"), null);
});

test("selects all six Rust packages at the selected version only after publication", () => {
  const expected = [
    ["macOS", "arm64", "macos-arm64.dmg"],
    ["macOS", "x86_64", "macos-x86_64.dmg"],
    ["Windows", "installer", "windows-x64-setup.exe"],
    ["Windows", "zip", "windows-x64.zip"],
    ["Linux", "appimage", "linux-x86_64.AppImage"],
    ["Linux", "targz", "linux-x86_64.tar.gz"],
  ];
  for (const version of ["0.10.0", "0.10.1-rc.1"]) {
    for (const [os, variant, suffix] of expected) {
      const release = { schema_version: 1, version, published: true };
      assert.equal(downloadUrl("rust", release, os, variant),
        `https://github.com/youtube-at-vach/MeasureLab/releases/download/v${version}/MeasureLab-v${version}-${suffix}`);
      assert.equal(downloadUrl("rust", { ...release, published: false }, os, variant), null);
    }
  }
  for (const [os, variant] of [["macOS", "x64"], ["Windows", "onedir"], ["Linux", "arm64"], ["Unknown", "zip"]]) {
    assert.equal(downloadUrl("rust", { ...rustRelease, published: true }, os, variant), null);
  }
});

test("rejects malformed distribution metadata and unknown editions", () => {
  assert.equal(validRustRelease(rustRelease), true);
  for (const release of [null, {}, { ...rustRelease, schema_version: 2 },
    { ...rustRelease, published: "true" }, { ...rustRelease, version: "../v0.10.0" },
    { ...rustRelease, version: "0.9.1" }, { ...rustRelease, version: "v0.10.0" },
    { ...rustRelease, version: ["0.10.0"] }]) {
    assert.equal(validRustRelease(release), false);
    assert.equal(downloadUrl("rust", release, "macOS", "arm64"), null);
  }
  assert.equal(downloadUrl("unknown", rustRelease, "macOS", "arm64"), null);
  assert.equal(downloadUrl("__proto__", rustRelease, "macOS", "arm64"), null);
});

test("Rust publication state is loaded separately and fails closed on unavailable metadata", async () => {
  const published = { ...rustRelease, published: true };
  const fetchRelease = async (url) => {
    assert.equal(url, "/rust-release.json");
    return { ok: true, json: async () => published };
  };
  assert.deepEqual(await loadRustRelease("/rust-release.json", rustRelease, fetchRelease), published);
  for (const fetchRelease of [
    async () => ({ ok: false }),
    async () => ({ ok: true, json: async () => ({}) }),
    async () => ({ ok: true, json: async () => { throw new Error("Invalid JSON"); } }),
    async () => { throw new Error("Offline, timeout or rate limit"); },
  ]) {
    const result = await loadRustRelease("/rust-release.json", published, fetchRelease);
    assert.equal(result.published, false);
    assert.equal(downloadUrl("rust", result, "Windows", "zip"), null);
    assert.ok(downloadUrl("python", pythonRelease, "Windows", "onedir"));
  }
});

test("every Rust CPU and format has a label and OS guidance in all site languages", () => {
  for (const lang of ["ja", "en", "zh"]) {
    for (const [os, variants] of Object.entries(DOWNLOADS.rust)) {
      assert.ok(rustMessages[lang].requirementData[os].items.length);
      for (const key of Object.keys(variants)) assert.ok(rustMessages[lang].labels[key]);
    }
  }
});
