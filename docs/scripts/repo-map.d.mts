export type Token = [text: string, kind: string];
export type Snippet = { about: string; lines: Token[][] };

export const KIND: Record<string, string>;
export function buildRepoMap(root: string, map: unknown): { snippets: Record<string, Snippet>; warnings: string[] };
