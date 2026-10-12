import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const BASE = '/poise-voice-isolator/'
const REPO = 'chabandou/poise-voice-isolator'
const RELEASES_URL = `https://github.com/${REPO}/releases`
const WINDOWS_ASSET = 'Poise_Setup.exe'

type ReleaseInfo = {
  /** Tag of the newest stable release, e.g. "v1.1.0". */
  version: string | null
  /** Newest release that ships the Windows installer (or the releases page). */
  windowsUrl: string
}

type GithubRelease = {
  tag_name: string
  draft: boolean
  prerelease: boolean
  assets: Array<{ name: string; browser_download_url: string }>
}

// Release info is fetched once at build time and baked into the page, so
// visitors' browsers never call the GitHub API (60 requests/hour per IP
// unauthenticated, and a third-party request on every visit). In CI the
// workflow's GITHUB_TOKEN lifts the rate limit. A failed fetch never fails
// the build: the page links to the releases page and hides the version.
async function fetchRelease(): Promise<ReleaseInfo> {
  const fallback: ReleaseInfo = { version: null, windowsUrl: `${RELEASES_URL}/latest` }
  try {
    const headers: Record<string, string> = { Accept: 'application/vnd.github+json' }
    if (process.env.GITHUB_TOKEN) {
      headers.Authorization = `Bearer ${process.env.GITHUB_TOKEN}`
    }
    const response = await fetch(`https://api.github.com/repos/${REPO}/releases?per_page=20`, {
      headers,
      signal: AbortSignal.timeout(10_000),
    })
    if (!response.ok) {
      throw new Error(`GitHub API responded ${response.status}`)
    }
    const stable = ((await response.json()) as GithubRelease[]).filter(
      (release) => !release.draft && !release.prerelease,
    )
    // The latest release does not always carry every platform's asset, so
    // link the newest release that actually has the installer.
    const installer = stable
      .flatMap((release) => release.assets)
      .find((asset) => asset.name === WINDOWS_ASSET)
    const info: ReleaseInfo = {
      version: stable.find((release) => /^v?\d/.test(release.tag_name))?.tag_name ?? null,
      windowsUrl: installer?.browser_download_url ?? fallback.windowsUrl,
    }
    console.info(`[release] ${info.version ?? 'no version'}, Windows: ${info.windowsUrl}`)
    return info
  } catch (error) {
    console.warn(`[release] could not fetch release info (${String(error)}); building without it`)
    return fallback
  }
}

// Preload the two fonts visible above the fold (Rajdhani Bold headline,
// Inter body) so they don't swap in late. Only the latin woff2 files;
// other subsets still load on demand through unicode-range.
const preloadFonts = (): Plugin => ({
  name: 'poise-preload-fonts',
  apply: 'build',
  transformIndexHtml: {
    order: 'post',
    handler(_html, context) {
      return Object.keys(context.bundle ?? {})
        .filter((file) => /(rajdhani-latin-700-normal|inter-latin-wght-normal)-[\w-]+\.woff2$/.test(file))
        .map((file) => ({
          tag: 'link',
          attrs: { rel: 'preload', as: 'font', type: 'font/woff2', href: `${BASE}${file}`, crossorigin: '' },
          injectTo: 'head' as const,
        }))
    },
  },
})

// https://vite.dev/config/
export default defineConfig(async () => ({
  base: BASE,
  plugins: [react(), tailwindcss(), preloadFonts()],
  define: {
    __RELEASE__: JSON.stringify(await fetchRelease()),
  },
}))
