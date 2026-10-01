import './style.css'
import { SearchApp } from './app'
import './chat.ts'

// Initialize SearchApp on the left side
document.addEventListener('DOMContentLoaded', () => {
  const app = new SearchApp()
  app.render()
})

// ChatWidget initializes automatically from chat.ts
