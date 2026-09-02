import { access, mkdir, readFile, rm } from 'node:fs/promises';
import path from 'node:path';
import { getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs';
import { localExecutable, projectRoot, runCommand, withPreview } from './lib/preview.mjs';

const outputDirectory = path.join(projectRoot, 'dist/pdf');
const pdfAssetsDirectory = path.join(projectRoot, 'pdf');

const editions = [
  {
    localePath: '',
    filename: 'operation_manual_ja',
    contentsName: '目次',
    cover: 'cover-ja.html',
    last: '/MeasureLab/PROPOSED_FEATURES/',
    expectedCoverText: 'オペレーションマニュアル',
  },
  {
    localePath: 'en/',
    filename: 'operation_manual_en',
    contentsName: 'Contents',
    cover: 'cover-en.html',
    last: '/MeasureLab/en/PROPOSED_FEATURES/',
    expectedCoverText: 'Operation Manual',
  },
];

async function validatePdf(edition) {
  const pdfPath = path.join(outputDirectory, `${edition.filename}.pdf`);
  const loadingTask = getDocument({
    data: new Uint8Array(await readFile(pdfPath)),
    verbosity: 0,
  });
  const document = await loadingTask.promise;

  if (document.numPages < 2) {
    throw new Error(`${edition.filename}.pdf has only ${document.numPages} page(s).`);
  }

  const firstPage = await document.getPage(1);
  const viewport = firstPage.getViewport({ scale: 1 });
  if (Math.abs(viewport.width - 595.28) > 2 || Math.abs(viewport.height - 841.89) > 2) {
    throw new Error(
      `${edition.filename}.pdf is not A4 (${viewport.width.toFixed(2)} × ${viewport.height.toFixed(2)} pt).`,
    );
  }

  const outline = await document.getOutline();
  if (!outline?.length) {
    throw new Error(`${edition.filename}.pdf does not contain a PDF outline.`);
  }

  const firstPageText = (await firstPage.getTextContent()).items
    .map((item) => ('str' in item ? item.str : ''))
    .join(' ');
  if (!firstPageText.includes(edition.expectedCoverText)) {
    throw new Error(`${edition.filename}.pdf does not contain the expected cover text.`);
  }

  let internalLinkCount = 0;
  for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
    const page = await document.getPage(pageNumber);
    const annotations = await page.getAnnotations();
    for (const annotation of annotations) {
      if (annotation.dest) internalLinkCount += 1;
      const externalUrl = annotation.url ?? annotation.unsafeUrl;
      if (externalUrl && /(?:localhost|127\.0\.0\.1)/i.test(externalUrl)) {
        throw new Error(`${edition.filename}.pdf contains a local preview link: ${externalUrl}`);
      }
    }
  }

  if (internalLinkCount === 0) {
    throw new Error(`${edition.filename}.pdf does not contain internal link annotations.`);
  }

  console.log(
    `Validated ${edition.filename}.pdf: ${document.numPages} A4 pages, outline and ${internalLinkCount} internal links.`,
  );
  await loadingTask.destroy();
}

await access(path.join(projectRoot, 'dist/index.html'));
await mkdir(outputDirectory, { recursive: true });

for (const edition of editions) {
  await rm(path.join(outputDirectory, `${edition.filename}.pdf`), { force: true });
}

await withPreview(
  async ({ documentationRoot }) => {
    for (const edition of editions) {
      await runCommand(localExecutable('starlight-to-pdf'), [
        `${documentationRoot}${edition.localePath}`,
        '--path',
        outputDirectory,
        '--filename',
        edition.filename,
        '--contents-name',
        edition.contentsName,
        '--contents-links',
        'internal',
        '--last',
        edition.last,
        '--format',
        'A4',
        '--margins',
        '1.5cm 1.4cm 1.8cm 1.6cm',
        '--styles',
        path.join(pdfAssetsDirectory, 'pdf.css'),
        '--preceding-html',
        path.join(pdfAssetsDirectory, edition.cover),
        '--following-html',
        path.join(pdfAssetsDirectory, 'back-cover.html'),
        '--header',
        path.join(pdfAssetsDirectory, 'header.html'),
        '--footer',
        path.join(pdfAssetsDirectory, 'footer.html'),
        '--page-wait-until',
        'networkidle0',
        '--timeout',
        '240000',
        '--print-bg',
        '--pdf-outline',
      ]);
      await validatePdf(edition);
    }
  },
  { port: 4322 },
);
