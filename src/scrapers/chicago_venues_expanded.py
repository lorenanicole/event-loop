"""
Comprehensive Chicago Entertainment Venues by Neighborhood
Based on research and user-provided listings.
Organized by neighborhood for geographic scoping.
"""

CHICAGO_VENUES_BY_NEIGHBORHOOD = {
    # BUCKTOWN - Music venues, bars, event spaces
    "Bucktown": [
        {"name": "The Hideout", "url": "https://www.hideoutchicago.com", "category": "music", "address": "1354 W Wabansia Ave"},
        {"name": "Concord Music Hall", "url": "https://www.concordmusichal.com", "category": "music", "address": "2047 N Milwaukee Ave"},
        {"name": "Salt Shed", "url": "https://www.saltshedchicago.com", "category": "music", "address": "1357 N Elston Ave"},
        {"name": "Outset", "url": "https://www.outsetbar.com", "category": "music", "address": "1675 N Elston Ave"},
        {"name": "Morgan Manufacturing", "url": "https://www.morganmfgchicago.com", "category": "other", "address": "1837 W Hubbard St"},
        {"name": "Emporium Chicago", "url": "https://www.emporiumchicago.com", "category": "music", "address": "1366 N Milwaukee Ave"},
        {"name": "Rosa's Lounge", "url": "https://www.rosaslounge.com", "category": "music", "address": "3420 W North Ave"},
    ],

    # WICKER PARK - Rock, indie, electronic venues
    "Wicker Park": [
        {"name": "Subterranean", "url": "https://www.subt.net", "category": "music", "address": "2011 W North Ave"},
        {"name": "Chop Shop", "url": "https://www.chopshopmusic.com", "category": "music", "address": "2033 W North Ave"},
        {"name": "Empty Bottle", "url": "https://www.emptybottle.com", "category": "music", "address": "1035 N Western Ave"},
        {"name": "Morgan Manufacturing Lofts", "url": "https://www.morganmfgchicago.com", "category": "other", "address": "1837 W Hubbard"},
    ],

    # LOGAN SQUARE - Diverse venues
    "Logan Square": [
        {"name": "Lincoln Hall", "url": "https://www.lincolnhallchicago.com", "category": "music", "address": "2424 N Lincoln Ave"},
        {"name": "Thalia Hall", "url": "https://www.thaliahall.com", "category": "music", "address": "1807 S Allport St"},
        {"name": "Lacuna Lofts", "url": "https://www.lacunalofts.com", "category": "music", "address": "2101 S Archer Ave"},
        {"name": "Artifact Events", "url": "https://www.artifactevents.com", "category": "other", "address": "4325 N Ravenswood Ave"},
    ],

    # PILSEN - Arts district venues
    "Pilsen": [
        {"name": "Lacuna Lofts", "url": "https://www.lacunalofts.com", "category": "music", "address": "2101 S Archer Ave"},
        {"name": "Artifact Events", "url": "https://www.artifactevents.com", "category": "other", "address": "4325 N Ravenswood Ave"},
        {"name": "El Museo de los Muertos", "url": "https://www.elmuseodelasmuertos.com", "category": "other", "address": "3400 W Lawrence Ave"},
        {"name": "Bridgeport Art Center", "url": "https://www.bridgeportartcenter.com", "category": "other", "address": "1200 W 35th St"},
    ],

    # UPTOWN - Theater, concerts, live music
    "Uptown": [
        {"name": "Byline Bank Aragon Ballroom", "url": "https://www.aragonchicago.com", "category": "music", "address": "1106 W Lawrence Ave"},
        {"name": "Riviera Theatre", "url": "https://www.rivierachicago.com", "category": "music", "address": "4746 N Broadway St"},
        {"name": "Green Mill Jazz Club", "url": "https://www.greenmilljazzclub.com", "category": "music", "address": "4802 N Broadway St"},
        {"name": "Music Box Theatre", "url": "https://www.musicboxtheatre.com", "category": "cinema", "address": "3733 N Southport Ave"},
    ],

    # LAKEVIEW - Diverse entertainment
    "Lakeview": [
        {"name": "Schubas Tavern", "url": "https://www.schubastavern.com", "category": "music", "address": "3159 N Southport Ave"},
        {"name": "The Vic Theatre", "url": "https://www.thevictheatre.com", "category": "music", "address": "3145 N Sheffield Ave"},
        {"name": "Cornelia Nightclub", "url": "https://www.cornelianightclub.com", "category": "music", "address": "3708 N Clark St"},
        {"name": "Boystown Music Venues", "url": "https://www.roscoes.com", "category": "music", "address": "3209 N Halsted St"},
    ],

    # RIVER NORTH - Large venues, entertainment district
    "River North": [
        {"name": "House of Blues Chicago", "url": "https://www.houseofblues.com/chicago", "category": "music", "address": "329 N Dearborn St"},
        {"name": "Chicago Theatre", "url": "https://www.thechicagotheatre.com", "category": "theater", "address": "175 N State St"},
        {"name": "CIBC Theatre", "url": "https://www.cibctheatre.com", "category": "theater", "address": "18 W Monroe St"},
        {"name": "Paris Club", "url": "https://www.parisclubchicago.com", "category": "music", "address": "59 W Hubbard St"},
        {"name": "Foundation Chicago", "url": "https://www.foundationchicago.com", "category": "music", "address": "66 W Kinzie St"},
    ],

    # LOOP - Downtown theaters and venues
    "Loop": [
        {"name": "Chicago Symphony Orchestra Hall", "url": "https://cso.org", "category": "music", "address": "220 S Michigan Ave"},
        {"name": "Civic Opera House", "url": "https://www.lyricopera.org", "category": "theater", "address": "20 W Randolph St"},
        {"name": "Auditorium Theatre", "url": "https://www.auditoriumtheatre.org", "category": "theater", "address": "50 E Congress Pkwy"},
        {"name": "Cadillac Palace Theatre", "url": "https://www.ticketmaster.com", "category": "theater", "address": "151 W Randolph St"},
    ],

    # WEST LOOP - Arts and music
    "West Loop": [
        {"name": "Morgan Manufacturing", "url": "https://www.morganmfgchicago.com", "category": "other", "address": "1837 W Hubbard St"},
        {"name": "Lacuna Lofts", "url": "https://www.lacunalofts.com", "category": "music", "address": "2101 S Archer Ave"},
        {"name": "Morgan Ballroom", "url": "https://www.morganmfgchicago.com", "category": "other", "address": "1837 W Hubbard St"},
    ],

    # LINCOLN SQUARE - Theater, music, restaurants
    "Lincoln Square": [
        {"name": "Lincoln Theatre", "url": "https://www.lincolntheatre.org", "category": "theater", "address": "4415 N Lincoln Ave"},
        {"name": "Ravenswood Events", "url": "https://www.ravenswoodeventspace.com", "category": "other", "address": "4325 N Ravenswood Ave"},
        {"name": "Griffith Theater", "url": "https://www.griffiththeater.com", "category": "theater", "address": "2650 W Barry Ave"},
    ],

    # ROGERS PARK - Diverse venues
    "Rogers Park": [
        {"name": "Loyola University Performing Arts", "url": "https://www.luc.edu", "category": "theater", "address": "6525 N Sheridan Rd"},
        {"name": "Rogers Park Venue", "url": "https://www.rogersparkcenter.org", "category": "other", "address": "7211 N Clark St"},
    ],

    # DOWNTOWN - Major venues
    "Downtown": [
        {"name": "Jay Pritzker Pavilion", "url": "https://www.millenniumpark.org", "category": "music", "address": "201 E Randolph St"},
        {"name": "United Center", "url": "https://www.unitedcenter.com", "category": "music", "address": "1901 W Madison St"},
        {"name": "Allstate Arena", "url": "https://www.allstatearena.com", "category": "music", "address": "6220 N Mannheim Rd"},
    ],

    # ANDERSONVILLE - Swedish neighborhood venues
    "Andersonville": [
        {"name": "Andersonville Brewing Company", "url": "https://www.andersonvillebrewing.com", "category": "music", "address": "5656 N Clark St"},
        {"name": "Hopleaf Bar", "url": "https://www.hopleaf.com", "category": "music", "address": "5148 N Clark St"},
    ],
}

def get_venues_for_neighborhood(neighborhood: str) -> list:
    """Get all venues for a neighborhood."""
    return CHICAGO_VENUES_BY_NEIGHBORHOOD.get(neighborhood, [])

def get_all_neighborhoods() -> list:
    """Get all neighborhoods with venues."""
    return list(CHICAGO_VENUES_BY_NEIGHBORHOOD.keys())

def get_venue_count_by_neighborhood() -> dict:
    """Get count of venues per neighborhood."""
    return {
        nbhd: len(venues)
        for nbhd, venues in CHICAGO_VENUES_BY_NEIGHBORHOOD.items()
    }
