# MeasureLab documentation

`docs-site/` is the source of truth for the MeasureLab web manual and PDF manuals. It uses Node.js 24 LTS, Astro Starlight, and `starlight-to-pdf`. MkDocs and WeasyPrint are not part of this build.

## Commands

Run commands from this directory after `npm ci`.

- `npm run dev`: start the Starlight development server.
- `npm run build:web`: build the static web manual and Pagefind search index into `dist/`.
- `npm run build:pdf`: generate both PDFs from an existing `dist/` web build.
- `npm run build:all`: build the web manual once, then generate both PDFs.
- `npm run check`: run Astro checks, build the web manual, and crawl links, images, fragments, explicit anchors, and sidebar pagination.

## Content contract

- Japanese source pages live in `src/content/docs/` and are published at `/MeasureLab/`.
- English source pages mirror the same paths under `src/content/docs/en/` and are published at `/MeasureLab/en/`.
- Missing English pages use Starlight's Japanese fallback.
- Cross-page links use the canonical GitHub Pages URL so PDF annotations never point to the local preview server. Same-page fragment links remain relative.
- Write inline math as `$...$` and display math as `$$...$$`. Math is rendered to HTML and MathML during the Astro build; no client-side math JavaScript is used.
- Preserve explicit legacy heading anchors with the `{#anchor}` suffix.

The web output is `dist/`. PDF output is fixed to:

- `dist/pdf/operation_manual_ja.pdf`
- `dist/pdf/operation_manual_en.pdf`

The PDF build serves the existing static output through an isolated local Astro preview, waits for readiness, generates both editions, validates A4 size, outline and link annotations, and always stops the preview.

`starlight-to-pdf` is fixed at `1.4.0` in the lockfile. Its upstream Puppeteer dependency currently produces known audit warnings, so the generator accepts only the trusted local static preview. Upgrade it separately when the upstream project supports a maintained Puppeteer release.
