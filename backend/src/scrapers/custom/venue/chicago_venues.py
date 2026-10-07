"""
Comprehensive list of Chicago entertainment venues.
Used as seeds for Nominatim venue search and SerpAPI website discovery.
"""

CHICAGO_VENUES = [
    # ===== THEATERS - MAJOR & BROADWAY =====
    {"name": "Steppenwolf Theatre Company", "category": "theater"},
    {"name": "Goodman Theatre", "category": "theater"},
    {"name": "Chicago Theatre", "category": "theater"},
    {"name": "CIBC Theatre", "category": "theater"},
    {"name": "Athenaeum Theatre", "category": "theater"},
    {"name": "Auditorium Theatre", "category": "theater"},
    {"name": "Cadillac Palace Theatre", "category": "theater"},
    {"name": "Ambassador Theatre Chicago", "category": "theater"},
    {"name": "Ford Center for the Performing Arts Oriental Theatre", "category": "theater"},
    # ===== THEATERS - OFF-BROADWAY & INDEPENDENT =====
    {"name": "Court Theatre", "category": "theater"},
    {"name": "Lookingglass Theatre Company", "category": "theater"},
    {"name": "TimeLine Theatre Company", "category": "theater"},
    {"name": "American Blues Theater", "category": "theater"},
    {"name": "Broken Nose Theatre", "category": "theater"},
    {"name": "A Red Orchid Theatre", "category": "theater"},
    {"name": "Trap Door Theatre", "category": "theater"},
    {"name": "Strawdog Theatre Company", "category": "theater"},
    {"name": "Raven Theatre", "category": "theater"},
    {"name": "Silk Road Rising", "category": "theater"},
    {"name": "Sideshow Theatre Company", "category": "theater"},
    {"name": "Jackalope Theatre Company", "category": "theater"},
    {"name": "Steep Theatre Company", "category": "theater"},
    {"name": "Rivendell Theatre Ensemble", "category": "theater"},
    {"name": "Hypocrites Theatre", "category": "theater"},
    {"name": "Bailiwick Chicago", "category": "theater"},
    # ===== COMEDY CLUBS & IMPROV =====
    {"name": "Second City", "category": "comedy"},
    {"name": "iO Theater", "category": "comedy"},
    {"name": "Zanies Chicago", "category": "comedy"},
    {"name": "The Laugh Factory", "category": "comedy"},
    {"name": "Comedians You Should Know", "category": "comedy"},
    {"name": "Laugh Out Loud Comedy Club", "category": "comedy"},
    {"name": "Comedy Sportz Chicago", "category": "comedy"},
    {"name": "Barrel of Laughs", "category": "comedy"},
    {"name": "The Upright Citizens Brigade Theatre", "category": "comedy"},
    {"name": "Annoyance Theatre", "category": "comedy"},
    # ===== MUSIC VENUES - CONCERT HALLS & SYMPHONIES =====
    {"name": "Chicago Symphony Orchestra Hall", "category": "music"},
    {"name": "Lyric Opera of Chicago", "category": "music"},
    {"name": "Ravinia Festival", "category": "music"},
    {"name": "Chicago Cultural Center", "category": "music"},
    {"name": "Harris Theater for Music and Dance", "category": "music"},
    {"name": "Jay Pritzker Pavilion", "category": "music"},
    {"name": "Civic Opera House", "category": "music"},
    # ===== MUSIC VENUES - MAJOR ROCK/POP VENUES =====
    {"name": "Congress Theater", "category": "music"},
    {"name": "Byline Bank Aragon Ballroom", "category": "music"},
    {"name": "Riviera Theatre", "category": "music"},
    {"name": "The Vic Theatre", "category": "music"},
    {"name": "Metro Chicago", "category": "music"},
    {"name": "House of Blues Chicago", "category": "music"},
    {"name": "Allstate Arena", "category": "music"},
    {"name": "United Center", "category": "music"},
    {"name": "Radius Chicago", "category": "music"},
    # ===== MUSIC VENUES - MID-SIZE & ROCK CLUBS (THE KEY ONES YOU MENTIONED) =====
    {"name": "Thalia Hall", "category": "music"},
    {"name": "Chop Shop", "category": "music"},
    {"name": "Den Theatre", "category": "music"},
    {"name": "SPACE Chicago", "category": "music"},
    {"name": "Bottom Lounge", "category": "music"},
    {"name": "Smartbar", "category": "music"},
    {"name": "Concord Music Hall", "category": "music"},
    {"name": "Park West", "category": "music"},
    {"name": "Abbey Pub", "category": "music"},
    {"name": "Schubas Tavern", "category": "music"},
    {"name": "Roscoe's Tavern", "category": "music"},
    {"name": "Brighton Bar", "category": "music"},
    {"name": "Pony Datz Nightclub", "category": "music"},
    {"name": "Coliseum Events", "category": "music"},
    # ===== MUSIC VENUES - ADDITIONAL HIGHLY-RATED SPOTS =====
    {"name": "The Hideout", "category": "music"},
    {"name": "The Salt Shed", "category": "music"},
    {"name": "Lincoln Hall", "category": "music"},
    {"name": "Subterranean", "category": "music"},
    {"name": "The Empty Bottle", "category": "music"},
    {"name": "Outset", "category": "music"},
    {"name": "Bookclub Chicago", "category": "music"},
    {"name": "Martyrs'", "category": "music"},
    {"name": "The Hive On Hubbard", "category": "music"},
    {"name": "Candlelight Concerts", "category": "music"},
    # ===== MUSIC VENUES - JAZZ, BLUES & SMALL CLUBS =====
    {"name": "Green Mill Jazz Club", "category": "music"},
    {"name": "Blue Chicago", "category": "music"},
    {"name": "Kingston Mines", "category": "music"},
    {"name": "Rosa's Lounge", "category": "music"},
    {"name": "Buddy Guy's Legends", "category": "music"},
    {"name": "Jazz Record Mart", "category": "music"},
    {"name": "The Velvet Lounge", "category": "music"},
    {"name": "Andy's Jazz Club", "category": "music"},
    {"name": "Jazz Showcase", "category": "music"},
    {"name": "HotHouse Chicago", "category": "music"},
    {"name": "Constellation", "category": "music"},
    # ===== MUSIC VENUES - ELECTRONIC & EXPERIMENTAL =====
    {"name": "Spybar", "category": "music"},
    {"name": "Smart Bar", "category": "music"},
    # ===== MUSIC VENUES - SMALLER VENUES & CAFES =====
    {"name": "Logan Theatre", "category": "music"},
    {"name": "Mayne Stage", "category": "music"},
    {"name": "Uncommon Ground", "category": "music"},
    {"name": "Fitzgerald's", "category": "music"},
    {"name": "City Winery Chicago", "category": "music"},
    {"name": "Lacuna Lofts", "category": "music"},
    # ===== CINEMAS & MOVIE THEATERS =====
    {"name": "Music Box Theatre", "category": "cinema"},
    {"name": "Landmark Theatres Century Center", "category": "cinema"},
    {"name": "Alamo Drafthouse Chicago", "category": "cinema"},
    {"name": "ArcLight Cinemas Chicago", "category": "cinema"},
    {"name": "Portage Theater", "category": "cinema"},
    {"name": "The Regal", "category": "cinema"},
    # ===== MUSEUMS WITH PERFORMANCE SPACES =====
    {"name": "Art Institute of Chicago", "category": "museum"},
    {"name": "Museum of Contemporary Art Chicago", "category": "museum"},
    {"name": "Field Museum", "category": "museum"},
    {"name": "Adler Planetarium", "category": "museum"},
    {"name": "Shedd Aquarium", "category": "museum"},
    {"name": "Chicago History Museum", "category": "museum"},
    {"name": "DuSable Museum of African American History", "category": "museum"},
    # ===== DANCE & PERFORMANCE VENUES =====
    {"name": "Hubbard Street Dance Chicago", "category": "theater"},
    {"name": "Joffre Ballet Chicago", "category": "theater"},
    {"name": "Remy Dance Center", "category": "theater"},
    {"name": "Links Hall", "category": "theater"},
    {"name": "Mana Contemporary Chicago", "category": "theater"},
    # ===== EVENT SPACES & MULTI-USE VENUES =====
    {"name": "Navy Pier", "category": "other"},
    {"name": "McCormick Place", "category": "other"},
    {"name": "Morgan Manufacturing", "category": "other"},
    {"name": "Artifact Events", "category": "other"},
    {"name": "Ignite Glass Studios", "category": "other"},
    {"name": "Bridgeport Art Center", "category": "other"},
    {"name": "Zhou B Art Center", "category": "other"},
    {"name": "Wicker Park Arts Center", "category": "other"},
]


def get_venues_by_category(category: str) -> list[dict]:
    """Get all venues in a specific category."""
    return [v for v in CHICAGO_VENUES if v["category"] == category]


def get_all_venue_names() -> list[str]:
    """Get all venue names."""
    return [v["name"] for v in CHICAGO_VENUES]
