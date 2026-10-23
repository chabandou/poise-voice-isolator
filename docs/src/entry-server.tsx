import { StrictMode } from 'react'
import { renderToString } from 'react-dom/server'
import App from './App.tsx'
import RepoPage from './RepoPage.tsx'

// Used only by scripts/prerender.mjs at build time: each page's HTML is
// rendered once into its dist file so crawlers and link previews see real
// content, and its entry (main.tsx, repo.tsx) hydrates it in the browser.
export const render = () =>
  renderToString(
    <StrictMode>
      <App />
    </StrictMode>,
  )

export const renderRepo = () =>
  renderToString(
    <StrictMode>
      <RepoPage />
    </StrictMode>,
  )
