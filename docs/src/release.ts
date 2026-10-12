export const REPO_URL = 'https://github.com/chabandou/poise-voice-isolator';
export const RELEASES_URL = `${REPO_URL}/releases`;
export const ISSUES_URL = `${REPO_URL}/issues`;

// Baked in at build time by vite.config.ts (fetchRelease): no request to
// GitHub from visitors' browsers. The deploy workflow rebuilds after each
// release build and daily, so it stays current.
export const RELEASE = __RELEASE__;
