// Renders each page to static HTML and writes it into its dist file.
// Runs after `vite build` (client) and `vite build --ssr` (server bundle).
import { readFile, rm, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const OUTLET = '<!--ssr-outlet-->'
const dist = fileURLToPath(new URL('../dist/', import.meta.url))
const serverDir = fileURLToPath(new URL('../dist-ssr/', import.meta.url))

const { render, renderRepo } = await import(new URL('../dist-ssr/entry-server.js', import.meta.url).href)
const pages = [
  ['index.html', render],
  ['repo/index.html', renderRepo],
]

for (const [file, renderPage] of pages) {
  const template = await readFile(`${dist}${file}`, 'utf8')
  if (!template.includes(OUTLET)) {
    throw new Error(`prerender: ${OUTLET} not found in dist/${file}`)
  }
  const html = renderPage()
  await writeFile(`${dist}${file}`, template.replace(OUTLET, html))
  console.log(`prerender: wrote ${(html.length / 1024).toFixed(1)} kB of HTML into dist/${file}`)
}
await rm(serverDir, { recursive: true, force: true })
