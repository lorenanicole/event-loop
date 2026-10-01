"""
Comprehensive list of Chicago entertainment venues.
Used as seeds for Nominatim venue search and SerpAPI website discovery.
"""

CHICAGO_VENUES = [
    # Theaters - Broadway & Major
    {"name": "Steppenwolf Theatre Company", "category": "theater"},
    {"name": "Goodman Theatre", "category": "theater"},
    {"name": "Chicago Theatre", "category": "theater"},
    {"name": "CIBC Theatre", "category": "theater"},
    {"name": "Athenaeum Theatre", "category": "theater"},
    {"name": "Auditorium Theatre", "category": "theater"},
    {"name": "Cadillac Palace Theatre", "category": "theater"},
    {"name": "Ambassador Theatre Chicago", "category": "theater"},
    {"name": "Ford Center for the Performing Arts Oriental Theatre", "category": "theater"},
    {"name": "Joffre Ballet Chicago", "category": "theater"},

    # Theaters - Off-Broadway & Independent
    {"name": "Court Theatre", "category": "theater"},
    {"name": "Lookingglass Theatre Company", "category": "theater"},
    {"name": "TimeLine Theatre Company", "category": "theater"},
    {"name": "American Blues Theater", "category": "theater"},
    {"name": "Broken Nose Theatre", "category": "theater"},
    {"name": "A Red Orchid Theatre", "category": "theater"},
    {"name": "Trap Door Theatre", "category": "theater"},
    {"name": "Strawdog Theatre Company", "category": "theater"},

    # Comedy Clubs
    {"name": "Second City", "category": "comedy"},
    {"name": "iO Theater", "category": "comedy"},
    {"name": "Zanies Chicago", "category": "comedy"},
    {"name": "The Laugh Factory", "category": "comedy"},
    {"name": "Comedians You Should Know", "category": "comedy"},
    {"name": "Laugh Out Loud Comedy Club", "category": "comedy"},
    {"name": "Comedy Store Chicago", "category": "comedy"},
    {"name": "Barrel of Laughs", "category": "comedy"},

    # Music Venues - Concert Halls
    {"name": "Chicago Symphony Orchestra Hall", "category": "music"},
    {"name": "Lyric Opera of Chicago", "category": "music"},
    {"name": "Ravinia Festival", "category": "music"},
    {"name": "Chicago Cultural Center", "category": "music"},
    {"name": "Harris Theater for Music and Dance", "category": "music"},
    {"name": "Jay Pritzker Pavilion", "category": "music"},

    # Music Venues - Rock & Pop
    {"name": "Congress Theater", "category": "music"},
    {"name": "Aragon Ballroom", "category": "music"},
    {"name": "Riviera Theatre", "category": "music"},
    {"name": "Vic Theatre", "category": "music"},
    {"name": "Metro Chicago", "category": "music"},
    {"name": "House of Blues Chicago", "category": "music"},
    {"name": "Allstate Arena", "category": "music"},
    {"name": "United Center", "category": "music"},
    {"name": "Chicago Coliseum", "category": "music"},
    {"name": "Radius Chicago", "category": "music"},

    # Music Venues - Blues, Jazz, Clubs
    {"name": "Green Mill Jazz Club", "category": "music"},
    {"name": "Blue Chicago", "category": "music"},
    {"name": "Kingston Mines", "category": "music"},
    {"name": "Rosa's Lounge", "category": "music"},
    {"name": "Buddy Guy's Legends", "category": "music"},
    {"name": "Jazz Record Mart", "category": "music"},
    {"name": "The Velvet Lounge", "category": "music"},
    {"name": "Andy's Jazz Club", "category": "music"},

    # Movie Palaces & Cinemas
    {"name": "Music Box Theatre", "category": "cinema"},
    {"name": "Landmark Theatres - Century Centre", "category": "cinema"},
    {"name": "Alamo Drafthouse Chicago", "category": "cinema"},
    {"name": "ArcLight Cinemas Chicago", "category": "cinema"},
    {"name": "Portage Theater", "category": "cinema"},
    {"name": "Riviera Cinemas", "category": "cinema"},

    # Museums with Performance Spaces
    {"name": "Art Institute of Chicago", "category": "museum"},
    {"name": "Museum of Contemporary Art Chicago", "category": "museum"},
    {"name": "Field Museum", "category": "museum"},
    {"name": "Adler Planetarium", "category": "museum"},
    {"name": "Shedd Aquarium", "category": "museum"},
    {"name": "Chicago History Museum", "category": "museum"},

    # Event Spaces & Auditoriums
    {"name": "Navy Pier", "category": "other"},
    {"name": "McCormick Place", "category": "other"},
    {"name": "Lacuna Lofts", "category": "other"},
    {"name": "Morgan Manufacturing", "category": "other"},
    {"name": "Morgan Ballroom", "category": "other"},
    {"name": "Lacuna Lofts - Lacuna Lofts Building", "category": "other"},
    {"name": "The Morgan Manufacturing", "category": "other"},

    # Dance Venues
    {"name": "Hubbard Street Dance Chicago", "category": "theater"},
    {"name": "Remy Dance Center", "category": "theater"},
    {"name": "Links Hall", "category": "theater"},

    # Additional Improv/Alternative
    {"name": "The Upright Citizens Brigade Theatre Chicago", "category": "comedy"},
    {"name": "Wicker Park Arts Center", "category": "other"},
    {"name": "Lacuna Lofts", "category": "other"},
]


def get_venues_by_category(category: str) -> list[dict]:
    """Get all venues in a specific category."""
    return [v for v in CHICAGO_VENUES if v["category"] == category]


def get_all_venue_names() -> list[str]:
    """Get all venue names."""
    return [v["name"] for v in CHICAGO_VENUES]
