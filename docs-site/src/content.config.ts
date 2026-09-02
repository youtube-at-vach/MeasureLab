import { defineCollection } from 'astro:content';
import { docsLoader, i18nLoader } from '@astrojs/starlight/loaders';
import { docsSchema, i18nSchema } from '@astrojs/starlight/schema';

const generateDocumentationId = ({ entry }: { entry: string }) =>
  entry
    .replace(/\.(?:markdown|mdown|mkdn|mkd|mdwn|md|mdx)$/i, '')
    .replace(/\/index$/, '');

export const collections = {
  docs: defineCollection({
    loader: docsLoader({ generateId: generateDocumentationId }),
    schema: docsSchema(),
  }),
  i18n: defineCollection({ loader: i18nLoader(), schema: i18nSchema() }),
};
