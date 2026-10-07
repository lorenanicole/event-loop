import axios from 'axios'

export interface Event {
  id: number
  name: string
  date: string
  date_end?: string | null
  time?: string | null
  time_end?: string | null
  category: string
  details?: string
  origination_url: string
  date_retrieved: string
  venue_name?: string | null
  address?: string | null
  cost?: string | null
  age_range?: string | null
}

export interface SearchResponse {
  events: Event[]
  total: number
}

export interface Stats {
  total_events: number
  unique_categories: number
  earliest_event: string
  latest_event: string
}

const API_BASE = '/api'

const client = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
})

export interface Neighborhood {
  name: string
  event_count: number
}

export async function searchEvents(
  query: string,
  limit: number = 20,
  neighborhood: string | null = null,
  category: string | null = null,
): Promise<Event[]> {
  try {
    const response = await client.post('/search', {
      query,
      limit,
      // Sent as structured filters, not words in the query string: matching
      // them as text meant a tile only worked if its name appeared in the
      // event's title.
      ...(neighborhood ? { neighborhood } : {}),
      ...(category ? { category } : {}),
    })
    return response.data
  } catch (error) {
    console.error('Search error:', error)
    throw error
  }
}

/** Neighborhoods that currently have upcoming events, busiest first. */
export async function getNeighborhoods(): Promise<Neighborhood[]> {
  try {
    const response = await client.get('/events/neighborhoods')
    return response.data
  } catch (error) {
    console.error('Error fetching neighborhoods:', error)
    return []
  }
}

export async function getCategories(): Promise<string[]> {
  try {
    const response = await client.get('/search/categories')
    return response.data.categories
  } catch (error) {
    console.error('Error fetching categories:', error)
    return []
  }
}

export async function getStats(): Promise<Stats | null> {
  try {
    const response = await client.get('/search/stats')
    return response.data
  } catch (error) {
    console.error('Error fetching stats:', error)
    return null
  }
}

export async function getAllEvents(skip: number = 0, limit: number = 20): Promise<Event[]> {
  try {
    const response = await client.get('/events', {
      params: { skip, limit }
    })
    return response.data
  } catch (error) {
    console.error('Error fetching events:', error)
    return []
  }
}
