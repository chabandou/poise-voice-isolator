// Renders the README's file tree image (.github/media/file-tree.png) with
// headless Chromium, from src/repo-map.json, the same list the site's repo
// map page shows. After editing that list: node docs/scripts/render-file-tree.mjs
// (CHROME=/path/to/chrome to pick the browser; fonts load from Google Fonts).
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const OUT = fileURLToPath(new URL('../../.github/media/file-tree.png', import.meta.url))
const MAP = JSON.parse(readFileSync(new URL('../src/repo-map.json', import.meta.url), 'utf8'))
const CHROME = process.env.CHROME ?? 'chromium'
const WIDTH = 1120
const ACCENT = '#5fd5eb'
// The signal path's stops and their colours, as on the site (index.css --stage-*).
const STAGES = [['Drive', '#f49aa6'], ['Host', '#f5a524'], ['Capture', '#e8d36a'], ['Prepare', '#35e0a8'], ['Isolate', '#5fd5eb']]

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;')
const guides = (trail) => trail.map((last) => (last ? '   ' : '│  ')).join('')

/** The tree as rows; a folded folder (as the site starts it) shows its files as one wrapped line. */
export function treeRows(nodes, depth = 0, trail = []) {
  return nodes.flatMap((node, index) => {
    const last = index === nodes.length - 1
    const pre = guides(trail) + (depth ? (last ? '└─ ' : '├─ ') : '')
    const childTrail = depth ? [...trail, last] : trail
    if (!node.children) {
      const folder = node.name.endsWith('/')
      return [{ pre, name: node.name, aside: folder ? node.desc : '', stage: node.stage, kind: folder ? 'd' : '' }]
    }
    if (node.folded) {
      const stages = new Set(node.children.map((child) => child.stage))
      const names = node.children.map((child) => child.name.replace(/\.(py|c|h)$/, ''))
      return [
        { pre, name: `${node.name}  ${node.children.length} files`, stage: stages.size === 1 ? [...stages][0] : undefined, kind: 'd' },
        { pre: guides(childTrail), name: names.join(' · '), kind: 'n' },
      ]
    }
    return [{ pre, name: node.name, stage: node.stage, kind: 'd' }, ...treeRows(node.children, depth + 1, childTrail)]
  })
}

function row({ pre, name, aside, stage, kind }) {
  const note = kind === 'n'
  const color = kind === 'd' ? '#f8fafc' : note || !stage ? '#8b94a3' : '#c9d1dc'
  // A stop's first letter in its colour.
  const [stop, tint] = stage ? STAGES[stage - 1] : ['', '']
  return `<div class="row" style="min-height:${note ? 0 : 22}px;font-size:${note ? '11px' : '12.5px'};line-height:${note ? '17px' : '22px'}">`
    + `<span class="pre">${esc(pre)}</span>`
    + `<span style="flex:1 1 auto;min-width:0;color:${color};font-weight:${kind === 'd' ? 600 : 400}">${esc(name)}`
    + (aside ? `<span class="aside">  ${esc(aside)}</span>` : '') + '</span>'
    + `<span class="tag" style="color:${tint}">${stop[0] ?? ''}</span></div>`
}

// Roots after the first in a column are set apart, as on the site.
const column = (section) => `<div><div class="col">${esc(section.title)}</div>`
  + section.nodes.map((root, i) => `<div${i ? ' class="root"' : ''}>${treeRows([root]).map(row).join('')}</div>`).join('')
  + '</div>'

const stops = STAGES.map(([name, tint]) => `<span class="dot" style="background:${tint}"></span><span style="color:${tint}">${name}</span>`)
  .join('<span class="line"></span>')

const page = `<!doctype html><html><head><meta charset="utf-8"><title>0</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Inter:wght@400;500&family=JetBrains+Mono:wght@400;500;600&display=swap">
<style>
body{margin:0;background:#0a111e;color:#f8fafc;font-family:Inter,system-ui,sans-serif}
main{width:${WIDTH}px;box-sizing:border-box;padding:52px 64px 64px;display:flex;flex-direction:column;gap:40px}
h1{margin:0;font:700 30px/36px Rajdhani,sans-serif;letter-spacing:.02em}h1 span{font-weight:500;color:#8b94a3}
h1 small{margin-left:12px;font:400 17px Inter,system-ui,sans-serif;letter-spacing:0;color:${ACCENT}}h1 small b{font-weight:400;color:#8b94a3}
h1 svg{vertical-align:-1px;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
p{margin:4px 0 0;font-size:14px;line-height:20px;color:#8b94a3}
.caps{font:600 13px Rajdhani,sans-serif;letter-spacing:.18em;text-transform:uppercase}
.stops{display:flex;align-items:center;gap:16px}
.dot{width:12px;height:12px;border-radius:50%;flex:none}
.line{flex:1 1 0;height:2px;background:#1d2a3b}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:56px 32px;font-family:'JetBrains Mono',ui-monospace,monospace}
.col{padding-bottom:12px;margin-bottom:14px;border-bottom:1px solid #1d2a3b;color:#8b94a3;font:600 13px Rajdhani,sans-serif;letter-spacing:.18em;text-transform:uppercase}
.root{margin-top:14px}
.aside{font:400 12px/22px Inter,system-ui,sans-serif;color:#8b94a3}
.row{display:flex;align-items:baseline}.pre{flex:none;white-space:pre;color:#34465c}
.tag{flex:none;width:14px;margin-left:8px;text-align:center;font-size:11px;font-weight:600}
</style></head><body><main>
<div><h1>Poise <span>/ file tree</span><small><b>·</b> click for the interactive version <svg width="15" height="15" viewBox="0 0 12 12" aria-hidden="true"><path d="M4 2 H10 V8 M10 2 L3 9"></path></svg></small></h1>
<p>The repository as it stands on master. Each file carries the first letter of the stop it serves on the signal path, from noisy input to clean output; untagged files support the rest.</p></div>
<div class="stops caps">${stops}</div>
<div class="grid">${MAP.sections.map(column).join('')}</div>
</main>
<script>document.fonts.ready.then(() => { document.title = document.querySelector('main').offsetHeight })</script>
</body></html>`

if (import.meta.url === `file://${process.argv[1]}`) {
  const html = join(mkdtempSync(join(tmpdir(), 'poise-tree-')), 'tree.html')
  writeFileSync(html, page)
  const chrome = (...args) => execFileSync(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars', '--virtual-time-budget=5000', ...args, html], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] })
  // First pass: the page's height once its fonts are in; then the screenshot at that size.
  const height = Number(/<title>(\d+)<\/title>/.exec(chrome(`--window-size=${WIDTH},800`, '--dump-dom'))?.[1])
  if (!height) throw new Error('render-file-tree: could not measure the page')
  const shot = join(dirname(html), 'tree.png')
  chrome('--force-device-scale-factor=2', `--window-size=${WIDTH},${height}`, `--screenshot=${shot}`)
  // 256 colours keep the text crisp at about a third of the bytes (ImageMagick).
  execFileSync('magick', [shot, '-strip', '-dither', 'None', '-colors', '256', `PNG8:${OUT}`])
  console.log(`render-file-tree: wrote ${OUT} (${WIDTH}x${height}, ${(statSync(OUT).size / 1024).toFixed(0)} kB)`)
}
