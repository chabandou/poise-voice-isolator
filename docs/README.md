# Poise website

The landing page for Poise Voice Isolator, served from GitHub Pages at
<https://chabandou.github.io/poise-voice-isolator/>.

React 19 + TypeScript, built with Vite and styled with Tailwind CSS v4.
The page is prerendered to static HTML at build time and hydrated in the
browser.

## Commands

Run everything from this `docs/` folder. npm is the package manager
(`package-lock.json` is the only lockfile, and CI runs `npm ci`).

```bash
npm install        # install dependencies
npm run dev        # dev server at http://localhost:5173/poise-voice-isolator/
npm run build      # production build into dist/ (see "Build pipeline")
npm run preview    # serve dist/ locally to check the production build
npm run lint       # ESLint
```

## Deploying

`.github/workflows/deploy.yml` builds and publishes `dist/` to GitHub Pages.
It runs:

- on pushes to `master` that touch `docs/**` or the workflow itself,
- after the **Build Windows installer** or **Build Linux binary** workflow
  succeeds (new releases),
- daily at 05:17 UTC, to pick up releases or assets uploaded by hand,
- manually, from the Actions tab (**Deploy to GitHub Pages → Run workflow**).

GitHub pauses scheduled workflows after 60 days without repository activity;
the other triggers keep working.

## Build pipeline

`npm run build` runs four steps:

1. `tsc -b` type-checks the app and the Vite config.
2. `vite build` builds the client bundle. While loading the config,
   `vite.config.ts` fetches the latest release from the GitHub API once and
   bakes the version and the Windows installer URL into the bundle as
   `__RELEASE__` (read through `src/release.ts`). Visitors' browsers never
   call GitHub. Set `GITHUB_TOKEN` to avoid the 60 requests/hour
   unauthenticated limit (CI passes the workflow token). If the fetch fails,
   the build still succeeds: the version is hidden and the download links
   point at the releases page.
3. `vite build --ssr src/entry-server.tsx` builds a server bundle of the app.
4. `scripts/prerender.mjs` renders the app to HTML, writes it into the
   `<!--ssr-outlet-->` placeholder in `dist/index.html`, and deletes the
   temporary `dist-ssr/` folder.

In the browser, `src/main.tsx` hydrates the prerendered HTML. The dev server
has no prerendered HTML, so there it renders from scratch.

## Layout

```
index.html               page shell: meta tags, pre-paint theme script, SSR outlet
vite.config.ts           build-time release lookup, font preloads
scripts/prerender.mjs    writes the prerendered HTML into dist/index.html
public/                  copied as-is (favicon, social preview image)
src/
  main.tsx               client entry: fonts, styles, hydrate/render
  entry-server.tsx       server entry used by the prerender step
  App.tsx                page sections, in order
  index.css              design tokens, per-theme colours, component classes, animations
  themes.ts              the six colour themes and the shared theme store
  release.ts             repo links and the baked-in release info
  reveal.ts              scroll-triggered entrance animations
  components/            one file per section, plus shared pieces (Brand, Dial, CtaButton)
```

## Things to keep in mind

- **Colours mirror the desktop app.** The tokens in `src/index.css` and the
  theme list in `src/themes.ts` copy `stream_denoiser/gui/themes.py`. When a
  theme changes in the app, update both files to match.
- **Never `@import` a URL in `index.css`.** Firefox-based browsers apply none
  of a stylesheet's rules until every `@import` has loaded, so a slow
  third-party stylesheet leaves the page unthemed. Fonts are self-hosted
  (Fontsource packages imported in `main.tsx`), so nothing needs one.
- **Entrance animations.** Add `{...reveal(delayMs, variant)}` to an element
  to animate it in when it scrolls into view. `useReveal()` marks revealed
  elements with a `data-revealed` attribute, never a class: React rewrites
  `className` on re-render, which would hide the element again. Content is
  only hidden while JavaScript runs (`index.html` adds a `js` class to
  `<html>`), so the prerendered page stays readable without it.
- **Prerendering means no browser APIs during render.** Read `window`,
  `document` or `localStorage` only in effects or event handlers, and make
  the first render identical on server and client. Otherwise hydration
  fails. Values that can legitimately differ (like the footer's year) need
  `suppressHydrationWarning`.
- **The saved theme applies before first paint.** A small script in
  `index.html` reads `localStorage` and sets `data-theme` on `<html>`. Keep
  its list of theme ids in sync with `src/themes.ts`.
