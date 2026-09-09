import assert from "node:assert/strict";
import test from "node:test";
import { hasWindowsInstaller, windowsInstallerName } from "./release-assets.js";

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
