"""Running the venue scrapers and storing what they return.

This file was 4,118 lines doing three unrelated jobs. The other two now live
next to it:

    venue_parsing.py   reading dates, titles and prices out of page text
    extractors.py      one extractor per way a venue publishes a calendar
    venues.py          which venues to scrape, as data

What is left is the part that has to know about all three: run every venue
concurrently, and write the results.

Imported names are re-exported below, so callers keep importing from here and
the split is invisible to them.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from shared.categories import classify_all, infer_category, normalize_category
from shared.database.models import Base, EventModel, NeighborhoodModel, VenueModel
from shared.database.neighborhoods import canonical_neighborhood, resolve_neighborhood_id
from shared.localtime import to_chicago_naive

# Re-exported for callers that imported these from here before the split.
# Named explicitly rather than star-imported: a star says "something in there"
# and this says which, so removing an extractor fails loudly at the import
# instead of quietly at the call.
from .extractors import (  # noqa: F401
    extract_dated_links,
    extract_dated_list_items,
    extract_events_from_json_ld,
    extract_labelled_meeting,
    extract_songkick_venue,
    extract_tickeri_venue,
    extract_tribe_events,
)
from .venue_parsing import (  # noqa: F401
    VENUE_SCRAPE_TIMEOUT,
    infer_event_year,
    jsonld_offer_cost,
    parse_date_range,
    venue_source_name,
)
from .venue_scraper import VenueConfig, VenueEvent, VenueScraper, parse_cost  # noqa: F401
from .venues import CHICAGO_VENUES  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def venue_to_neighborhood() -> dict[str, str]:
    """Map lowercased venue name -> canonical neighborhood name.

    CHICAGO_VENUES is keyed by neighborhood, so it is the authoritative source
    for which part of the city a venue sits in.
    """
    mapping: dict[str, str] = {}
    for neighborhood, configs in CHICAGO_VENUES.items():
        for config in configs:
            mapping.setdefault(config.name.strip().lower(), canonical_neighborhood(neighborhood))
    return mapping


async def _url_taken(session, url: str) -> bool:
    """True if some event row already claims this origination_url."""
    result = await session.execute(
        select(EventModel.id).where(EventModel.origination_url == url)
    )
    return result.scalars().first() is not None


async def save_events_to_db(
    async_session_maker,
    config: VenueConfig,
    events: list[VenueEvent],
    neighborhood: Optional[str] = None,
) -> None:
    """Save extracted events to database (upsert to avoid duplicates)."""
    if not events:
        return

    async with async_session_maker() as session:
        try:
            # Which part of the city these events belong to, so the UI can
            # offer neighborhoods as a filter.
            neighborhood_id = await resolve_neighborhood_id(session, neighborhood)
            # origination_url is UNIQUE in the schema, but venues routinely reuse a
            # single URL across shows (a homepage fallback, or one tour page covering
            # two nights). Track what this batch has claimed so a collision can be
            # given a deterministic unique variant instead of raising - an IntegrityError
            # here rolls back every event for the venue, not just the colliding one.
            used_urls = set()
            # An extractor that yields the same event twice used to produce two
            # rows, because the collision handling below invents a unique URL
            # for the second one and so preserves the duplicate rather than
            # recognizing it. Kingston Mines stored every show twice this way,
            # every night. Collapse identical events before saving instead:
            # identity is name + date + time, so two genuinely different sets
            # on one night still count separately.
            deduped = []
            seen_identity = set()
            for event in events:
                identity = (
                    (event.name or "").strip().lower(),
                    (event.date or "").strip(),
                    (event.time or "").strip().lower(),
                )
                if identity in seen_identity:
                    continue
                seen_identity.add(identity)
                deduped.append(event)
            if len(deduped) != len(events):
                logger.info(
                    f"{config.name}: {len(events) - len(deduped)} duplicate events "
                    f"collapsed before saving"
                )
            events = deduped

            # Add or update events
            for i, event in enumerate(events):
                # Parse date string to datetime objects
                parsed_date, parsed_date_end = parse_date_range(event.date) if event.date else (None, None)
                parsed_date_end_override, _ = parse_date_range(event.date_end) if event.date_end else (None, None)

                # Use override if provided, otherwise use parsed end date
                final_date_end = parsed_date_end_override or parsed_date_end

                source_name = venue_source_name(config)

                # Check if event already exists by name + date + source
                # This handles venues that don't have unique event URLs (all use fallback)
                existing = await session.execute(
                    select(EventModel).where(
                        (EventModel.name == event.name) &
                        (EventModel.source == source_name) &
                        (EventModel.date == parsed_date)  # Same event on same date
                    )
                )
                existing_event = existing.scalars().first()

                if existing_event:
                    # Update existing event with new date info
                    existing_event.date = parsed_date
                    existing_event.date_end = final_date_end
                    existing_event.time = event.time
                    existing_event.time_end = event.time_end
                    existing_event.date_retrieved = datetime.utcnow()
                    # Only fill a price in, never blank one out: a venue that
                    # stops printing the price on its listing page should not
                    # erase a price already collected.
                    if event.cost:
                        existing_event.cost = event.cost
                    if neighborhood_id:
                        existing_event.neighborhood_id = neighborhood_id
                else:
                    # Resolve a unique origination_url. The suffix is derived from the
                    # event's identity (source + date + name), so a later rescrape of the
                    # same event rebuilds the same URL and updates in place.
                    base_url = event.url or config.website_url
                    origination_url = base_url
                    if base_url in used_urls or await _url_taken(session, base_url):
                        date_key = parsed_date.strftime("%Y-%m-%d") if parsed_date else "nodate"
                        origination_url = f"{base_url}#{source_name}-{date_key}-{event.name[:60]}"
                        if origination_url in used_urls:
                            origination_url = f"{origination_url}-{i}"
                    used_urls.add(origination_url)

                    # Create new event
                    event_model = EventModel(
                        name=event.name,
                        date=parsed_date,
                        date_end=final_date_end,
                        time=event.time,
                        time_end=event.time_end,
                        category=normalize_category(
                            infer_category(event.name, event.category)
                        ),
                        # Every applicable label, so the event is findable
                        # under its secondary categories too.
                        categories=classify_all(event.name, event.category),
                        address=event.location,
                        venue_name=event.venue_name or config.name,
                        origination_url=origination_url,
                        source=source_name,
                        details=None,
                        cost=event.cost,
                        neighborhood_id=neighborhood_id,
                    )
                    session.add(event_model)

            await session.commit()
            logger.info(f"Saved {len(events)} events to database for {config.name}")

        except Exception as e:
            logger.error(f"Error saving events for {config.name}: {e}")
            await session.rollback()


async def scrape_chicago_events() -> dict[str, list[VenueEvent]]:
    """Scrape ALL Chicago neighborhoods/venues and save to database."""
    results = {}
    total_events = 0

    # Initialize database - use shared database and create all tables
    from shared.database import AsyncSessionLocal, init_db

    await init_db()
    async_session = AsyncSessionLocal

    async with httpx.AsyncClient(timeout=15) as client:
        for neighborhood, venues in CHICAGO_VENUES.items():
            logger.info(f"\n{'='*60}")
            logger.info(f"Scraping {neighborhood} ({len(venues)} venues)")
            logger.info('='*60)

            neighborhood_events = []
            for config in venues:
                try:
                    scraper = VenueScraper(config)
                    # Hard cap per venue: a site that never finishes loading (or a
                    # browser that won't close) would otherwise stall the whole run.
                    events = await asyncio.wait_for(
                        scraper.scrape(client), timeout=VENUE_SCRAPE_TIMEOUT
                    )
                    neighborhood_events.extend(events)
                    total_events += len(events)

                    # Save events to database
                    await save_events_to_db(async_session, config, events, neighborhood)

                except asyncio.TimeoutError:
                    logger.error(f"{config.name}: timed out after {VENUE_SCRAPE_TIMEOUT}s, skipping")
                except Exception as e:
                    logger.error(f"Error scraping {config.name}: {e}")

            results[neighborhood] = neighborhood_events
            logger.info(f"{neighborhood}: {len(neighborhood_events)} total events\n")

    logger.info(f"\n{'='*60}")
    logger.info(f"✅ TOTAL CHICAGO EVENTS: {total_events}")
    logger.info('='*60)

    for neighborhood in sorted(results.keys()):
        events = results[neighborhood]
        by_venue = {}
        for e in events:
            by_venue.setdefault(e.venue_name, []).append(e)

        print(f"\n{neighborhood}: {len(events)} events")
        for venue in sorted(by_venue.keys()):
            print(f"  • {venue}: {len(by_venue[venue])}")

    return results


if __name__ == "__main__":
    import asyncio
    asyncio.run(scrape_chicago_events())
