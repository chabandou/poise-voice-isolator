// Renders the README's file tree image (.github/media/file-tree.png) with
// headless Chromium. Edit COLS when files move, then: node docs/scripts/render-file-tree.mjs
// (CHROME=/path/to/chrome to pick the browser; fonts load from Google Fonts).
import { execFileSync } from 'node:child_process'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const OUT = fileURLToPath(new URL('../../.github/media/file-tree.png', import.meta.url))
const WIDTH = 1120
// shortcut: fixed page height, bump it when a column grows past the bottom edge.
const HEIGHT = 1520
const ACCENT = '#5fd5eb'

// Each row is "prefix|name|tag|kind": tag = signal-path stop (01-05), kind d = folder,
// n = a wrapped list of names, s = spacer.
const COLS = [
  { title: 'Root & core', rows: [
    '|poise-voice-isolator/||d',
    '├─ |run_poise_gui.py|01|',
    '├─ |poise_tui.py|01|',
    '├─ |run_denoiser.py|01|',
    '├─ |build-linux.sh||',
    '├─ |poise_windows.spec||',
    '├─ |setup.iss||',
    '├─ |pyproject.toml · requirements.txt||',
    '└─ |stream_denoiser/||d',
    '   ├─ |__main__.py|01|',
    '   ├─ |cli.py|01|',
    '   ├─ |audio_host.py|02|',
    '   ├─ |session.py|02|',
    '   ├─ |audio_gc.py|02|',
    '   ├─ |backend_detection.py|03|',
    '   ├─ |device_utils.py|03|',
    '   ├─ |sync.py|03|',
    '   ├─ |processor.py|04|',
    '   ├─ |resampler.py|04|',
    '   ├─ |aad.py|04|',
    '   ├─ |constants.py||',
    '   ├─ |platform_utils.py||',
    '   ├─ |health.py||',
    '   ├─ |logging_config.py||',
    '   └─ |updates.py||',
  ] },
  { title: 'Signal', rows: [
    '|stream_denoiser/||d',
    '├─ |backends/||d',
    '│  ├─ |choice.py|03|',
    '│  ├─ |pipewire_backend.py|03|',
    '│  ├─ |pipewire_node.py|03|',
    '│  ├─ |wasapi_backend.py|03|',
    '│  ├─ |wasapi_node.py|03|',
    '│  ├─ |delay_core.py|03|',
    '│  ├─ |node_loop.py|03|',
    '│  ├─ |pulse_backend.py|03|',
    '│  ├─ |pulse_simple.py|03|',
    '│  ├─ |sounddevice_backend.py|03|',
    '│  ├─ |_loop_util.py|03|',
    '│  └─ |platform/  linux · windows|03|',
    '├─ |engines/||d',
    '│  ├─ |base.py|05|',
    '│  ├─ |availability.py|05|',
    '│  ├─ |onnx_model.py|05|',
    '│  ├─ |deepfilternet3.py|05|',
    '│  ├─ |gtcrn.py|05|',
    '│  ├─ |rnnoise.py|05|',
    '│  └─ |rnnoise_lib.py|05|',
    '├─ |models/||d',
    '│  ├─ |denoiser_model_df3.onnx|05|',
    '│  ├─ |denoiser_model_df3_states.npz|05|',
    '│  └─ |gtcrn.onnx|05|',
    '└─ |native/||d',
    '   ├─ |poise_wasapi.dll|03|',
    '   └─ |rnnoise.dll|05|',
  ] },
  { title: 'Desktop app', rows: [
    '|stream_denoiser/gui/||d',
    '├─ |__main__.py|01|',
    '├─ |main_window.py|01|',
    '├─ |worker.py|02|',
    '├─ |settings.py|01|',
    '├─ |system_tray.py|01|',
    '├─ |titlebar.py|01|',
    '├─ |themes.py|01|',
    '├─ |styles.py|01|',
    '├─ |animations.py|01|',
    '├─ |fonts.py|01|',
    '├─ |cursors.py|01|',
    '├─ |scaling.py|01|',
    '├─ |tooltip.py|01|',
    '├─ |updater.py||',
    '├─ |utils.py||',
    '├─ |widgets/  23 files|01|d',
    '│  |dial · power_button · model_selector · device_selector · home_scene · lattice · sky · sky_gpu · emblem · phosphor · pattern_card · theme_tile · stats_bar · rolling_number · slider · switch · combo · chip · settings_row · sidebar · donate_button · vb_cable_dialog||n',
    '└─ |assets/  52 icons, images, banners||d',
  ] },
  { title: 'Terminal & native', rows: [
    '|stream_denoiser/tui/||d',
    '├─ |__main__.py|01|',
    '├─ |app.py|01|',
    '├─ |settings.py|01|',
    '├─ |palette.py|01|',
    '├─ |font.py|01|',
    '├─ |log_events.py|01|',
    '├─ |styles.tcss|01|',
    '└─ |widgets/  8 files|01|d',
    '   |box · device_list · events_panel · isolation_panel · key_bar · model_picker · signal_panel||n',
    '|||s',
    '|native/||d',
    '├─ |core/||d',
    '│  └─ |poise_core.c · .h|03|',
    '├─ |poise_pw/||d',
    '│  └─ |poise_pw.c · Makefile|03|',
    '├─ |poise_wasapi/||d',
    '│  └─ |poise_wasapi.c · .h · Makefile|03|',
    '└─ |latmeter/||d',
    '   └─ |latmeter.c · Makefile||',
  ] },
  { title: 'Ship', rows: [
    '|installer/||d',
    '├─ |bootstrapper/||d',
    '│  |__main__ · core · engine · pages · window · widgets · chrome · brand||n',
    '├─ |setup_app.py||',
    '├─ |fetch_vbcable.py||',
    '├─ |PoiseSetup.spec||',
    '└─ |windows/vbcable-notice.txt||',
    '|||s',
    '|docs/  Vite + React site||d',
    '├─ |src/  13 files, components/ 15||d',
    '└─ |public/ · scripts/||',
    '|||s',
    '|aur-bin/  PKGBUILD||d',
  ] },
  { title: 'Prove', rows: [
    '|.github/||d',
    '├─ |workflows/||d',
    '│  |build-linux · build-windows · deploy · pulse-ci · windows-frozen||n',
    '└─ |ISSUE_TEMPLATE/ · actions/ · media/||',
    '|||s',
    '|tests/  62 files, pytest||d',
    '|||s',
    '|measurements/||d',
    '├─ |windows-latency.md||',
    '├─ |windows-latency-runs.csv||',
    '└─ |export_runs.py||',
  ] },
]
const STOPS = ['01 Drive', '02 Host', '03 Capture', '04 Prepare', '05 Isolate']

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;')

function row(line) {
  const [pre, name, tag, kind] = line.split('|')
  const note = kind === 'n'
  const h = kind === 's' ? '14px' : note ? '0' : '22px'
  const color = kind === 'd' ? '#f8fafc' : note || !tag ? '#8b94a3' : '#c9d1dc'
  return `<div class="row" style="min-height:${h};font-size:${note ? '11px' : '12.5px'};line-height:${note ? '17px' : '22px'}">`
    + `<span class="pre">${esc(pre)}</span>`
    + `<span style="flex:1 1 auto;min-width:0;color:${color};font-weight:${kind === 'd' ? 600 : 400}">${esc(name)}</span>`
    + `<span class="tag">${tag}</span></div>`
}

const stops = STOPS.map((s, i) => `<span class="dot${i === STOPS.length - 1 ? ' last' : ''}"></span><span>${s}</span>`)
  .join('<span class="line"></span>')
const cols = COLS.map((c) => `<div><div class="col">${esc(c.title)}</div>${c.rows.map(row).join('')}</div>`).join('')

const page = `<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Inter:wght@400;500&family=JetBrains+Mono:wght@400;500;600&display=swap">
<style>
body{margin:0;background:#0a111e;color:#f8fafc;font-family:Inter,system-ui,sans-serif}
main{width:${WIDTH}px;box-sizing:border-box;padding:52px 64px 64px;display:flex;flex-direction:column;gap:40px}
h1{margin:0;font:700 30px/36px Rajdhani,sans-serif;letter-spacing:.02em}h1 span{font-weight:500;color:#8b94a3}
p{margin:4px 0 0;font-size:14px;line-height:20px;color:#8b94a3}
.caps{font:600 13px Rajdhani,sans-serif;letter-spacing:.18em;text-transform:uppercase}
.stops{display:flex;align-items:center;gap:16px;color:${ACCENT}}
.dot{width:12px;height:12px;box-sizing:border-box;border-radius:50%;border:2px solid ${ACCENT};flex:none}.dot.last{background:${ACCENT}}
.line{flex:1 1 0;height:2px;background:#1d2a3b}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:56px 32px;font-family:'JetBrains Mono',ui-monospace,monospace}
.col{padding-bottom:12px;margin-bottom:14px;border-bottom:1px solid #1d2a3b;color:#8b94a3;font:600 13px Rajdhani,sans-serif;letter-spacing:.18em;text-transform:uppercase}
.row{display:flex;align-items:baseline}.pre{flex:none;white-space:pre;color:#34465c}
.tag{flex:none;padding-left:8px;font-size:11px;color:${ACCENT}}
</style></head><body><main>
<div><h1>Poise <span>/ file tree</span></h1>
<p>The repository as it stands on master. Each file is tagged with the stop on the signal path it serves; untagged files support the rest.</p></div>
<div class="stops caps">${stops}</div>
<div class="grid">${cols}</div>
</main></body></html>`

const dir = mkdtempSync(join(tmpdir(), 'poise-tree-'))
const html = join(dir, 'tree.html')
writeFileSync(html, page)
execFileSync(process.env.CHROME ?? 'chromium', [
  '--headless=new', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=2',
  `--window-size=${WIDTH},${HEIGHT}`, '--virtual-time-budget=5000', `--screenshot=${OUT}`, html,
], { stdio: 'ignore' })
console.log(`render-file-tree: wrote ${OUT}`)
