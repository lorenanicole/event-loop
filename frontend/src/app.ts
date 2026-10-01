import { searchEvents, getStats, Event, Stats } from './api'

export class SearchApp {
  private container: HTMLElement
  private stats: Stats | null = null
  private events: Event[] = []
  private isLoading = false
  private selectedKeyword = 'music'
  private selectedTimeframe = 'this weekend'

  constructor() {
    this.container = document.getElementById('app') || document.body
  }

  async render() {
    await this.loadStats()
    this.container.innerHTML = `
      <div class="min-h-screen bg-white flex flex-col">
        ${this.renderMainInterface()}
        <div id="events-container" class="flex-1">
          <!-- Events will be rendered here -->
        </div>
        ${this.renderFooter()}
      </div>
    `
    this.attachEventListeners()
  }

  private renderMainInterface() {
    const keywords = ['music', 'comedy', 'theater', 'sports', 'art', 'food', 'film', 'dance']
    const timeframes = [
      'tonight',
      'this weekend',
      'this week',
      'next week',
      'this month',
      'next month'
    ]

    return `
      <section class="flex-1 flex flex-col justify-center items-center px-4 py-12">
        <div class="max-w-2xl w-full text-center">
          <!-- Main heading -->
          <div class="mb-16">
            <h1 class="text-5xl md:text-6xl font-light text-gray-900 leading-tight">
              I want to find<br>
              <span id="keyword-display" class="font-bold text-primary-600">${this.selectedKeyword}</span>
              events<br>
              <span id="timeframe-display" class="font-bold text-primary-600">${this.selectedTimeframe}</span>
            </h1>
          </div>

          <!-- Event keyword selector -->
          <div class="mb-12">
            <label class="block text-sm text-gray-500 mb-4 uppercase tracking-wide">Choose event type</label>
            <div class="flex flex-wrap gap-3 justify-center">
              ${keywords.map(kw => `
                <button
                  class="keyword-btn px-4 py-2 rounded-full border-2 transition-all ${
                    kw === this.selectedKeyword
                      ? 'border-primary-600 bg-primary-600 text-white'
                      : 'border-gray-300 text-gray-700 hover:border-primary-600'
                  }"
                  data-keyword="${kw}"
                >
                  ${kw}
                </button>
              `).join('')}
            </div>
          </div>

          <!-- Timeframe selector -->
          <div class="mb-16">
            <label class="block text-sm text-gray-500 mb-4 uppercase tracking-wide">When</label>
            <div class="flex flex-wrap gap-3 justify-center">
              ${timeframes.map(tf => `
                <button
                  class="timeframe-btn px-4 py-2 rounded-full border-2 transition-all ${
                    tf === this.selectedTimeframe
                      ? 'border-primary-600 bg-primary-600 text-white'
                      : 'border-gray-300 text-gray-700 hover:border-primary-600'
                  }"
                  data-timeframe="${tf}"
                >
                  ${tf}
                </button>
              `).join('')}
            </div>
          </div>

          <!-- Main action button -->
          <div class="mb-8">
            <button
              id="search-btn"
              class="px-12 py-4 bg-primary-600 text-white text-lg font-semibold rounded-full hover:bg-primary-700 transition-colors shadow-lg hover:shadow-xl transform hover:scale-105"
            >
              ✨ Show me the magic
            </button>
          </div>

          <!-- Stats indicator -->
          ${this.stats ? `
            <div class="text-sm text-gray-500">
              ${this.stats.total_events} events waiting to be discovered
            </div>
          ` : ''}
        </div>
      </section>
    `
  }

  private renderEventsList(events: Event[]) {
    const container = document.getElementById('events-container')
    if (!container) return

    if (events.length === 0) {
      container.innerHTML = `
        <div class="min-h-screen flex items-center justify-center px-4">
          <div class="text-center">
            <p class="text-2xl text-gray-600 mb-4">Hmm, no ${this.selectedKeyword} found ${this.selectedTimeframe}...</p>
            <button
              id="back-btn"
              class="text-primary-600 underline hover:text-primary-700"
            >
              ← Try something else
            </button>
          </div>
        </div>
      `
      document.getElementById('back-btn')?.addEventListener('click', () => this.render())
      return
    }

    container.innerHTML = `
      <div class="container mx-auto px-4 py-8 max-w-6xl">
        <button
          id="back-btn"
          class="mb-8 text-primary-600 underline hover:text-primary-700"
        >
          ← Back to search
        </button>

        <h2 class="text-4xl font-bold text-gray-900 mb-8">
          Found ${events.length} ${this.selectedKeyword} event${events.length !== 1 ? 's' : ''} ${this.selectedTimeframe}
        </h2>

        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          ${events.map(event => this.renderEventCard(event)).join('')}
        </div>
      </div>
    `

    document.getElementById('back-btn')?.addEventListener('click', () => this.render())
  }

  private renderEventCard(event: Event): string {
    const eventDate = new Date(event.date)
    const formattedDate = eventDate.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })

    const categoryColors: Record<string, string> = {
      'music': 'bg-purple-100 text-purple-800',
      'comedy': 'bg-blue-100 text-blue-800',
      'theater': 'bg-red-100 text-red-800',
      'art': 'bg-yellow-100 text-yellow-800',
      'food': 'bg-orange-100 text-orange-800',
      'sports': 'bg-green-100 text-green-800',
      'film': 'bg-indigo-100 text-indigo-800',
    }

    const categoryColor = categoryColors[event.category.toLowerCase()] || 'bg-gray-100 text-gray-800'

    return `
      <a
        href="${event.origination_url}"
        target="_blank"
        rel="noopener noreferrer"
        class="group bg-white rounded-lg border border-gray-200 p-6 hover:shadow-lg transition-all hover:border-primary-600"
      >
        <div class="flex justify-between items-start mb-3">
          <h3 class="font-bold text-lg text-gray-900 group-hover:text-primary-600 flex-1">${this.escapeHtml(event.name)}</h3>
        </div>

        <div class="space-y-3 mb-4">
          <div class="flex items-center text-gray-600 text-sm">
            <span class="mr-2">📅</span>
            <span>${formattedDate}</span>
          </div>

          <div>
            <span class="inline-block px-3 py-1 rounded-full text-xs font-medium ${categoryColor}">
              ${this.escapeHtml(event.category)}
            </span>
          </div>
        </div>

        ${event.details ? `
          <p class="text-gray-600 text-sm line-clamp-2 mb-4">
            ${this.escapeHtml(event.details.substring(0, 150))}
          </p>
        ` : ''}

        <div class="text-primary-600 text-sm font-medium group-hover:underline">
          Learn more →
        </div>
      </a>
    `
  }

  private renderFooter() {
    return `
      <footer class="text-center py-8 text-sm text-gray-400">
        🏙️ forged in the 312, for the 312
      </footer>
    `
  }

  private attachEventListeners() {
    // Keyword buttons
    document.querySelectorAll('.keyword-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        this.selectedKeyword = (e.target as HTMLElement).getAttribute('data-keyword') || 'music'
        this.render()
      })
    })

    // Timeframe buttons
    document.querySelectorAll('.timeframe-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        this.selectedTimeframe = (e.target as HTMLElement).getAttribute('data-timeframe') || 'this weekend'
        this.render()
      })
    })

    // Search button
    document.getElementById('search-btn')?.addEventListener('click', () => {
      this.performSearch()
    })

    // Allow Enter key to trigger search (only in search inputs)
    const keywordInput = document.getElementById('keyword-input')
    if (keywordInput) {
      keywordInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
          this.performSearch()
        }
      })
    }
  }

  private async performSearch() {
    if (this.isLoading) return

    this.isLoading = true
    const query = `${this.selectedKeyword} events ${this.selectedTimeframe}`

    const container = document.getElementById('events-container')
    if (container) {
      container.innerHTML = '<div class="flex items-center justify-center min-h-screen"><p class="text-gray-500 text-lg">✨ Finding magic...</p></div>'
    }

    try {
      this.events = await searchEvents(query, 20)
      this.renderEventsList(this.events)
    } catch (error) {
      if (container) {
        container.innerHTML = '<div class="flex items-center justify-center min-h-screen text-red-600"><p>Oops! Something went wrong. Try again?</p></div>'
      }
    } finally {
      this.isLoading = false
    }
  }

  private async loadStats() {
    try {
      const response = await fetch('/api/search/stats')
      if (response.ok) {
        this.stats = await response.json()
      }
    } catch (error) {
      console.error('Error loading stats:', error)
    }
  }

  private escapeHtml(text: string): string {
    const div = document.createElement('div')
    div.textContent = text
    return div.innerHTML
  }
}
