import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/vazirmatn'
import App from './App'
import './styles.css'

const root = document.getElementById('root')
if (!root) throw new Error('root element missing from index.html')

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/service-worker.js').catch((cause: unknown) => {
      console.warn('image cache is unavailable; continuing without it', cause)
    })
  })
}
