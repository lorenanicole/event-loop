"""Reading a ticket price off an event's own page.

The scrapers read listing pages, and most venues do not put a price on a
listing card. Of 2,498 unpriced events, re-scanning every scrap of text already
in the database recovered exactly zero prices, because the price was never on
the page we fetched. It is on the event's own page, which every row already
links to in `origination_url`.

Two ways to read it:

1. `schema.org/Event` `offers` - numeric, unambiguous, and correct on every
   page sampled. Thalia Hall, Chop Shop, Salt Shed and Chief O'Neill's all
   publish it. Applied to any source that has it.

2. A per-source pattern, for venues that print the price as prose. Each rule
   below was written against text actually observed on that venue's pages, and
   the comment records what that text looks like.

Deliberately NOT here: a generic "find a price label, read the number next to
it" scan. It was built and measured, and it is wrong often enough to be worse
than no price at all:

  - Zanies' per-show URLs render the whole month's listing, so every show
    picked up a neighbouring show's price.
  - Broadway In Chicago pages advertise "a limited number of $49 day-of-show
    rush tickets", which is not what a seat costs.
  - Old Town writes "$23 General Public ($20 + $3 fee)"; a nearest-number scan
    reported $20, undercutting the real price.
  - McCormick Place quotes "a usage deposit of $300 per line" - exhibitor
    billing, not admission.
  - Reggies serves bytes that decode to garbage sprinkled with dollar signs.

A price that cannot be read confidently is left alone. An absent price is
honest; an invented one is worse than nothing, because the price is the one
thing on a listing somebody might plan around.
"""

import json
import re
from typing import Optional

from bs4 import BeautifulSoup


def money(value: float) -> str:
    """Render an amount the way the UI shows it.

    Whole dollars read better without cents, and 25.5 must not become "$25.5",
    which looks like a truncation.
    """
    return f"${value:.0f}" if value == int(value) else f"${value:.2f}"


def render(prices: list[float]) -> Optional[str]:
    """A list of amounts as one displayable price, or a range."""
    if not prices:
        return None
    low, high = min(prices), max(prices)
    if high == 0:
        return "Free"
    # A tier list starting at zero means free entry with paid upgrades;
    # "$0-$40" reads like a bug, so lead with the free option.
    if low == 0:
        return f"Free-{money(high)}"
    return money(low) if low == high else f"{money(low)}-{money(high)}"


def _as_amount(raw) -> Optional[float]:
    # `is` rather than `in (..., False)`: 0 == False in Python, so a membership
    # test discards a price of zero - every free event lost its price.
    if raw is None or raw is True or raw is False or raw == "":
        return None
    try:
        return float(str(raw).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def price_from_offers(node: dict) -> Optional[str]:
    """Read a price out of a schema.org Event's `offers`.

    `offers` may be a single object or a list of them, one per ticket tier, in
    which case the overall span is reported.
    """
    offers = node.get("offers")
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return None

    prices = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        spec = offer.get("priceSpecification")
        source = spec if isinstance(spec, dict) else offer
        for key in ("price", "lowPrice", "highPrice", "minPrice", "maxPrice"):
            amount = _as_amount(source.get(key))
            if amount is not None:
                prices.append(amount)

    return render(prices)


def price_from_jsonld(soup: BeautifulSoup) -> Optional[str]:
    """The first price in any schema.org block on the page.

    Walks the whole structure rather than only the top level: sites wrap the
    Event in an `@graph` or hang it off `mainEntity`, several levels above the
    offers. Bounded, because a malformed document can nest deeply.
    """
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = [data]
        visited = 0
        while stack and visited < 500:
            visited += 1
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            if "offers" in node:
                found = price_from_offers(node)
                if found:
                    return found
            stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
    return None


# Per-source price patterns. Each entry is (pattern, mode):
#   "one"   - one captured amount; 0 renders as Free
#   "range" - two captured amounts, rendered as a span
#   "all"   - every match's first group collected into one span
#
# Rules are tried in order and the first that matches wins, so a specific
# pattern can sit ahead of a looser one for the same venue.
SOURCE_PRICE_RULES: dict[str, list[tuple[str, str]]] = {
    # "... Chicago, IL 60632 Event Fee $0.00 Age Range Early Childhood".
    # Most Park District programming is genuinely free, which is why this one
    # rule covers more rows than every other source put together.
    "chicago_park_district": [(r"Event Fee\s*\$(\d+(?:\.\d{2})?)", "one")],

    # "TICKETS General Admission $25 VIP $40 Student Tickets $20 CASH ONLY",
    # and some pages write "Thursday - $30 general admission - $45 VIP".
    "chicago_venue_jazz_showcase": [
        (r"General Admission\s*\$(\d+)", "one"),
        (r"\$(\d+)\s*(?:-|—|–)?\s*general admission", "one"),
    ],

    # "$23 General Public ($20 + $3 fee)" - the advertised total comes first,
    # and the parenthesised split is the base plus the service fee. Capturing
    # the leading number reports what somebody actually pays.
    "chicago_venue_old_town_school_of_folk_music": [
        (r"\$(\d+)\s+General Public", "one"),
    ],

    # "Doors open - 9:00 PM Tickets TIER 1 $20.00 Get tickets TIER 2 $25.00",
    # also spelled "EARLY BIRD" / "General Admission". Every tier is collected
    # so the row shows the span rather than just the cheapest.
    "chicago_venue_sleeping_village": [
        (r"(?:TIER\s*\d|EARLY BIRD|General Admission)\s*\$(\d+)(?:\.\d{2})?", "all"),
    ],

    # "Select Evening - 15 Performances - $73.00 to $82.00".
    "chicago_venue_goodman_theatre": [
        (r"\$(\d+)(?:\.\d{2})?\s+to\s+\$(\d+)(?:\.\d{2})?", "range"),
    ],

    # "Show Length: 60 Minutes Tickets: $20 Rated: R".
    "chicago_venue_den_theatre": [(r"Tickets:\s*\$(\d+)", "one")],

    # "Baffes Theatre at the Beverly Arts Center Tickets: $35 for adults".
    "chicago_venue_beverly_arts_center": [(r"Tickets:\s*\$(\d+)", "one")],

    # "Wed, Oct 7th - Doors 7PM - Show 8PM - $10adv/$15doors".
    "chicago_venue_martyrss": [
        (r"\$(\d+)\s*adv\s*/\s*\$(\d+)\s*doors?", "range"),
    ],

    # "General admission is $27 when tickets are purchased online".
    "chicago_venue_navy_pier": [(r"General admission is \$(\d+)", "one")],
}


def price_from_source_rules(source: Optional[str], text: str) -> Optional[str]:
    """Apply the patterns written for this source, if there are any."""
    for pattern, mode in SOURCE_PRICE_RULES.get(source or "", []):
        if mode == "all":
            amounts = [
                a for m in re.finditer(pattern, text, re.I)
                if (a := _as_amount(m.group(1))) is not None
            ]
            if amounts:
                return render(amounts)
            continue

        match = re.search(pattern, text, re.I)
        if not match:
            continue
        if mode == "range":
            low, high = _as_amount(match.group(1)), _as_amount(match.group(2))
            if low is not None and high is not None and low <= high:
                return render([low, high])
            continue
        amount = _as_amount(match.group(1))
        if amount is not None:
            return render([amount])
    return None


def visible_text(soup: BeautifulSoup) -> str:
    """Page text with the parts that are not prose removed."""
    for tag in soup(["script", "style", "noscript", "nav", "footer", "svg"]):
        tag.decompose()
    return " ".join((soup.get_text(" ") or "").split())


def cost_from_page(html: str, source: Optional[str] = None) -> Optional[str]:
    """The ticket price on an event page, structured data preferred."""
    if not html or "<" not in html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    found = price_from_jsonld(soup)
    if found:
        return found
    return price_from_source_rules(source, visible_text(soup))
