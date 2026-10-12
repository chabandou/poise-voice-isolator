import { StrictMode } from 'react'
import { createRoot, hydrateRoot } from 'react-dom/client'
// Self-hosted fonts (bundled; no third-party requests). Inter and JetBrains
// Mono are variable fonts; headings only use Rajdhani Bold.
import '@fontsource-variable/inter'
import '@fontsource-variable/jetbrains-mono'
import '@fontsource/rajdhani/700.css'
import './index.css'
import App from './App.tsx'
import { applyTheme, getTheme } from './themes'

// index.html restores the saved theme before paint; sync theme-color too.
applyTheme(getTheme())

const app = (
  <StrictMode>
    <App />
  </StrictMode>
)
const root = document.getElementById('root')!

// Production builds ship prerendered HTML (scripts/prerender.mjs), which
// React adopts in place; the dev server serves an empty root.
if (root.firstElementChild) {
  hydrateRoot(root, app)
} else {
  createRoot(root).render(app)
}
