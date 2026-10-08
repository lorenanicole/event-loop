# Scraper inventory

This file documents which scraper modules are active, which are available but
not scheduled, and which have been retired. Update it when adding or removing
a scraper.

---

## Active (run by `additive_scrape.py` and `POST /api/venue-events/refresh`)

These are the modules that actually execute during a normal scrape run.

### Entry points
| File | Role |
|---|---|
| `backend/additive_scrape.py` | CLI runner — calls `VenueScraper` over `CHICAGO_VENUES` and each external scraper |
| `backend/src/app/api/routes.py` → `POST /api/venue-events/refresh` | HTTP trigger — calls `scrape_chicago_events()` |

### Venue scrapers (custom)
| Module | What it does |
|---|---|
| `scrapers/custom/venue/chicago_events_scraper.py` | Orchestrates venue scraping; re-exports helpers from the modules below |
| `scrapers/custom/venue/venue_scraper.py` | `VenueScraper` engine, `VenueConfig` dataclass, `parse_cost()` |
| `scrapers/custom/venue/venues.py` | `CHICAGO_VENUES` — the canonical list of venues and their configs |
| `scrapers/custom/venue/extractors.py` | Reusable extractors: `extract_tribe_events`, `extract_dated_list_items`, etc. |
| `scrapers/custom/venue/venue_parsing.py` | Date, title, and price parsing helpers |

### External scrapers
| Module | Source | Notes |
|---|---|---|
| `scrapers/external/do312.py` | do312.com | Active; primary Chicago events aggregator |
| `scrapers/external/eventbrite.py` | Eventbrite API | Active; requires `EVENTBRITE_PRIVATE_TOKEN` |
| `scrapers/external/ticketmaster.py` | Ticketmaster API | Active; requires `TICKETMASTER_API_KEY` |
| `scrapers/external/chicago_park_district.py` | Chicago Park District | Active; public API, no key needed |
| `scrapers/external/broadway_in_chicago.py` | broadwayinchicago.com | Active; HTML scraper |
| `scrapers/external/bandsintown.py` | Bandsintown API | Active; requires API key |
| `scrapers/external/yourchicagoguide.py` | yourchicagoguide.com | Active; HTML scraper |

---

## Available but not scheduled

These modules exist and are importable but are not called by any scheduled or
HTTP-triggered run. They can be run manually.

| Module | What it does | Why not scheduled |
|---|---|---|
| `scrapers/custom/eventscom.py` | events.com scraper | Commented out of `external/__init__.py`; requires pyppeteer (headless browser), not installed in prod |
| `scrapers/custom/timeoutchicago.py` | Time Out Chicago scraper | Not wired into `additive_scrape.py`; was used for a one-off import, source still works |

---

## Retired (deleted)

These files were removed because they had no callers in the running application,
contained hardcoded absolute paths from a developer machine, or had broken
imports. Their git history is preserved if they are ever needed for reference.

| File | Reason for deletion |
|---|---|
| `scrapers/custom/venue_discovery_worker.py` | Hardcoded `sys.path.insert(0, "/Users/lorenamesa/...")`, no callers |
| `scrapers/custom/venue_events_persist.py` | Broken import (`from scrapers.venue_scraper import ...` — path never existed), no callers |
| `scrapers/custom/venue_implementation_sprint.py` | Hardcoded `sys.path.insert(0, "/Users/lorenamesa/...")`, one-off sprint script, no callers |
| `scrapers/custom/venue/chicago_venues_master.py` | Research data dump; superseded by `venues.py`. Only imported by the two populate scripts below |
| `scrapers/custom/venue/chicago_venues.py` | Flat name list superseded by `venues.py`; only used by `osm_venues.py` |
| `scrapers/custom/venue/populate_venues.py` | One-off DB population script; no callers in running app |
| `scrapers/custom/venue/populate_venues_upsert.py` | Duplicate of `populate_venues.py` with upsert logic; no callers |
| `scrapers/custom/venue/osm_venues.py` | OpenStreetMap venue discovery experiment; no callers |
| `scrapers/custom/venue/avondale_venues.py` | Single-neighbourhood prototype; superseded by `venues.py` entries |
| `scrapers/custom/venue/wicker_park_venues_v2.py` | Single-neighbourhood prototype; superseded by `venues.py` entries |
