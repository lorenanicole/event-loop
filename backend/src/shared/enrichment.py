"""
Event enrichment utilities for extracting cost and age_range information from event data.
Uses regex patterns for fast, simple extraction without AI.
"""

import logging
import re

logger = logging.getLogger(__name__)


# Cost patterns - ordered by priority (more specific first)
COST_PATTERNS = [
    # Free variations
    (r"\b(?:free|no charge|no admission fee)\b", "Free", re.IGNORECASE),
    # Donation/PWYC (Pay What You Can) - check before price patterns
    (r"\b(?:donation|suggested donation|pwyc|pay what you can)\b", "Donation", re.IGNORECASE),
    # Price ranges: $10-20, $10–20, $10 to $20
    (r"\$\d+(?:\s*[-–to]+\s*\$?\d+)?", None, re.IGNORECASE),  # Capture the match
    # Paid (generic)
    (r"\b(?:paid event|ticketed)\b", "Paid", re.IGNORECASE),
]

# Age range patterns - ordered by priority (more specific first)
AGE_PATTERNS = [
    # Age + (e.g., 18+, 21+, 13+) - most specific, without trailing word boundary (+ is not word char)
    (r"\b(\d{1,2})\+", None, re.IGNORECASE),  # Capture the number
    # Age and over (e.g., 18 and over, 21 and over)
    (r"\b(\d{1,2})\s+and\s+over\b", None, re.IGNORECASE),  # Capture the number
    # 18 and up, 21 and up
    (r"\b(\d{1,2})\s+(?:and\s+)?up\b", None, re.IGNORECASE),  # Capture the number
    # Years old or years of age - specific numeric pattern
    (r"\b(\d{1,2})\s+years?\s+(?:old|of age)\b", None, re.IGNORECASE),  # Capture the number
    # Minimum age
    (r"\bminimum age[:\s]+(\d{1,2})\b", None, re.IGNORECASE),  # Capture the number
    # All ages - before kids friendly to prioritize specificity
    (r"\b(?:all ages|family friendly|family-friendly)\b", "All ages", re.IGNORECASE),
    # Kids/family related - less specific
    (r"\b(?:kids?\s+friendly|for kids?|family event)\b", "Kids friendly", re.IGNORECASE),
    # Note: removed "children" from kids_friendly pattern as it conflicts with numeric patterns
]

# Outdoor/Indoor patterns
OUTDOOR_PATTERNS = [
    (
        r"\b(?:outdoor|outside|park|lakefront|plaza|rooftop|beach|pier|trail|garden|botanical)\b",
        "outdoor",
        re.IGNORECASE,
    ),
    (r"\b(?:in the park|at the lake|along the river)\b", "outdoor", re.IGNORECASE),
]

INDOOR_PATTERNS = [
    (
        r"\b(?:indoor|inside|theater|theatre|lounge|venue|nightclub|museum|gallery|hall|arena|stadium|auditorium)\b",
        "indoor",
        re.IGNORECASE,
    ),
    (r"\b(?:at the|chicago loop|downtown)\b", "indoor", re.IGNORECASE),
]


def extract_cost(text: str) -> str | None:
    """
    Extract cost information from event text.
    Returns: "Free", "Donation", a price range like "$25", "$15-30", or None if not found.
    """
    if not text or not isinstance(text, str):
        return None

    text = text.strip()

    for pattern, replacement, flags in COST_PATTERNS:
        match = re.search(pattern, text, flags)
        if match:
            if replacement:
                return replacement
            else:
                # Return the matched text (e.g., "$25" or "$10-20")
                return match.group(0).strip()

    return None


def extract_age_range(text: str) -> str | None:
    """
    Extract age range information from event text.
    Returns: "All ages", "Kids friendly", "18+", "21+", etc., or None if not found.
    """
    if not text or not isinstance(text, str):
        return None

    text = text.strip()

    for pattern, replacement, flags in AGE_PATTERNS:
        match = re.search(pattern, text, flags)
        if match:
            if replacement:
                return replacement
            else:
                # Extract the age number and format as "18+", "21+", etc.
                age_num = match.group(1)
                return f"{age_num}+"

    return None


def extract_from_event_text(
    event_name: str,
    details: str | None = None,
) -> tuple[str | None, str | None]:
    """
    Combined extraction of cost and age_range from event name and details.
    Searches both name and details, prioritizing details (more detailed info).

    Returns: (cost, age_range) tuple
    """
    # Combine name and details for comprehensive search
    full_text = f"{event_name} {details or ''}".strip()

    # Extract cost (check name and full text)
    cost = extract_cost(event_name)
    if not cost:
        cost = extract_cost(full_text)

    # Extract age_range (check name and full text)
    age_range = extract_age_range(event_name)
    if not age_range:
        age_range = extract_age_range(full_text)

    return cost, age_range


def extract_is_outdoor(text: str) -> str | None:
    """
    Detect if event is outdoor, indoor, or hybrid.
    Returns: "outdoor", "indoor", or None if unclear.
    """
    if not text or not isinstance(text, str):
        return None

    text = text.strip().lower()

    # Check outdoor patterns first
    for pattern, outdoor_type, flags in OUTDOOR_PATTERNS:
        if re.search(pattern, text, flags):
            return outdoor_type

    # Check indoor patterns
    for pattern, indoor_type, flags in INDOOR_PATTERNS:
        if re.search(pattern, text, flags):
            return indoor_type

    return None


def extract_address(text: str) -> str | None:
    """
    Extract street address from event text.
    Looks for patterns like "123 Main St", "at 456 State St", "located at 789 Oak Ave".
    Returns: address string or None if not found.
    """
    if not text or not isinstance(text, str):
        return None

    # Pattern: number + street name + optional apartment/suite
    # e.g., "123 Main Street", "456 Oak Ave, Chicago, IL 60601"
    address_pattern = r"\b(\d+\s+[A-Za-z\s]+(?:St|Street|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive|Way|Lane|Ln|Ct|Court|Pl|Place)\.?[^,]*)"
    match = re.search(address_pattern, text, re.IGNORECASE)
    if match:
        return match.group(0).strip()

    return None


def extract_venue_name(event_name: str, url: str | None = None) -> str | None:
    """
    Extract venue/location name from event name or URL.
    Heuristic: if event name contains "at" or "at the", extract the part after it.
    E.g., "Concert at Blue Note" -> "Blue Note"
    """
    if not event_name or not isinstance(event_name, str):
        return None

    # Look for "at venue_name" pattern
    at_pattern = r"\bat\s+(?:the\s+)?([A-Za-z\s&'-]+?)(?:\s+-|\s+on|\s+\(|$)"
    match = re.search(at_pattern, event_name, re.IGNORECASE)
    if match:
        venue = match.group(1).strip()
        # Filter out common filler words
        if venue and len(venue) > 2 and venue.lower() not in ["the", "chicago"]:
            return venue

    return None


def extract_and_update_event(event_data: dict) -> dict:
    """
    Extract cost, age_range, is_outdoor, address, and venue_name from event data.
    Used during scraping to enrich events before saving to DB.

    Args:
        event_data: dict with 'name' and optional 'details', 'url' keys

    Returns:
        Updated event_data dict with enriched fields
    """
    if not event_data:
        return event_data

    name = event_data.get("name", "")
    details = event_data.get("details", "")
    event_data.get("url") or event_data.get("origination_url")

    # Extract cost and age range
    cost, age_range = extract_from_event_text(name, details)
    if cost:
        event_data["cost"] = cost
    if age_range:
        event_data["age_range"] = age_range

    # Extract outdoor/indoor
    full_text = f"{name} {details or ''}".strip()
    is_outdoor = extract_is_outdoor(full_text)
    if is_outdoor:
        event_data["is_outdoor"] = is_outdoor

    # Extract address
    address = extract_address(full_text)
    if address:
        event_data["address"] = address

    # Extract venue name
    venue_name = extract_venue_name(name)
    if venue_name:
        event_data["venue_name"] = venue_name

    return event_data
