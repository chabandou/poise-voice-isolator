import { StrictMode } from 'react'
import { renderToString } from 'react-dom/server'
import App from './App.tsx'

// Used only by scripts/prerender.mjs at build time: the page's HTML is
// rendered once into dist/index.html so crawlers and link previews see real
// content, and main.tsx hydrates it in the browser.
export const render = () =>
  renderToString(
    <StrictMode>
      <App />
    </StrictMode>,
  )
