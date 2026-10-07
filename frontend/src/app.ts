import { searchEvents, getStats, getFilterCounts, Event, Stats, Neighborhood } from './api'

export class SearchApp {
  private container: HTMLElement
  private stats: Stats | null = null
  private events: Event[] = []
  private categories: Neighborhood[] = []
  private neighborhoods: Neighborhood[] = []
  private isLoading = false
  // Paging state. The page used to show the first 20 of 3,000+ events with no
  // way to reach the rest.
  private static readonly PAGE_SIZE = 20
  private isLoadingMore = false
  private hasMore = true
  private scrollObserver: IntersectionObserver | null = null
  // All three start empty: the page opens on everything that is coming up and
  // the sentence narrows it, rather than putting words in anyone's mouth.
  private selectedKeyword: string | null = null
  private selectedTimeframe: string | null = null
  private selectedNeighborhood: string | null = null

  constructor() {
    this.container = document.getElementById('app') || document.body
  }

  async render() {
    await this.loadFilterCounts()
    await this.loadStats()
    this.container.innerHTML = `
      <div class="min-h-screen bg-white flex flex-col">
        ${this.renderMainInterface()}
        <div id="events-container" class="flex-1">
          <!-- Events will be rendered here -->
        </div>
        <!-- Footer first, then the skyline as a closing band beneath it.
             Layering them put the title block on top of the towers. -->
        ${this.renderFooter()}
        ${this.renderSkyline()}
      </div>
    `
    this.attachEventListeners()
    // The sentence already reads as a complete question, so answer it rather
    // than making someone click to see anything at all.
    this.performSearch()
  }

  /**
   * A six-pointed star, as on the Chicago flag — two overlaid triangles,
   * not the five-pointed star people usually reach for.
   */
  private star(size: number, className: string) {
    return `
      <svg width="${size}" height="${size}" viewBox="0 0 24 24" class="${className}" aria-hidden="true">
        <path fill="currentColor" d="M12 1.5 15 8.1 22.2 8.1 16.3 12 19.1 18.8 12 14.6 4.9 18.8 7.7 12 1.8 8.1 9 8.1Z"/>
      </svg>
    `
  }

  /**
   * The real Chicago skyline, as a silhouette.
   *
   * Towers run roughly south-west to north-east, the way the city reads from
   * the lake, and their heights are to scale against the Sears Tower. Each has
   * the profile it is actually recognized by — the Sears Tower's bundled-tube setbacks
   * and twin antennas, the Board of Trade's Art Deco ziggurat, Aon's plain
   * slab, Two Prudential's chevron, 401 N Wabash's setbacks and spire, the
   * St. Regis's stacked tiers, and the Hancock's taper with its twin masts.
   *
   * Drawn as separate shapes rather than one path so a building can be
   * adjusted without unpicking a wall of coordinates. aria-hidden: it is
   * decoration and carries no information.
   */
  private renderSkyline() {
    // One continuous profile, the way an elevation drawing is cut: buildings
    // share edges instead of floating as separate blocks, and it is drawn as a
    // hairline over a near-flat wash rather than a gradient fill.
    // Every roofline is a segment of this one outline, including the Board of
    // Trade's pyramid, Two Prudential's chevron and the Hancock's taper.
    // Drawing those as separate shapes laid over the silhouette left their
    // bases showing as lines inside the fill.
    const profile = [
      'M0,260 L0,232 L70,232',                               // West Loop low-rise
      'L70,170 L100,170 L100,152 L136,152',                  // 311 S Wacker + crown
      'L136,196 L150,196',
      'L150,156 L172,156 L172,120 L196,120 L196,90 L232,90 L232,126 L252,126', // Sears Tower setbacks
      'L252,190 L264,190',
      'L264,216 L280,216 L280,198 L293,180 L306,198 L306,216 L324,216', // Board of Trade ziggurat
      'L324,240 L378,240',
      'L378,164 L400,164 L400,148 L428,148 L428,176 L448,176', // Franklin Center
      'L448,142 L518,142',                                    // Aon Center slab
      'L518,196 L536,196',
      'L536,184 L563,144 L590,184',                           // Two Prudential chevron
      'L590,246 L648,246',
      'L648,192 L676,192 L676,154 L700,154 L700,120 L742,120', // 401 N Wabash setbacks
      'L742,204 L758,204',
      'L758,200 L774,200 L774,166 L792,166 L792,136 L812,136 L812,200 L832,200', // St. Regis tiers
      'L832,244 L884,244',
      'L896,148 L962,148 L974,244',                           // 875 N Michigan, tapered
      'L980,244 L980,194 L1040,194',                          // 900 N Michigan
      'L1040,220 L1060,220 L1060,208 L1104,208',              // Water Tower Place
      'L1104,246 L1200,246 L1200,260 Z',                      // Gold Coast tailing off
    ].join(' ')

    // Each tower gets an invisible hover target carrying its name, height and
    // year. Hovering lights the building and shows a native tooltip, so the
    // skyline can be read rather than just looked at - and the whole svg
    // carries an aria-label for anyone not using a pointer.
    const towers: [string, number, number, number][] = [
      // label, x, width, top
      ['311 South Wacker Drive · 961 ft · 1990', 70, 66, 152],
      // It is the Sears Tower. It will remain the Sears Tower.
      ['Sears Tower · 1,451 ft · 1973', 146, 110, 30],
      ['Chicago Board of Trade · 605 ft · 1930', 262, 64, 180],
      ['Franklin Center · 1,007 ft · 1989', 376, 74, 148],
      ['Aon Center · 1,136 ft · 1973', 448, 70, 142],
      ['Two Prudential Plaza · 995 ft · 1990', 534, 58, 114],
      // Named by its address, like the other towers here. Chicago refers to
      // buildings this way as a matter of course, and this one has earned it.
      ['401 North Wabash · 1,389 ft · 2009', 646, 98, 62],
      ['St. Regis Chicago · 1,198 ft · 2020', 756, 78, 136],
      ['875 North Michigan (the Hancock) · 1,128 ft · 1969', 882, 94, 78],
      ['900 North Michigan · 871 ft · 1989', 978, 64, 194],
      ['Water Tower Place · 859 ft · 1976', 1050, 56, 208],
    ]
    const label = towers.map(t => t[0].split(' · ')[0]).join(', ')

    return `
      <div class="select-none w-full overflow-hidden">
        <svg viewBox="0 0 1200 260" preserveAspectRatio="none" class="block w-full h-auto"
             role="img" aria-label="The Chicago skyline, left to right: ${label}.">
          <style>
            .sky-hit { fill: #41B6E6; fill-opacity: 0; transition: fill-opacity .18s ease; cursor: help; }
            .sky-hit:hover { fill-opacity: .18; }
          </style>
          <!-- One flat silhouette. Opacity is set on the group rather than per
               shape, so the masts do not darken where they meet a roof - the
               whole city composites as a single tone. -->
          <g fill="#41B6E6" opacity="0.22">
            <path d="${profile}"/>
            <rect x="203.5" y="38" width="2.5" height="54"/>   <!-- Sears Tower antennas -->
            <rect x="221.5" y="30" width="2.5" height="62"/>
            <rect x="561.5" y="114" width="2.5" height="32"/>  <!-- Two Prudential spire -->
            <rect x="719.5" y="62" width="2.5" height="60"/>   <!-- 401 N Wabash spire -->
            <rect x="914.5" y="78" width="2.5" height="72"/>   <!-- Hancock masts -->
            <rect x="944.5" y="78" width="2.5" height="72"/>
          </g>
          <g>
            ${towers.map(([name, x, w, top]) => `
              <rect class="sky-hit" x="${x}" y="${top}" width="${w}" height="${260 - top}">
                <title>${this.escapeHtml(name)}</title>
              </rect>
            `).join('')}
          </g>
        </svg>
      </div>
    `
  }

  /** The three fill-in-the-blank slots, in sentence order. */
  /**
   * Every category label to show on a card, primary first.
   *
   * Cards used to show `category` alone, which reads as a contradiction the
   * moment a filter is on: "Beyond Belief Community Archival Training
   * Workshop" is stored as Arts & Culture *and* Community, so filtering by
   * Community produced a card whose only pill said Arts & Culture. 262 events
   * carry more than one label.
   *
   * Falls back to the single field for rows written before the multi-label
   * column existed, and de-duplicates because the primary is also the first
   * entry of the array.
   */
  private static cardCategories(event: Event): string[] {
    const parents = (event.categories && event.categories.length)
      ? event.categories
      : [event.category]
    // Parents first, because those are the tiles - a card must name the filter
    // that returned it. Then the source's finer labels, which are the ones
    // that actually tell you something: "Arts" is the tile, "Arts & Crafts" is
    // what the afternoon involves.
    const all = [...parents, ...(event.subcategories || [])]
    const seen = new Set<string>()
    return all.filter(label => {
      if (!label) return false
      const key = label.toLowerCase()
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  }

  /**
   * Capitalize a category for display, leaving acronyms and deliberate
   * internal capitals alone - LGBTQ and DJs must survive.
   */
  private static displayCategory(value: string): string {
    const acronyms = new Set(['LGBTQ', 'TV', 'DJ', 'BYOB', 'NYE', 'EDM'])
    return value
      .split(' ')
      .map(word =>
        word
          .split('/')
          .map(part => {
            if (/[A-Z]/.test(part.slice(1))) return part
            if (acronyms.has(part.toUpperCase())) return part.toUpperCase()
            return part.charAt(0).toUpperCase() + part.slice(1).toLowerCase()
          })
          .join('/'),
      )
      .join(' ')
  }

  private slots() {
    const categories = this.categories.length > 0
      ? this.categories
      : ['Music', 'Comedy', 'Theater', 'Sports', 'Arts', 'Food & Drink', 'Film', 'Community']
          .map(name => ({ name, event_count: 0 }))
    return [
      {
        key: 'what',
        label: 'anything',
        value: this.selectedKeyword,
        // The value sent to the API is the stored category, untouched; only
        // the label is capitalized. The backend normalizes case on the way in,
        // so this is a safety net for anything older or from a new source.
        // A count of 0 means the fallback list is in use (the request failed),
        // so no number is shown rather than a misleading zero.
        options: categories.map(c => ({
          value: c.name,
          label: SearchApp.displayCategory(c.name),
          ...(c.event_count ? { count: c.event_count } : {}),
        })),
        clearable: true,
      },
      {
        key: 'when',
        label: 'any time',
        value: this.selectedTimeframe,
        options: ['tonight', 'this weekend', 'this week', 'next week', 'this month', 'next month']
          .map(t => ({ value: t, label: t })),
        clearable: true,
      },
      {
        key: 'where',
        // Names the city plainly in the sentence. The local character here
        // comes from the neighborhoods themselves, not from an accent.
        label: 'anywhere in Chicago',
        value: this.selectedNeighborhood,
        options: this.neighborhoods.map(n => ({ value: n.name, label: n.name, count: n.event_count })),
        clearable: true,
      },
    ]
  }

  private slot(key: string) {
    return this.slots().find(s => s.key === key)!
  }

  /**
   * One fill-in-the-blank. Rendered as a combobox rather than a plain select:
   * opening it shows every option (so the choices are browsable), and typing
   * filters them (so someone who knows what they want is not scrolling).
   */
  private renderSlot(slot: ReturnType<SearchApp['slots']>[number]) {
    const filled = slot.value !== null && slot.value !== undefined
    const display = filled ? slot.value : slot.label
    return `
      <span class="relative inline-block align-baseline" data-combo="${slot.key}">
        <button
          type="button"
          class="combo-trigger group inline-flex items-baseline gap-2 border-b-2 pb-1 transition-colors ${
            filled
              ? 'border-primary-600 text-primary-600 font-bold'
              : 'border-dashed border-gray-300 text-gray-400 font-normal hover:border-primary-600 hover:text-primary-600'
          }"
          data-combo-trigger="${slot.key}"
          aria-haspopup="listbox"
          aria-expanded="false"
        >
          <span data-combo-label>${this.escapeHtml(String(display))}</span>
          <svg class="w-5 h-5 shrink-0 self-center opacity-40 group-hover:opacity-80 transition-opacity" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path d="M6 8l4 4 4-4" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </button>

        <div
          class="combo-panel hidden absolute left-1/2 -translate-x-1/2 top-full mt-3 z-50 w-72 max-w-[90vw] rounded-2xl border border-gray-200 bg-white shadow-xl overflow-hidden text-left"
          data-combo-panel="${slot.key}"
        >
          <div class="p-2 border-b border-gray-100">
            <input
              type="text"
              class="combo-filter w-full px-3 py-2 text-base font-normal text-gray-900 rounded-lg bg-gray-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-primary-500"
              placeholder="Type to filter…"
              data-combo-filter="${slot.key}"
              autocomplete="off"
            />
          </div>
          <ul class="combo-options max-h-64 overflow-y-auto py-1 text-base font-normal" role="listbox" data-combo-list="${slot.key}">
            ${slot.clearable ? this.renderOption(slot.key, '', slot.label, null, slot.value === null) : ''}
            ${slot.options.map(o => this.renderOption(slot.key, o.value, o.label, (o as any).count ?? null, o.value === slot.value)).join('')}
          </ul>
        </div>
      </span>
    `
  }

  private renderOption(slotKey: string, value: string, label: string, count: number | null, selected: boolean) {
    return `
      <li role="option" aria-selected="${selected}" data-combo-label="${this.escapeHtml(label)}">
        <button
          type="button"
          class="combo-option w-full flex items-center justify-between gap-3 px-4 py-2 text-left transition-colors ${
            selected ? 'bg-primary-50 text-primary-700 font-semibold' : 'text-gray-700 hover:bg-gray-50'
          }"
          data-combo-select="${slotKey}"
          data-value="${this.escapeHtml(value)}"
        >
          <span>${this.escapeHtml(label)}</span>
          ${count !== null ? `<span class="text-xs text-gray-400 tabular-nums">${count}</span>` : ''}
        </button>
      </li>
    `
  }

  /**
   * Things people have written about Chicago, for the empty state.
   *
   * Chosen to reflect who actually wrote this city: Brooks and Hansberry from
   * the South Side, Cisneros from the Mexican-American West Side, Addams from
   * Hull-House, alongside the usual Sandburg and Algren.
   *
   * Every quote is sourced to a specific work and year. Burnham's is the one
   * exception - every Chicagoan knows it and nobody can source it, its
   * authenticity having been questioned in the Journal of the AIA as early as
   * 1957 - so it is credited as "attributed to" rather than put in his mouth.
   */
  private static readonly QUOTES: { text: string; who: string; work: string }[] = [
    {
      text: 'We are each other&rsquo;s harvest: we are each other&rsquo;s business: we are each other&rsquo;s magnitude and bond.',
      who: 'Gwendolyn Brooks',
      work: 'Paul Robeson, 1970',
    },
    {
      text: 'There is always something left to love.',
      who: 'Lorraine Hansberry',
      work: 'A Raisin in the Sun, 1959',
    },
    {
      text: 'Like it or not, you are Mango Street, and one day you&rsquo;ll come back too.',
      who: 'Sandra Cisneros',
      work: 'The House on Mango Street, 1984',
    },
    {
      text: 'The good we secure for ourselves is precarious and uncertain until it is secured for all of us.',
      who: 'Jane Addams',
      work: 'Twenty Years at Hull-House, 1910',
    },
    {
      text: 'She is always a novelty; for she is never the Chicago you saw when you passed through the last time.',
      who: 'Mark Twain',
      work: 'Life on the Mississippi, 1883',
    },
    {
      text: 'Once you&rsquo;ve come to be part of this particular patch, you&rsquo;ll never love another.',
      who: 'Nelson Algren',
      work: 'Chicago: City on the Make, 1951',
    },
    {
      text: 'Stormy, husky, brawling, City of the Big Shoulders.',
      who: 'Carl Sandburg',
      work: 'Chicago, 1914',
    },
    {
      text: 'Make no little plans; they have no magic to stir men&rsquo;s blood.',
      who: 'attributed to Daniel Burnham',
      work: 'architect of the 1909 Plan of Chicago',
    },
  ]

  private renderMainInterface() {
    const [what, when, where] = this.slots()
    return `
      <section class="px-4 pt-16 pb-10">
        <div class="max-w-3xl mx-auto text-center">
          <!-- An invitation rather than a transaction. "events" is gone from
               the middle: "Let's explore comedy this weekend in Pilsen" says
               it without the filler, and it still reads when nothing is
               chosen - "Let's explore anything any time anywhere in Chicago". -->
          <h1 class="text-4xl md:text-5xl font-light text-gray-900 leading-[1.6] md:leading-[1.7]">
            <span class="block mb-2">Let&rsquo;s explore</span>
            ${this.renderSlot(what)}
            ${this.renderSlot(when)}
            ${this.selectedNeighborhood ? '<span class="mx-1 text-gray-400 font-light">in</span>' : ''}
            ${this.renderSlot(where)}
          </h1>

          <div class="mt-10 flex items-center justify-center gap-4 text-sm">
            <button id="browse-toggle" class="text-gray-500 hover:text-primary-600 transition-colors inline-flex items-center gap-1.5">
              <svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path d="M3 5h14v2H3V5zm0 4h14v2H3V9zm0 4h9v2H3v-2z"/></svg>
              <span id="browse-toggle-label">Browse everything</span>
            </button>
            ${this.stats ? `<span class="text-gray-300">·</span><span class="text-gray-400">${this.stats.total_events} upcoming events</span>` : ''}
          </div>

          <div id="browse-panel" class="hidden mt-8 text-left">
            ${this.renderBrowseGroup('what', 'Event type', what.options, what.value, what.label)}
            ${this.renderBrowseGroup('where', 'Neighborhood', where.options, where.value, where.label)}
          </div>
        </div>
      </section>
    `
  }

  /** The full tag grid, for scanning everything at once rather than filtering. */
  private renderBrowseGroup(
    slotKey: string,
    heading: string,
    options: { value: string; label: string; count?: number }[],
    selected: string | null,
    // The slot's own wording for "no filter" - "anything" for event type,
    // "anywhere in Chicago" for neighborhood - so the pill reads the same way
    // the sentence above does. Previously hardcoded to "anywhere", which is
    // why event type had no way to clear itself at all.
    clearLabel?: string,
  ) {
    // "anywhere in Chicago" is the sentence's phrasing; as a pill among
    // neighborhoods the city name is redundant.
    const clearText = clearLabel?.replace(/ in Chicago$/, '')
    return `
      <div class="mb-8">
        <h2 class="text-xs text-gray-400 mb-3 uppercase tracking-wider">${heading}</h2>
        <div class="flex flex-wrap gap-2">
          ${clearText ? `
            <button class="browse-tag px-3 py-1.5 rounded-full text-sm border transition-all ${
              selected === null
                ? 'border-primary-600 bg-primary-600 text-white'
                : 'border-gray-200 text-gray-600 hover:border-primary-600'
            }" data-combo-select="${slotKey}" data-value="">${this.escapeHtml(clearText)}</button>
          ` : ''}
          ${options.map(o => `
            <button
              class="browse-tag px-3 py-1.5 rounded-full text-sm border transition-all ${
                o.value === selected
                  ? 'border-primary-600 bg-primary-600 text-white'
                  : 'border-gray-200 text-gray-600 hover:border-primary-600'
              }"
              data-combo-select="${slotKey}"
              data-value="${this.escapeHtml(o.value)}"
            >${this.escapeHtml(o.label)}${o.count !== undefined ? `<span class="ml-1.5 text-xs opacity-60 tabular-nums">${o.count}</span>` : ''}</button>
          `).join('')}
        </div>
      </div>
    `
  }

  private renderEventsList(events: Event[]) {
    const container = document.getElementById('events-container')
    if (!container) return

    if (events.length === 0) {
      // No dead end and no back button: the sentence above is still there to
      // edit. A different quote each time turns the empty result into a nudge
      // to go looking somewhere else in the city.
      const where = this.selectedNeighborhood ? ` in ${this.escapeHtml(this.selectedNeighborhood)}` : ''
      const quotes = SearchApp.QUOTES
      const quote = quotes[Math.floor(Math.random() * quotes.length)]
      container.innerHTML = `
        <div class="flex items-center justify-center px-4 py-20">
          <div class="text-center max-w-xl">
            <p class="text-xl text-gray-600">
              Nothing${this.selectedTimeframe ? ' ' + this.escapeHtml(this.selectedTimeframe) : ' coming up'}${where}.
            </p>
            <p class="mt-1 text-gray-400">Change the sentence above to look somewhere else.</p>

            <div class="mt-10 flex items-center justify-center gap-2 text-chicago-red">
              ${this.star(11, '').repeat(4)}
            </div>
            <blockquote class="mt-5">
              <p class="text-lg md:text-xl text-gray-700 leading-relaxed">&ldquo;${quote.text}&rdquo;</p>
              <footer class="mt-3 text-sm text-gray-400">
                ${quote.who}<span class="mx-1.5 text-gray-300">&middot;</span><cite class="not-italic">${quote.work}</cite>
              </footer>
            </blockquote>
          </div>
        </div>
      `
      return
    }

    container.innerHTML = `
      <div class="container mx-auto px-4 pb-8 max-w-6xl">
        <h2 class="text-center text-sm uppercase tracking-wider text-gray-400 mb-6">
          ${events.length} ${this.selectedKeyword ? this.escapeHtml(this.selectedKeyword) + ' ' : ''}event${events.length !== 1 ? 's' : ''}${
            this.selectedTimeframe ? ' ' + this.escapeHtml(this.selectedTimeframe) : ' coming up'
          }${this.selectedNeighborhood ? ` in ${this.escapeHtml(this.selectedNeighborhood)}` : ''}
        </h2>

        <div id="events-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          ${events.map(event => this.renderEventCard(event)).join('')}
        </div>
        <!-- Watched by an IntersectionObserver: scrolling it into view loads
             the next page. A button would work too, but the list is for
             browsing and stopping to click breaks that. -->
        <div id="events-sentinel" class="h-12 flex items-center justify-center">
          ${this.hasMore ? '<span id="events-loading-more" class="hidden text-gray-400 text-sm">Looping in more…</span>' : ''}
        </div>
      </div>
    `

  }

  /**
   * Format an event's date for display.
   *
   * Multi-day events show as a range ("Oct 22 – Dec 6"), with "Through <end>"
   * once the run is already under way. Single-day events show the published
   * start time, which lives in `time` - the `date` column is stored at
   * midnight, so reading the clock off it would print "12:00 AM" for everything.
   */
  private formatEventDate(event: Event): string {
    const dayMonth: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' }
    const start = new Date(event.date)
    const startLabel = start.toLocaleDateString('en-US', dayMonth)

    if (event.date_end) {
      const end = new Date(event.date_end)
      const endLabel = end.toLocaleDateString('en-US', dayMonth)
      if (endLabel !== startLabel) {
        const today = new Date()
        today.setHours(0, 0, 0, 0)
        return start < today ? `Through ${endLabel}` : `${startLabel} – ${endLabel}`
      }
    }

    return event.time ? `${startLabel} · ${event.time}` : startLabel
  }

  /**
   * Where the event is, as one line.
   *
   * `address` is often prefixed with the venue ("Cole's Bar, 2338 N Milwaukee
   * Ave"), and for some sources it is a sentence scraped out of the blurb
   * rather than a place at all. So: drop the duplicate prefix, and ignore
   * anything that does not look like an address.
   */
  private formatLocation(event: Event): string | null {
    const venue = (event.venue_name || '').trim()
    let address = (event.address || '').trim()

    // Prose gives itself away by length and sentence punctuation.
    const plausible =
      address.length > 0 &&
      address.length <= 90 &&
      address.split(' ').length <= 14 &&
      !/[?!;]/.test(address)
    if (!plausible) address = ''

    if (venue && address) {
      const withoutVenue = address.replace(
        new RegExp(`^${venue.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*,\\s*`, 'i'),
        '',
      )
      return withoutVenue && withoutVenue !== address
        ? `${venue} · ${withoutVenue}`
        : `${venue} · ${address}`
    }
    return venue || address || null
  }

  private renderEventCard(event: Event): string {
    const formattedDate = this.formatEventDate(event)
    const location = this.formatLocation(event)
    const cost = (event.cost || '').trim()

    // One color for every category rather than a per-category rainbow. The
    // old map (purple, yellow, orange, indigo) fought the flag palette, and a
    // category is a label, not a status, so it does not need to be color
    // coded. Red stays reserved for the few real accents - if every card wore
    // it, it would stop reading as an accent at all.
    const categoryColor = 'bg-chicago-blue/15 text-primary-700'

    // Not every event has a page to link to: Google's event cards carry a
    // venue and a date but no URL. Wrapping those in an anchor anyway rendered
    // href="null" - a card that looks clickable and goes nowhere - so the
    // whole card becomes a plain div instead, and the "Learn more" line below
    // is dropped with it.
    const link = event.origination_url
    const tag = link ? 'a' : 'div'
    const linkAttrs = link
      ? `href="${this.escapeHtml(link)}" target="_blank" rel="noopener noreferrer"`
      : ''
    const hoverClasses = link
      ? 'hover:shadow-lg hover:border-primary-600'
      : ''

    return `
      <${tag}
        ${linkAttrs}
        class="group bg-white rounded-lg border border-gray-200 p-6 transition-all ${hoverClasses}"
      >
        <div class="flex justify-between items-start mb-3">
          <h3 class="font-bold text-lg text-gray-900 ${link ? 'group-hover:text-primary-600' : ''} flex-1">${this.escapeHtml(event.name)}</h3>
        </div>

        <div class="space-y-2 mb-4">
          <div class="flex items-start text-gray-600 text-sm">
            <span class="mr-2 shrink-0">📅</span>
            <span>${formattedDate}</span>
          </div>

          ${location ? `
            <div class="flex items-start text-gray-600 text-sm">
              <span class="mr-2 shrink-0">📍</span>
              <span>${this.escapeHtml(location)}</span>
            </div>
          ` : ''}

          <div class="flex flex-wrap items-center gap-2 pt-1">
            ${SearchApp.cardCategories(event).map(label => {
              // A subtag is drawn outlined rather than filled, so the two
              // levels read as a hierarchy instead of as a row of equal
              // claims: "Arts" is the tile this card answers to, "Arts &
              // Crafts" is the detail underneath it.
              const isSubtag = (event.subcategories || []).includes(label)
              const style = isSubtag
                ? 'border border-gray-300 text-gray-600'
                : categoryColor
              return `
                <span class="inline-block px-3 py-1 rounded-full text-xs font-medium ${style}">
                  ${this.escapeHtml(SearchApp.displayCategory(label))}
                </span>
              `
            }).join('')}
            ${cost ? `
              <span class="inline-block px-3 py-1 rounded-full text-xs font-medium ${
                /free/i.test(cost) ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-700'
              }">${this.escapeHtml(cost)}</span>
            ` : ''}
            ${event.age_range ? `
              <span class="inline-block px-3 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-700">
                ${this.escapeHtml(event.age_range)}
              </span>
            ` : ''}
          </div>
        </div>

        ${event.details ? `
          <p class="text-gray-600 text-sm line-clamp-2 mb-4">
            ${this.escapeHtml(event.details.substring(0, 150))}
          </p>
        ` : ''}

        ${link ? `
          <div class="text-primary-600 text-sm font-medium group-hover:underline">
            Learn more →
          </div>
        ` : ''}
      </${tag}>
    `
  }

  /**
   * The tagline as a line of Python that still reads as the sentence:
   * "await EventLoop since 1837, gather every hood".
   * `gather` is the real asyncio call, which is what the scrapers do.
   */
  /**
   * The credit, set as an architectural title block — the ruled box in the
   * corner of a drawing that names the project, the city and who drew it.
   * Chicago invented the skyscraper, so the building trade's own way of
   * signing work felt more apt than a handwriting font.
   *
   * "Tool Maker" is Sandburg's, from the opening line of "Chicago" (1914);
   * the link credits the poem rather than quietly borrowing from it.
   * The year is set in Roman numerals the way a cornerstone would carve it.
   */
  private renderTitleBlock() {
    const year = new Date().getFullYear()
    // A single grid with shared column tracks, so the vertical rule lines up
    // across both rows. Built as two independent flex rows, each row sized its
    // own cells and the divider zig-zagged.
    const label = 'text-[9px] uppercase tracking-[0.16em] text-gray-400 leading-none'
    const cell = 'px-3 py-2.5 min-h-[3.25rem] flex flex-col justify-between'
    return `
      <div class="mt-6 flex justify-center px-4">
        <div class="w-full max-w-[22rem] bg-white/90 backdrop-blur-sm ring-1 ring-gray-300 text-left overflow-hidden">
          <div class="grid grid-cols-[1fr_6.5rem]">
            <div class="${cell} border-b border-r border-gray-200">
              <div class="${label}">Project</div>
              <div class="text-sm font-bold text-gray-800 leading-none">EventLoop</div>
            </div>
            <div class="${cell} border-b border-gray-200">
              <div class="${label}">Location</div>
              <div class="text-sm font-semibold text-gray-700 leading-none">Chicago, Ill.</div>
            </div>

            <div class="${cell} border-r border-gray-200">
              <a
                href="https://en.wikipedia.org/wiki/Chicago_(poem)"
                target="_blank"
                rel="noopener noreferrer"
                title="&ldquo;Hog Butcher for the World, Tool Maker, Stacker of Wheat&hellip;&rdquo; &mdash; Carl Sandburg, &ldquo;Chicago&rdquo; (1914)"
                class="${label} self-start border-b border-dotted border-gray-300 hover:text-chicago-red hover:border-chicago-red transition-colors"
              >Tool Maker</a>
              <a
                href="https://lorenamesa.com"
                target="_blank"
                rel="noopener noreferrer"
                class="text-[15px] font-bold uppercase tracking-[0.1em] text-gray-800 leading-none hover:text-chicago-red transition-colors"
              >Lorena&nbsp;Mesa</a>
            </div>
            <div class="${cell}">
              <div class="${label}">Anno</div>
              <div class="text-sm font-semibold tracking-[0.08em] text-gray-700 leading-none">${this.roman(year)}</div>
            </div>
          </div>

          <div class="h-[3px] bg-chicago-red"></div>
        </div>
      </div>
    `
  }

  /** Roman numerals, for the cornerstone line. */
  private roman(value: number): string {
    const table: [number, string][] = [
      [1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'], [100, 'C'], [90, 'XC'],
      [50, 'L'], [40, 'XL'], [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I'],
    ]
    let out = ''
    for (const [n, numeral] of table) {
      while (value >= n) {
        out += numeral
        value -= n
      }
    }
    return out
  }

  /**
   * Land acknowledgment.
   *
   * Written to the Native Governance Center's guidance: name specific nations,
   * stay in the present tense because colonisation is ongoing rather than
   * historical, say "unceded" where it is true, and point at something
   * actionable instead of stopping at the words. The nations listed are the
   * ones named in the City of Chicago's own acknowledgment.
   *
   * The link goes to the American Indian Center of Chicago - the first urban
   * American Indian center in the United States, founded 1953, and still run
   * by and for the city's Native community.
   */
  private renderLandAcknowledgment() {
    return `
      <aside class="mt-10 mx-auto max-w-2xl px-4">
        <details class="group text-left">
          <summary class="cursor-pointer list-none text-center text-xs uppercase tracking-[0.16em] text-gray-400 hover:text-chicago-red transition-colors">
            <span class="border-b border-dotted border-gray-300 group-hover:border-chicago-red pb-0.5">
              Land acknowledgment
            </span>
          </summary>
          <div class="mt-4 text-sm leading-relaxed text-gray-500 space-y-3">
            <p>
              Chicago stands on the traditional, ancestral and unceded homelands of the
              Council of the Three Fires &mdash; the <strong class="font-semibold text-gray-700">Ojibwe</strong>,
              <strong class="font-semibold text-gray-700">Odawa</strong> and
              <strong class="font-semibold text-gray-700">Potawatomi</strong> Nations &mdash; and of the
              Myaamia, Ho-Chunk, Menominee, Sac and Fox, Peoria, Kaskaskia, Wea, Kickapoo
              and Mascouten peoples.
            </p>
            <p>
              The city carries an Indigenous name: <em>Chicago</em> comes from
              <span class="italic">shikaakwa</span>, the Myaamia word for the wild leeks that
              grew along the river here.
            </p>
            <p>
              Native people are not a chapter of this city&rsquo;s past. Chicago is home to one of
              the largest urban Native communities in the country, and to the
              <a
                href="https://aicchicago.org"
                target="_blank"
                rel="noopener noreferrer"
                class="font-semibold text-gray-700 underline decoration-chicago-red decoration-2 underline-offset-4 hover:text-chicago-red transition-colors"
              >American Indian Center</a>, the first urban American Indian center in the
              United States. Every event listed here takes place on this land.
            </p>
          </div>
        </details>
      </aside>
    `
  }

  /**
   * Copyright and credits.
   *
   * A notice is not required for copyright to exist - that has been automatic
   * in the US since 1989 - but it states the claim plainly and names the
   * licence, which matters here because the repository is MIT: a bare "all
   * rights reserved" would contradict the LICENSE file.
   *
   * The flag needs no permission. Wallace Rice designed it in 1917, so it is
   * long out of copyright, and the bars and stars here are decoration, which
   * is what the municipal code itself carves out.
   */
  private renderColophon() {
    const year = new Date().getFullYear()
    return `
      <div class="mt-10 px-4 text-center text-xs text-gray-400 space-x-1.5">
        <span>&copy; ${year} Lorena Mesa</span>
        <span class="text-gray-300">&middot;</span>
        <a
          href="https://opensource.org/license/mit"
          target="_blank"
          rel="noopener noreferrer"
          class="hover:text-chicago-red transition-colors underline decoration-dotted underline-offset-2"
        >MIT licensed</a>
        <span class="text-gray-300">&middot;</span>
        <span>Event listings belong to the venues and sources they came from</span>
      </div>
    `
  }

  private renderFooter() {
    return `
      <footer class="pt-10 pb-4 text-center">
        <!-- The flag: two light blue bars, four six-pointed red stars. -->
        <div class="flex items-center justify-center gap-3 mb-5">
          <span class="h-[3px] w-14 rounded-full bg-chicago-blue"></span>
          <span class="flex items-center gap-2 text-chicago-red">
            ${this.star(14, '').repeat(4)}
          </span>
          <span class="h-[3px] w-14 rounded-full bg-chicago-blue"></span>
        </div>

        <!-- Sat on its own light panel: the skyline behind it was washing the
             text out, and this is the one place the joke has to be legible. -->
        <div class="inline-block rounded-xl bg-white/85 backdrop-blur-sm px-5 py-3 ring-1 ring-gray-200/70">
          <code class="font-mono text-[13px] text-gray-700 select-all whitespace-nowrap">
            <span class="text-primary-700 font-semibold">await</span> <span class="text-gray-800">EventLoop</span><span class="text-gray-400">(</span>since<span class="text-gray-400">=</span><span class="text-chicago-red font-semibold">1837</span><span class="text-gray-400">)</span>.<span class="text-primary-700 font-semibold">gather</span><span class="text-gray-400">(*</span>every_hood<span class="text-gray-400">)</span>
          </code>
          <p class="mt-1.5 text-xs text-gray-500">one loop, every hood, gather round</p>
        </div>

        ${this.renderTitleBlock()}
        ${this.renderLandAcknowledgment()}
        ${this.renderColophon()}
      </footer>
    `
  }

  private attachEventListeners() {
    // One delegated listener on the container: the madlib re-renders its own
    // pieces, so per-element handlers would go stale on every selection.
    this.container.addEventListener('click', (e) => {
      const target = e.target as HTMLElement

      const trigger = target.closest('[data-combo-trigger]') as HTMLElement | null
      if (trigger) {
        this.toggleCombo(trigger.getAttribute('data-combo-trigger')!)
        return
      }

      const option = target.closest('[data-combo-select]') as HTMLElement | null
      if (option) {
        this.selectOption(
          option.getAttribute('data-combo-select')!,
          option.getAttribute('data-value') || '',
        )
        return
      }

      if (target.closest('#browse-toggle')) {
        this.toggleBrowse()
        return
      }

      // A click anywhere else dismisses an open list.
      if (!target.closest('[data-combo-panel]')) this.closeCombos()
    })

    // Filter as you type, so the list serves both browsing and quick entry.
    this.container.addEventListener('input', (e) => {
      const input = e.target as HTMLElement
      const key = input.getAttribute('data-combo-filter')
      if (key) this.filterOptions(key, (input as HTMLInputElement).value)
    })

    this.container.addEventListener('keydown', (e) => {
      const event = e as KeyboardEvent
      if (event.key === 'Escape') {
        this.closeCombos()
        return
      }
      if (event.key === 'Enter') {
        const key = (event.target as HTMLElement).getAttribute('data-combo-filter')
        if (!key) return
        // Enter takes the first option still visible after filtering.
        const first = this.container.querySelector(
          `[data-combo-list="${key}"] li:not(.hidden) [data-combo-select]`,
        ) as HTMLElement | null
        if (first) {
          event.preventDefault()
          this.selectOption(key, first.getAttribute('data-value') || '')
        }
      }
    })
  }

  private toggleCombo(key: string) {
    const panel = this.container.querySelector(`[data-combo-panel="${key}"]`) as HTMLElement | null
    if (!panel) return
    const willOpen = panel.classList.contains('hidden')
    this.closeCombos()
    if (!willOpen) return

    panel.classList.remove('hidden')
    this.container
      .querySelector(`[data-combo-trigger="${key}"]`)
      ?.setAttribute('aria-expanded', 'true')
    const filter = panel.querySelector('input') as HTMLInputElement | null
    if (filter) {
      filter.value = ''
      this.filterOptions(key, '')
      filter.focus()
    }
  }

  private closeCombos() {
    this.container.querySelectorAll('[data-combo-panel]').forEach(p => p.classList.add('hidden'))
    this.container
      .querySelectorAll('[data-combo-trigger]')
      .forEach(t => t.setAttribute('aria-expanded', 'false'))
  }

  /**
   * Reduce a label or a typed query to a comparable form.
   *
   * Categories are written with ampersands ("Arts & Crafts") and people type
   * the word, so "arts and crafts" matched nothing at all. Both sides are
   * normalized to the same shape, and punctuation is dropped so
   * "karaoke/trivia" and "karaoke trivia" both land.
   */
  private static normalizeForSearch(text: string): string {
    return text
      .toLowerCase()
      .replace(/&/g, ' and ')
      .replace(/[^a-z0-9]+/g, ' ')
      .trim()
  }

  private filterOptions(key: string, query: string) {
    const needle = SearchApp.normalizeForSearch(query)
    this.container.querySelectorAll(`[data-combo-list="${key}"] li`).forEach(li => {
      // The label, not the rendered text: that also carries the count, so
      // typing a number used to match unrelated options.
      const label = li.getAttribute('data-combo-label') || li.textContent || ''
      const haystack = SearchApp.normalizeForSearch(label)
      li.classList.toggle('hidden', needle.length > 0 && !haystack.includes(needle))
    })
  }

  private selectOption(key: string, value: string) {
    // An empty value is the "anything / any time / anywhere" option, so it
    // clears the slot rather than being ignored.
    if (key === 'what') this.selectedKeyword = value || null
    else if (key === 'when') this.selectedTimeframe = value || null
    else if (key === 'where') this.selectedNeighborhood = value || null

    // Re-render the sentence and tags in place, keeping the results on screen
    // so the page never blanks out between searches.
    const browseOpen = !this.container
      .querySelector('#browse-panel')
      ?.classList.contains('hidden')
    const section = this.container.querySelector('section')
    if (section) section.outerHTML = this.renderMainInterface()
    if (browseOpen) this.setBrowseOpen(true)

    this.closeCombos()
    // Picking an option is the search - there is no separate submit step.
    this.performSearch()
    // The tile counts describe the new selection, so they have to be redrawn
    // with it. Not awaited: the results matter more than the numbers, and
    // blocking on this would delay them.
    this.refreshFilterCounts()
  }

  /** Refetch the tile counts and redraw the tiles, leaving results alone. */
  private async refreshFilterCounts() {
    await this.loadFilterCounts()
    const browseOpen = !this.container
      .querySelector('#browse-panel')
      ?.classList.contains('hidden')
    const section = this.container.querySelector('section')
    if (section) section.outerHTML = this.renderMainInterface()
    if (browseOpen) this.setBrowseOpen(true)
  }

  private toggleBrowse() {
    const panel = this.container.querySelector('#browse-panel')
    this.setBrowseOpen(panel?.classList.contains('hidden') ?? true)
  }

  private setBrowseOpen(open: boolean) {
    const panel = this.container.querySelector('#browse-panel')
    const label = this.container.querySelector('#browse-toggle-label')
    if (!panel) return
    panel.classList.toggle('hidden', !open)
    if (label) label.textContent = open ? 'Hide options' : 'Browse everything'
  }

  private async performSearch() {
    if (this.isLoading) return

    this.isLoading = true
    // The neighborhood is passed separately as a structured filter, so it is
    // deliberately left out of the natural-language query string.
    // Only the timeframe, which is all the server parses out of this string.
    // The category must NOT be repeated here: it is already applied as a
    // structured filter, and as query text it also becomes a keyword that the
    // event's title has to contain, so the two filters cancel each other out.
    // With no timeframe the server applies no date window and simply returns
    // what is coming up, soonest first.
    const query = this.selectedTimeframe ? `events ${this.selectedTimeframe}` : 'events'

    const container = document.getElementById('events-container')
    if (container) {
      container.innerHTML = '<div class="flex items-center justify-center py-24"><p class="text-gray-400 text-lg">Looping you in…</p></div>'
    }

    try {
      // A new search starts a new list, so paging resets with it.
      this.events = await searchEvents(
        query, SearchApp.PAGE_SIZE, this.selectedNeighborhood, this.selectedKeyword, 0,
      )
      // A short page means there is nothing after it, which saves a request
      // that would come back empty.
      this.hasMore = this.events.length === SearchApp.PAGE_SIZE
      this.renderEventsList(this.events)
      this.watchForScroll()
    } catch (error) {
      if (container) {
        container.innerHTML = '<div class="flex items-center justify-center min-h-screen text-red-600"><p>Oops! Something went wrong. Try again?</p></div>'
      }
    } finally {
      this.isLoading = false
    }
  }

  /**
   * Refresh the tile counts for the current selection.
   *
   * Called on every change, not just at startup: the counts used to be
   * lifetime totals fetched once, so with "Arts & Crafts tonight" chosen the
   * Lake View tile still read 204 while the search returned nothing. Each
   * facet is computed with the other filters applied but not its own, so the
   * numbers stay comparable to each other.
   */
  /**
   * Load the next page and append it, rather than replacing the list.
   *
   * Guarded against overlapping calls: the observer can fire several times
   * while a request is in flight, and each would ask for the same offset.
   */
  private async loadMore() {
    if (this.isLoadingMore || !this.hasMore || this.isLoading) return
    this.isLoadingMore = true
    document.getElementById('events-loading-more')?.classList.remove('hidden')

    const query = this.selectedTimeframe ? `events ${this.selectedTimeframe}` : 'events'
    try {
      const next = await searchEvents(
        query,
        SearchApp.PAGE_SIZE,
        this.selectedNeighborhood,
        this.selectedKeyword,
        this.events.length,
      )
      if (next.length === 0) {
        this.hasMore = false
      } else {
        // Appended as markup rather than re-rendering the list, so the page
        // does not jump back to the top under the reader.
        const grid = document.getElementById('events-grid')
        if (grid) grid.insertAdjacentHTML('beforeend', next.map(e => this.renderEventCard(e)).join(''))
        this.events = this.events.concat(next)
        this.hasMore = next.length === SearchApp.PAGE_SIZE
        this.updateResultCount()
      }
    } catch (error) {
      // Leave hasMore alone: a failed request is not the end of the list, and
      // scrolling again should retry.
      console.error('Error loading more events:', error)
    } finally {
      this.isLoadingMore = false
      document.getElementById('events-loading-more')?.classList.add('hidden')
      if (!this.hasMore) {
        const sentinel = document.getElementById('events-sentinel')
        if (sentinel) sentinel.innerHTML = ''
      }
    }
  }

  /** Keep the heading's count in step with what has actually been loaded. */
  private updateResultCount() {
    const heading = document.querySelector('#events-container h2')
    if (!heading) return
    const shown = this.events.length
    heading.textContent = heading.textContent!.replace(
      /^\s*\d+/, String(shown),
    )
  }

  /** Load the next page when the bottom of the list comes into view. */
  private watchForScroll() {
    this.scrollObserver?.disconnect()
    const sentinel = document.getElementById('events-sentinel')
    if (!sentinel) return
    this.scrollObserver = new IntersectionObserver(
      entries => {
        if (entries.some(e => e.isIntersecting)) this.loadMore()
      },
      // Start fetching a little before the sentinel is actually visible, so
      // the next cards are usually there by the time the reader arrives.
      { rootMargin: '400px' },
    )
    this.scrollObserver.observe(sentinel)
  }

  private async loadFilterCounts() {
    const counts = await getFilterCounts(
      this.selectedKeyword,
      this.selectedNeighborhood,
      this.selectedTimeframe,
    )
    if (counts.categories.length > 0 || counts.neighborhoods.length > 0) {
      this.categories = counts.categories
      this.neighborhoods = counts.neighborhoods
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
