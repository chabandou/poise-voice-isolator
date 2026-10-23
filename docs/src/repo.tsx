import { StrictMode } from 'react'
import { createRoot, hydrateRoot } from 'react-dom/client'
// The repo map page (repo/index.html); fonts and styles as in main.tsx.
import '@fontsource-variable/inter'
import '@fontsource/rajdhani/600.css'
import '@fontsource/rajdhani/700.css'
import 'lenis/dist/lenis.css'
import './index.css'
import RepoPage from './RepoPage.tsx'
import { applyTheme, getTheme } from './themes'

applyTheme(getTheme())

const page = (
  <StrictMode>
    <RepoPage />
  </StrictMode>
)
const root = document.getElementById('root')!

if (root.firstElementChild) {
  hydrateRoot(root, page)
} else {
  createRoot(root).render(page)
}
