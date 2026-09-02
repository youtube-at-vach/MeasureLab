import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { check, LinkState } from 'linkinator';
import { projectRoot, withPreview } from './lib/preview.mjs';

const sourceRoot = path.join(projectRoot, 'src/content/docs');

async function countMarkdown(directory, excludeEnglishDirectory = false) {
  let count = 0;
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (excludeEnglishDirectory && entry.isDirectory() && entry.name === 'en') continue;
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) count += await countMarkdown(entryPath);
    else if (entry.name.endsWith('.md')) count += 1;
  }
  return count;
}

async function assertSidebarChain(documentationRoot, localePath) {
  let currentUrl = new URL(localePath, documentationRoot).href;
  const visited = [];

  while (currentUrl) {
    if (visited.includes(currentUrl)) throw new Error(`Sidebar pagination loop at ${currentUrl}`);
    visited.push(currentUrl);
    const response = await fetch(currentUrl);
    if (!response.ok) throw new Error(`Sidebar page returned HTTP ${response.status}: ${currentUrl}`);
    const html = await response.text();
    if (new URL(currentUrl).pathname.endsWith('/PROPOSED_FEATURES/')) break;
    const nextMatch = html.match(/<a href="([^"]+)" rel="next"/);
    currentUrl = nextMatch ? new URL(nextMatch[1], currentUrl).href : '';
  }

  if (visited.length !== 60) {
    throw new Error(`${localePath || 'ja'} sidebar has ${visited.length} pages instead of 60.`);
  }
  if (!new URL(visited.at(-1)).pathname.endsWith('/PROPOSED_FEATURES/')) {
    throw new Error(`${localePath || 'ja'} sidebar does not end at PROPOSED_FEATURES.`);
  }
}

async function assertExplicitAnchors(documentationRoot) {
  const anchors = [
    ['quickstart/', 'starting'],
    ['widget_guide/', 'quick-search-guide'],
    ['en/widget_guide/', 'quick-search-guide'],
    ['appendix/', 'limitations'],
    ['appendix/', 'troubleshooting'],
  ];

  for (const [route, anchor] of anchors) {
    const response = await fetch(new URL(route, documentationRoot));
    const html = await response.text();
    if (!html.includes(`id="${anchor}"`)) {
      throw new Error(`Missing explicit heading anchor #${anchor} on ${route}`);
    }
  }
}

const japaneseCount = await countMarkdown(sourceRoot, true);
const englishCount = await countMarkdown(path.join(sourceRoot, 'en'));
if (japaneseCount !== 63 || englishCount !== 60) {
  throw new Error(`Expected 63 Japanese and 60 English source pages, found ${japaneseCount} and ${englishCount}.`);
}

await withPreview(
  async ({ documentationRoot, origin }) => {
    await assertSidebarChain(documentationRoot, '');
    await assertSidebarChain(documentationRoot, 'en/');
    await assertExplicitAnchors(documentationRoot);

    const result = await check({
      path: documentationRoot,
      recurse: true,
      concurrency: 24,
      timeout: 30_000,
      checkCss: true,
      checkFragments: true,
      redirects: 'error',
      urlRewriteExpressions: [
        {
          pattern: /^https:\/\/youtube-at-vach\.github\.io\/MeasureLab/i,
          replacement: `${origin}/MeasureLab`,
        },
      ],
      linksToSkip: async (link) => new URL(link).origin !== origin,
    });

    const brokenLinks = result.links.filter((link) => link.state === LinkState.BROKEN);
    if (brokenLinks.length > 0) {
      const details = brokenLinks
        .map((link) => `${link.status ?? 'ERR'} ${link.url} (from ${link.parent ?? 'unknown'})`)
        .join('\n');
      throw new Error(`Found ${brokenLinks.length} broken documentation link(s):\n${details}`);
    }

    const sitemap = await readFile(path.join(projectRoot, 'dist/sitemap-0.xml'), 'utf8');
    const sitemapEntries = [...sitemap.matchAll(/<loc>/g)].length;
    if (sitemapEntries !== 126) {
      throw new Error(`Expected 126 localized web routes in the sitemap, found ${sitemapEntries}.`);
    }

    console.log(
      `Validated 123 source pages, two 60-page sidebars, 5 explicit anchors and ${result.links.length} links/assets.`,
    );
  },
  { port: 4323 },
);
