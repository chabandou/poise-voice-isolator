/** Release info injected at build time by vite.config.ts. */
declare const __RELEASE__: {
	version: string | null;
	windowsUrl: string;
};

/** The repo map's file outlines, read from the source at build time (vite.config.ts, scripts/repo-map.mjs). */
declare module 'virtual:repo-map-snippets' {
	const snippets: Record<string, { about: string; lines: Array<Array<[string, string]>> }>;
	export default snippets;
}
