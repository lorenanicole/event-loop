"""Telling a Chicago address from a suburban one.

do312 covers the whole metro, not just the city, so 44 upcoming events are in
Glencoe, Naperville, Rosemont, Berwyn and sixteen other suburbs. Shown in an
app whose headline reads "anywhere in Chicago", they quietly misrepresent
themselves - somebody looking for a Tuesday night out does not expect
Naperville.

Deleting them would be worse: the Chicago Botanic Garden is in Glencoe, the
Evanston rooms are part of the same scene, and people do travel. So they are
labelled instead, and the label is what the card and the assistant say.

Detection reads the city out of the address rather than guessing from a list
of suburb names, because a list gets this wrong in the direction that
matters: "3020 N. Oak Park Ave, Chicago" is a Chicago address on a street
named after a suburb, and a name match would move a real Chicago event to
Oak Park. The city is the token immediately before the state.
"""

import re

# "..., Evanston, IL 60202" or "..., Evanston, IL" - the city sits directly
# before the state, which is the only position that reliably means a city.
_CITY_BEFORE_STATE = re.compile(
    r",\s*([A-Za-z][A-Za-z .'-]{2,30}?),?\s+(?:IL|Illinois)\b",
    re.IGNORECASE,
)

# Written several ways by different sources.
_CHICAGO = {"chicago", "chicago il", "city of chicago"}


def locality_of(address: str | None) -> str | None:
    """The suburb an address is in, or None when it is Chicago or unknown.

    None means "do not label this": either it is in Chicago, or the address
    does not say. Both should be left alone - inventing a locality is worse
    than omitting one.
    """
    if not address:
        return None
    found = _CITY_BEFORE_STATE.search(address)
    if not found:
        return None
    city = " ".join(found.group(1).split()).title()
    if city.lower() in _CHICAGO:
        return None
    # A suite or unit number can land in the city position on a messy
    # address: "..., Suite 8, Naperville, IL". Take the last match instead.
    matches = _CITY_BEFORE_STATE.findall(address)
    if matches:
        city = " ".join(matches[-1].split()).title()
    return None if city.lower() in _CHICAGO else city
