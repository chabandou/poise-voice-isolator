// Renders the app to static HTML and writes it into dist/index.html.
// Runs after `vite build` (client) and `vite build --ssr` (server bundle).
import { readFile, rm, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const OUTLET = '<!--ssr-outlet-->'
const dist = fileURLToPath(new URL('../dist/', import.meta.url))
const serverDir = fileURLToPath(new URL('../dist-ssr/', import.meta.url))

const { render } = await import(new URL('../dist-ssr/entry-server.js', import.meta.url).href)
const template = await readFile(`${dist}index.html`, 'utf8')

if (!template.includes(OUTLET)) {
  throw new Error(`prerender: ${OUTLET} not found in dist/index.html`)
}

const appHtml = render()
await writeFile(`${dist}index.html`, template.replace(OUTLET, appHtml))
await rm(serverDir, { recursive: true, force: true })
console.log(`prerender: wrote ${(appHtml.length / 1024).toFixed(1)} kB of HTML into dist/index.html`)
