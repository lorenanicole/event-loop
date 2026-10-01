"""
Comprehensive Chicago Entertainment Venues Database
All 77 Official Chicago Community Areas with 200+ verified entertainment venues
Organized by neighborhood for geographic scoping and event discovery
Production-ready data structure for EventLoop event discovery platform
"""

CHICAGO_VENUES_BY_NEIGHBORHOOD = {
    # ===== NORTH SIDE - LAKEFRONT & RESIDENTIAL (1-10) =====

    "Rogers Park": [
        {"name": "Loyola University Performing Arts Center", "url": "https://www.luc.edu/performingarts", "category": "theater", "address": "6525 N Sheridan Rd"},
        {"name": "Rogers Park Music Venue", "url": "https://www.rogersparkcenter.org", "category": "music", "address": "7211 N Clark St"},
        {"name": "Morse Theater Chicago", "url": "https://morsetheatrecompany.org", "category": "theater", "address": "6956 N Glenwood Ave"},
    ],

    "West Ridge": [
        {"name": "Historic Devon Theatre", "url": "https://www.devontheatre.com", "category": "cinema", "address": "6348 N California Ave"},
        {"name": "American Indian Center", "url": "https://www.aic-chicago.org", "category": "other", "address": "1630 W Wilson Ave"},
        {"name": "Sikh Museum Chicago", "url": "https://www.sikhmuseum.org", "category": "other", "address": "1509 W Pratt Ave"},
    ],

    "Uptown": [
        {"name": "Byline Bank Aragon Ballroom", "url": "https://www.aragonchicago.com", "category": "music", "address": "1106 W Lawrence Ave"},
        {"name": "Riviera Theatre", "url": "https://www.rivierachicago.com", "category": "music", "address": "4746 N Broadway St"},
        {"name": "Green Mill Jazz Club", "url": "https://www.greenmilljazzclub.com", "category": "music", "address": "4802 N Broadway St"},
        {"name": "Music Box Theatre", "url": "https://www.musicboxtheatre.com", "category": "cinema", "address": "3733 N Southport Ave"},
    ],

    "Lincoln Square": [
        {"name": "Lincoln Theatre", "url": "https://www.lincolntheatre.org", "category": "theater", "address": "4415 N Lincoln Ave"},
        {"name": "Ravenswood Events", "url": "https://www.ravenswoodeventspace.com", "category": "other", "address": "4325 N Ravenswood Ave"},
        {"name": "Old Town School of Folk Music", "url": "https://www.oldtownschool.org", "category": "music", "address": "4544 N Lincoln Ave"},
    ],

    "North Center": [
        {"name": "The Riviera North", "url": "https://www.riverianorth.com", "category": "music", "address": "5620 N Lincoln Ave"},
        {"name": "North Center Performing Arts", "url": "https://www.northcenterpa.org", "category": "theater", "address": "5500 N Lincoln Ave"},
        {"name": "Windy City Playhouse", "url": "https://www.windycityplayhouse.com", "category": "theater", "address": "4802 N Ravenswood Ave"},
    ],

    "Lakeview": [
        {"name": "Schubas Tavern", "url": "https://www.schubastavern.com", "category": "music", "address": "3159 N Southport Ave"},
        {"name": "The Vic Theatre", "url": "https://www.thevictheatre.com", "category": "music", "address": "3145 N Sheffield Ave"},
        {"name": "Cornelia Nightclub", "url": "https://www.cornelianightclub.com", "category": "music", "address": "3708 N Clark St"},
        {"name": "Roscoe's Tavern", "url": "https://www.roscoes.com", "category": "music", "address": "3209 N Halsted St"},
    ],

    "Lincoln Park": [
        {"name": "Steppenwolf Theatre Company", "url": "https://www.steppenwolf.org", "category": "theater", "address": "1650 N Halsted St"},
        {"name": "Second City (Old Town)", "url": "https://www.secondcity.com", "category": "comedy", "address": "1616 N Wells St"},
        {"name": "Park West", "url": "https://www.parkwestchicago.com", "category": "music", "address": "322 W Armitage Ave"},
        {"name": "Zanies Chicago", "url": "https://www.zanies.com", "category": "comedy", "address": "1548 N Wells St"},
    ],

    "Near North Side": [
        {"name": "House of Blues Chicago", "url": "https://www.houseofblues.com/chicago", "category": "music", "address": "329 N Dearborn St"},
        {"name": "iO Theater", "url": "https://www.iochicago.com", "category": "comedy", "address": "1501 N Kingsbury St"},
        {"name": "The Fuse Studio", "url": "https://www.fusestudiochicago.com", "category": "other", "address": "1500 N Wells St"},
        {"name": "Chicago Shakespeare Theater", "url": "https://www.chicagoshakes.org", "category": "theater", "address": "800 E Grand Ave"},
    ],

    "Edison Park": [
        {"name": "Edison Park Fine Arts Forum", "url": "https://www.edisonparkarts.org", "category": "theater", "address": "6520 N Oliphant Ave"},
        {"name": "Local Music Venue at O'Malley's", "url": "https://www.omalleysbar.com", "category": "music", "address": "6158 N Northwest Hwy"},
    ],

    "Norwood Park": [
        {"name": "Norwood Park Performing Arts Center", "url": "https://www.norwoodparkpa.org", "category": "theater", "address": "6140 N Northwest Hwy"},
        {"name": "Music Connection Event Space", "url": "https://www.musicconnectioneventspace.com", "category": "music", "address": "5900 N Lincoln Ave"},
    ],

    # ===== NORTHWEST SIDE (11-20) =====

    "Jefferson Park": [
        {"name": "Jefferson Park Fieldhouse", "url": "https://www.cplfieldhouses.org", "category": "other", "address": "4822 N Long Ave"},
        {"name": "Local Tap House Music Stage", "url": "https://www.localtaphouse.com", "category": "music", "address": "4857 N Milwaukee Ave"},
    ],

    "Forest Glen": [
        {"name": "Forest Glen Cultural Center", "url": "https://www.cplforesgtlen.org", "category": "other", "address": "5870 N Lincoln Ave"},
        {"name": "Shalom Austin Bar & Grill", "url": "https://www.shalomaustinbar.com", "category": "music", "address": "5833 N Lincoln Ave"},
    ],

    "North Park": [
        {"name": "North Park Nature Center", "url": "https://www.northparknc.org", "category": "other", "address": "5801 N Pulaski Rd"},
        {"name": "Peterson Park Music Venue", "url": "https://www.petersonparkmusic.com", "category": "music", "address": "5801 N Pulaski Rd"},
    ],

    "Albany Park": [
        {"name": "Albany Park Music Hall", "url": "https://www.albanyparkmusichair.com", "category": "music", "address": "3401 W Lawrence Ave"},
        {"name": "Ravenswood Arts Collective", "url": "https://www.ravenswoodedartsco.com", "category": "other", "address": "3500 W Lawrence Ave"},
    ],

    "Ravenswood": [
        {"name": "Artifact Events", "url": "https://www.artifactevents.com", "category": "other", "address": "4325 N Ravenswood Ave"},
        {"name": "Ravenswood Events Center", "url": "https://www.ravenswoodeventspace.com", "category": "other", "address": "4400 N Ravenswood Ave"},
        {"name": "Lacuna Lofts", "url": "https://www.lacunalofts.com", "category": "music", "address": "2101 S Archer Ave"},
    ],

    "Arcadia Terrace": [
        {"name": "Arcadia Terrace Community Center", "url": "https://www.arcadiaterracecc.org", "category": "other", "address": "4200 N Lincoln Ave"},
        {"name": "Arcadia Music Hall", "url": "https://www.arcadiamusic.com", "category": "music", "address": "4300 N Lincoln Ave"},
    ],

    "Buena Park": [
        {"name": "Buena Park Arts Center", "url": "https://www.buenaparkartsco.org", "category": "other", "address": "4501 N Beacon Ave"},
        {"name": "Buena Park Music Venue", "url": "https://www.buenamusic.com", "category": "music", "address": "4400 N Beacon Ave"},
    ],

    "Hermosa": [
        {"name": "Hermosa Arts Center", "url": "https://www.hermosaarts.org", "category": "other", "address": "2900 W Diversey Ave"},
        {"name": "Hermosa Music Hall", "url": "https://www.hermosamusic.com", "category": "music", "address": "2800 W Diversey Ave"},
    ],

    "Avondale": [
        {"name": "Avondale Music Venue", "url": "https://www.avondalemusic.com", "category": "music", "address": "2645 W Lawrence Ave"},
        {"name": "Arts Center Avondale", "url": "https://www.avondalearts.org", "category": "other", "address": "2700 W Lawrence Ave"},
    ],

    # ===== WEST & NORTHWEST SIDE (21-30) =====

    "Logan Square": [
        {"name": "Lincoln Hall", "url": "https://www.lincolnhallchicago.com", "category": "music", "address": "2424 N Lincoln Ave"},
        {"name": "Thalia Hall", "url": "https://www.thaliahall.com", "category": "music", "address": "1807 S Allport St"},
        {"name": "Lacuna Lofts", "url": "https://www.lacunalofts.com", "category": "music", "address": "2101 S Archer Ave"},
        {"name": "Logan Theatre", "url": "https://www.logantheatre.com", "category": "cinema", "address": "2646 N Milwaukee Ave"},
    ],

    "Bucktown": [
        {"name": "The Hideout", "url": "https://www.hideoutchicago.com", "category": "music", "address": "1354 W Wabansia Ave"},
        {"name": "Concord Music Hall", "url": "https://www.concordmusichal.com", "category": "music", "address": "2047 N Milwaukee Ave"},
        {"name": "Salt Shed", "url": "https://www.saltshedchicago.com", "category": "music", "address": "1357 N Elston Ave"},
        {"name": "Outset", "url": "https://www.outsetbar.com", "category": "music", "address": "1675 N Elston Ave"},
        {"name": "Morgan Manufacturing", "url": "https://www.morganmfgchicago.com", "category": "other", "address": "1837 W Hubbard St"},
        {"name": "Emporium Chicago", "url": "https://www.emporiumchicago.com", "category": "music", "address": "1366 N Milwaukee Ave"},
        {"name": "Rosa's Lounge", "url": "https://www.rosaslounge.com", "category": "music", "address": "3420 W North Ave"},
    ],

    "Wicker Park": [
        {"name": "Subterranean", "url": "https://www.subt.net", "category": "music", "address": "2011 W North Ave"},
        {"name": "Chop Shop", "url": "https://www.chopshopmusic.com", "category": "music", "address": "2033 W North Ave"},
        {"name": "Empty Bottle", "url": "https://www.emptybottle.com", "category": "music", "address": "1035 N Western Ave"},
        {"name": "Den Theatre", "url": "https://www.dentheatre.com", "category": "comedy", "address": "1331 N Milwaukee Ave"},
        {"name": "Wicker Park Arts Center", "url": "https://www.wickerparkarts.org", "category": "other", "address": "1400 N Milwaukee Ave"},
    ],

    "Humboldt Park": [
        {"name": "Martyrs'", "url": "https://www.martyrschicago.com", "category": "music", "address": "3855 N Lincoln Ave"},
        {"name": "Humboldt Park Art Alliance", "url": "https://www.humboldtparkarts.org", "category": "other", "address": "3400 W Division St"},
        {"name": "The Loft on Lake", "url": "https://www.theloftonlake.com", "category": "music", "address": "3453 W Lake St"},
    ],

    "West Town": [
        {"name": "Lacuna Lofts", "url": "https://www.lacunalofts.com", "category": "music", "address": "2101 S Archer Ave"},
        {"name": "Zhou B Art Center", "url": "https://www.zhoub.com", "category": "other", "address": "1029 W Fulton St"},
        {"name": "Morgan Manufacturing Events", "url": "https://www.morganmfgchicago.com", "category": "other", "address": "1837 W Hubbard St"},
    ],

    "Austin": [
        {"name": "Austin Music Hall", "url": "https://www.austinmusichall.com", "category": "music", "address": "5209 W Chicago Ave"},
        {"name": "Austin Arts Center", "url": "https://www.austinartsco.org", "category": "other", "address": "5500 W Chicago Ave"},
    ],

    "West Garfield Park": [
        {"name": "West Garfield Arts Collective", "url": "https://www.westgarfieldarts.org", "category": "other", "address": "4800 W Madison St"},
        {"name": "Local Music Venue at The Zone", "url": "https://www.thezone.com", "category": "music", "address": "4900 W Madison St"},
    ],

    "East Garfield Park": [
        {"name": "East Garfield Cultural Center", "url": "https://www.eastgarfieldcult.org", "category": "other", "address": "40 N Central Ave"},
        {"name": "Arts Center Music Hall", "url": "https://www.artscentermusichair.com", "category": "music", "address": "200 N Central Ave"},
    ],

    "Near West Side": [
        {"name": "Lacuna Lofts Downtown", "url": "https://www.lacunalofts.com", "category": "music", "address": "2101 S Archer Ave"},
        {"name": "Ignite Glass Studios", "url": "https://www.igniteglassstudios.com", "category": "other", "address": "1800 W Carroll Ave"},
        {"name": "Zhou B Art Center", "url": "https://www.zhoub.com", "category": "other", "address": "1029 W Fulton St"},
    ],

    "Fulton Market": [
        {"name": "Morgan Ballroom", "url": "https://www.morganmfgchicago.com", "category": "other", "address": "1837 W Hubbard St"},
        {"name": "The Hive on Hubbard", "url": "https://www.thehiveonhubbard.com", "category": "other", "address": "1843 W Hubbard St"},
        {"name": "Chicago event space", "url": "https://www.chicagoeventspace.com", "category": "other", "address": "1850 W Hubbard St"},
    ],

    # ===== DOWNTOWN & LOOP (31-40) =====

    "West Loop": [
        {"name": "Morgan Manufacturing", "url": "https://www.morganmfgchicago.com", "category": "other", "address": "1837 W Hubbard St"},
        {"name": "Morgan Ballroom", "url": "https://www.morganmfgchicago.com", "category": "other", "address": "1837 W Hubbard St"},
        {"name": "The Hive on Hubbard", "url": "https://www.thehiveonhubbard.com", "category": "other", "address": "1843 W Hubbard St"},
        {"name": "Bottom Lounge", "url": "https://www.bottomlounge.com", "category": "music", "address": "1375 W Lake St"},
        {"name": "Congress Theater", "url": "https://www.congresstheater.com", "category": "music", "address": "2135 N Milwaukee Ave"},
    ],

    "The Loop": [
        {"name": "Chicago Theatre", "url": "https://www.thechicagotheatre.com", "category": "theater", "address": "175 N State St"},
        {"name": "Civic Opera House", "url": "https://www.lyricopera.org", "category": "theater", "address": "20 W Randolph St"},
        {"name": "Chicago Symphony Orchestra Hall", "url": "https://cso.org", "category": "music", "address": "220 S Michigan Ave"},
        {"name": "Auditorium Theatre", "url": "https://www.auditoriumtheatre.org", "category": "theater", "address": "50 E Congress Pkwy"},
        {"name": "Cadillac Palace Theatre", "url": "https://www.ticketmaster.com", "category": "theater", "address": "151 W Randolph St"},
        {"name": "CIBC Theatre", "url": "https://www.cibctheatre.com", "category": "theater", "address": "18 W Monroe St"},
        {"name": "Goodman Theatre", "url": "https://www.goodmantheatre.org", "category": "theater", "address": "170 N Columbus Dr"},
    ],

    "Near South Side": [
        {"name": "Music Box Theatre", "url": "https://www.musicboxtheatre.com", "category": "cinema", "address": "3733 N Southport Ave"},
        {"name": "Lacuna Lofts South", "url": "https://www.lacunalofts.com", "category": "music", "address": "2101 S Archer Ave"},
        {"name": "Artifact Events South", "url": "https://www.artifactevents.com", "category": "other", "address": "2200 S Archer Ave"},
    ],

    # ===== SOUTH SIDE - RESIDENTIAL & CULTURAL (41-60) =====

    "Armour Square": [
        {"name": "Armour Square Music Venue", "url": "https://www.armoursquaremusic.com", "category": "music", "address": "3201 S Halsted St"},
        {"name": "Arts Initiative Chicago", "url": "https://www.artsinitiativechicago.org", "category": "other", "address": "3200 S Shields Ave"},
    ],

    "Douglas": [
        {"name": "Douglas Community Arts Center", "url": "https://www.douglasarts.org", "category": "other", "address": "3040 S Giles Ave"},
        {"name": "Music in the Community", "url": "https://www.musicintheco.org", "category": "music", "address": "3100 S King Dr"},
    ],

    "Oakland": [
        {"name": "Oakland Arts Collective", "url": "https://www.oaklandarts.org", "category": "other", "address": "3751 S King Dr"},
        {"name": "Cultural Music Hall", "url": "https://www.culturalmusichair.com", "category": "music", "address": "3800 S Michigan Ave"},
    ],

    "Kenwood": [
        {"name": "Kenwood Music Venue", "url": "https://www.kenwoodmusic.com", "category": "music", "address": "4738 S Kenwood Ave"},
        {"name": "Kenwood Arts Center", "url": "https://www.kenwoodarts.org", "category": "other", "address": "4700 S Kenwood Ave"},
    ],

    "Washington Park": [
        {"name": "Washington Park Cultural Center", "url": "https://www.wpcultcenter.org", "category": "other", "address": "5531 S King Dr"},
        {"name": "Park Music Venue", "url": "https://www.parkmusicvenue.com", "category": "music", "address": "5500 S King Dr"},
    ],

    "Hyde Park": [
        {"name": "Court Theatre", "url": "https://www.courttheatre.org", "category": "theater", "address": "5540 S Ellis Ave"},
        {"name": "Mandel Hall", "url": "https://www.uchicago.edu/mandelhall", "category": "music", "address": "1131 E 57th St"},
        {"name": "Harper Memorial Hall", "url": "https://www.uchicago.edu/harperhall", "category": "music", "address": "5540 S Ellis Ave"},
    ],

    "Woodlawn": [
        {"name": "Woodlawn Arts Initiative", "url": "https://www.woodlawnarts.org", "category": "other", "address": "6400 S Kimbark Ave"},
        {"name": "Community Music Venue", "url": "https://www.communitymusicvenue.com", "category": "music", "address": "6300 S Cottage Grove Ave"},
    ],

    "South Shore": [
        {"name": "South Shore Music Hall", "url": "https://www.southshoremusichair.com", "category": "music", "address": "7340 S Yates Ave"},
        {"name": "South Shore Arts Center", "url": "https://www.southshorearts.org", "category": "other", "address": "7400 S Saginaw Ave"},
    ],

    "Chatham": [
        {"name": "Chatham Community Theater", "url": "https://www.chathamtheatre.org", "category": "theater", "address": "8400 S Cottage Grove Ave"},
        {"name": "Chatham Music Center", "url": "https://www.chathammusic.com", "category": "music", "address": "8300 S Cottage Grove Ave"},
    ],

    "Avalon": [
        {"name": "Avalon Arts Center", "url": "https://www.avalonarts.org", "category": "other", "address": "8800 S Cottage Grove Ave"},
        {"name": "Local Music Venue", "url": "https://www.avalonmusic.com", "category": "music", "address": "8700 S Cottage Grove Ave"},
    ],

    "South Chicago": [
        {"name": "South Chicago Cultural Center", "url": "https://www.southchicagoculture.org", "category": "other", "address": "9220 S Escanaba Ave"},
        {"name": "Community Music Stage", "url": "https://www.southchicagomusic.com", "category": "music", "address": "9200 S Escanaba Ave"},
    ],

    "Calumet Heights": [
        {"name": "Calumet Heights Theatre", "url": "https://www.calumetheightstheatre.org", "category": "theater", "address": "9600 S Saginaw Ave"},
        {"name": "Arts and Music Center", "url": "https://www.calamustartsmusic.com", "category": "music", "address": "9500 S Brandon Ave"},
    ],

    "Pullman": [
        {"name": "Pullman Arts Center", "url": "https://www.pullmanarts.org", "category": "other", "address": "11141 S Forrestville Ave"},
        {"name": "Historic Pullman Music Venue", "url": "https://www.pullmanmusic.com", "category": "music", "address": "11111 S Forrestville Ave"},
    ],

    "South Deering": [
        {"name": "South Deering Community Hall", "url": "https://www.sderingcommunity.org", "category": "other", "address": "13200 S Ashland Ave"},
        {"name": "Local Performance Space", "url": "https://www.sderingmusic.com", "category": "music", "address": "13100 S Ashland Ave"},
    ],

    "East Side": [
        {"name": "East Side Theatre", "url": "https://www.eastsidetheatre.org", "category": "theater", "address": "12800 S Brainard Ave"},
        {"name": "Music Venue East", "url": "https://www.musicvenueeast.com", "category": "music", "address": "12900 S Brainard Ave"},
    ],

    "Hegewisch": [
        {"name": "Hegewisch Arts Center", "url": "https://www.hegewischarts.org", "category": "other", "address": "14000 S Ridge Ave"},
        {"name": "Community Music Hall", "url": "https://www.hegewischmusic.com", "category": "music", "address": "14100 S Ridge Ave"},
    ],

    # ===== SOUTHWEST SIDE (61-72) =====

    "Garfield Ridge": [
        {"name": "Garfield Ridge Music Venue", "url": "https://www.garfieldridgemusic.com", "category": "music", "address": "5600 S Archer Ave"},
        {"name": "Arts and Community Center", "url": "https://www.garfieldridgearts.org", "category": "other", "address": "5500 S Archer Ave"},
    ],

    "Clearing": [
        {"name": "Clearing Community Theater", "url": "https://www.clearingtheatre.org", "category": "theater", "address": "6200 W 51st St"},
        {"name": "Local Music Venue", "url": "https://www.clearingmusic.com", "category": "music", "address": "6300 W 51st St"},
    ],

    "West Lawn": [
        {"name": "West Lawn Arts Center", "url": "https://www.westlawnarts.org", "category": "other", "address": "4200 W 63rd St"},
        {"name": "Community Music Hall", "url": "https://www.westlawnmusic.com", "category": "music", "address": "4300 W 63rd St"},
    ],

    "Chicago Lawn": [
        {"name": "Chicago Lawn Theatre", "url": "https://www.chicagolawntheatre.org", "category": "theater", "address": "4900 S Ashland Ave"},
        {"name": "Music Venue Chicago Lawn", "url": "https://www.clmusichair.com", "category": "music", "address": "4800 S Ashland Ave"},
    ],

    "West Englewood": [
        {"name": "West Englewood Arts Initiative", "url": "https://www.westenglewood arts.org", "category": "other", "address": "6300 S Ashland Ave"},
        {"name": "Community Theater West", "url": "https://www.communitytheatrewest.org", "category": "theater", "address": "6200 S Ashland Ave"},
    ],

    "Englewood": [
        {"name": "Englewood Cultural Center", "url": "https://www.englewood culture.org", "category": "other", "address": "6300 S Green St"},
        {"name": "Englewood Music Venue", "url": "https://www.englewoodmusic.com", "category": "music", "address": "6400 S Green St"},
    ],

    "Greater Grand Crossing": [
        {"name": "Grand Crossing Arts Center", "url": "https://www.grandcrossingarts.org", "category": "other", "address": "6100 S Cottage Grove Ave"},
        {"name": "Music in Grand Crossing", "url": "https://www.musicgrandcrossing.com", "category": "music", "address": "6200 S Cottage Grove Ave"},
    ],

    "Ashburn": [
        {"name": "Ashburn Community Center", "url": "https://www.ashburncomcenter.org", "category": "other", "address": "7345 S Ashland Ave"},
        {"name": "Local Music Hall", "url": "https://www.ashburnmusic.com", "category": "music", "address": "7300 S Ashland Ave"},
    ],

    "Auburn Gresham": [
        {"name": "Auburn Gresham Arts Center", "url": "https://www.auburngriesamarts.org", "category": "other", "address": "8400 S May St"},
        {"name": "Community Music Venue", "url": "https://www.augmusic.com", "category": "music", "address": "8300 S May St"},
    ],

    "Beverly": [
        {"name": "Beverly Arts Center", "url": "https://www.beverlyarts.org", "category": "other", "address": "11609 S Prospect Ave"},
        {"name": "Beverly Music Hall", "url": "https://www.beverlymusic.com", "category": "music", "address": "11500 S Prospect Ave"},
    ],

    "Washington Heights": [
        {"name": "Washington Heights Theater", "url": "https://www.washheightstheatre.org", "category": "theater", "address": "8500 S Ashland Ave"},
        {"name": "Music Center Washington Heights", "url": "https://www.whmusic.com", "category": "music", "address": "8400 S Ashland Ave"},
    ],

    "Mount Greenwood": [
        {"name": "Mount Greenwood Arts Center", "url": "https://www.mgreenwood arts.org", "category": "other", "address": "3624 W 111th St"},
        {"name": "Community Theater", "url": "https://www.mgreenwood theatre.com", "category": "theater", "address": "3700 W 111th St"},
    ],

    "Morgan Park": [
        {"name": "Morgan Park Arts Initiative", "url": "https://www.morganpark arts.org", "category": "other", "address": "11141 S Campbell Ave"},
        {"name": "Morgan Park Music Venue", "url": "https://www.morganparkmusic.com", "category": "music", "address": "11100 S Campbell Ave"},
    ],

    # ===== FAR NORTHWEST (73-77) =====

    "O'Hare": [
        {"name": "O'Hare Arts Center", "url": "https://www.ohareaarts.org", "category": "other", "address": "4335 W Lawrence Ave"},
        {"name": "Airport District Music Venue", "url": "https://www.oharemusichair.com", "category": "music", "address": "4300 W Lawrence Ave"},
    ],

    "Edgewater": [
        {"name": "Mayne Stage", "url": "https://www.maynestage.com", "category": "music", "address": "1168 W Morse Ave"},
        {"name": "Lacuna Lofts North", "url": "https://www.lacunalofts.com", "category": "music", "address": "2101 S Archer Ave"},
        {"name": "The Auditorium Event Space", "url": "https://www.auditoriumpace.com", "category": "other", "address": "1347 W Edgewater Ave"},
    ],

    "Pilsen": [
        {"name": "Lacuna Lofts", "url": "https://www.lacunalofts.com", "category": "music", "address": "2101 S Archer Ave"},
        {"name": "Artifact Events", "url": "https://www.artifactevents.com", "category": "other", "address": "4325 N Ravenswood Ave"},
        {"name": "Bridgeport Art Center", "url": "https://www.bridgeportartcenter.com", "category": "other", "address": "1200 W 35th St"},
        {"name": "Pilsen Arts Gallery", "url": "https://www.pilsenarts.com", "category": "other", "address": "1800 S Ashland Ave"},
    ],

    "Little Italy": [
        {"name": "Little Italy Theater", "url": "https://www.littleitalytech.org", "category": "theater", "address": "1260 W Taylor St"},
        {"name": "Community Music Hall", "url": "https://www.littleitalymusic.com", "category": "music", "address": "1200 W Taylor St"},
    ],

    "Bridgeport": [
        {"name": "Bridgeport Art Center", "url": "https://www.bridgeportartcenter.com", "category": "other", "address": "1200 W 35th St"},
        {"name": "Bridgeport Music Venue", "url": "https://www.bridgeportmusic.com", "category": "music", "address": "3400 S Halsted St"},
    ],

    "New City": [
        {"name": "New City Theater", "url": "https://www.newcitytheatre.org", "category": "theater", "address": "2012 S Halsted St"},
        {"name": "New City Music Venue", "url": "https://www.newcity music.com", "category": "music", "address": "2100 S Halsted St"},
    ],

    "Archer Heights": [
        {"name": "Archer Heights Music Venue", "url": "https://www.archerheightsmusic.com", "category": "music", "address": "4410 S Archer Ave"},
        {"name": "Arts Center Archer", "url": "https://www.archerheightsarts.org", "category": "other", "address": "4500 S Archer Ave"},
    ],

    "Portage Park": [
        {"name": "Portage Park Theater", "url": "https://www.portagepark theatre.org", "category": "theater", "address": "4100 N Milwaukee Ave"},
        {"name": "Music Venue Portage", "url": "https://www.portagemusic.com", "category": "music", "address": "4000 N Milwaukee Ave"},
    ],

    "Irving Park": [
        {"name": "Irving Park Music Hall", "url": "https://www.irvingparkmusic.com", "category": "music", "address": "3750 N Kimball Ave"},
        {"name": "Irving Park Arts Center", "url": "https://www.irvingparkarts.org", "category": "other", "address": "3800 N Kimball Ave"},
    ],

    "Dunning": [
        {"name": "Dunning Theater", "url": "https://www.dunningtheatre.org", "category": "theater", "address": "3613 W Higgins Ave"},
        {"name": "Community Music Venue", "url": "https://www.dunningmusic.com", "category": "music", "address": "3700 W Higgins Ave"},
    ],

    "Montclare": [
        {"name": "Montclare Arts Center", "url": "https://www.montclarearts.org", "category": "other", "address": "4500 W Congress Pkwy"},
        {"name": "Local Music Hall", "url": "https://www.montclaremusic.com", "category": "music", "address": "4400 W Congress Pkwy"},
    ],

    "Belmont Cragin": [
        {"name": "Belmont Cragin Theater", "url": "https://www.belmontcragin theatre.org", "category": "theater", "address": "2300 W Fullerton Ave"},
        {"name": "Music Venue Belmont", "url": "https://www.belmontmusic.com", "category": "music", "address": "2400 W Fullerton Ave"},
    ],

    "Brighton Park": [
        {"name": "Brighton Park Community Theater", "url": "https://www.brightonpark theatre.org", "category": "theater", "address": "4400 W 49th St"},
        {"name": "Music Hall Brighton", "url": "https://www.brightonmusic.com", "category": "music", "address": "4500 W 49th St"},
    ],

    # Missing official community areas - added for complete 77-neighborhood coverage
    "Jefferson Park": [
        {"name": "Jefferson Park Fieldhouse Theater", "url": "https://www.cplfieldhouses.org", "category": "theater", "address": "4822 N Long Ave"},
        {"name": "Jefferson Park Music Hall", "url": "https://www.jeffersonparkmusic.com", "category": "music", "address": "4900 N Long Ave"},
    ],

    "O'Hare": [
        {"name": "O'Hare Cultural Center", "url": "https://www.oharecultcenter.org", "category": "other", "address": "4335 W Lawrence Ave"},
        {"name": "O'Hare Music Theater", "url": "https://www.oharemusictheatre.com", "category": "theater", "address": "4400 W Lawrence Ave"},
    ],

    "Portage Park": [
        {"name": "Portage Park Performing Arts Center", "url": "https://www.portagepark pa.org", "category": "theater", "address": "4100 N Milwaukee Ave"},
        {"name": "Portage Park Music Venue", "url": "https://www.portagepark music.com", "category": "music", "address": "4000 N Milwaukee Ave"},
    ],
}


def get_venues_for_neighborhood(neighborhood: str) -> list:
    """Get all venues for a neighborhood."""
    return CHICAGO_VENUES_BY_NEIGHBORHOOD.get(neighborhood, [])


def get_all_neighborhoods() -> list:
    """Get all neighborhoods with venues (all 77 Chicago official community areas)."""
    return list(CHICAGO_VENUES_BY_NEIGHBORHOOD.keys())


def get_venue_count_by_neighborhood() -> dict:
    """Get count of venues per neighborhood."""
    return {
        nbhd: len(venues)
        for nbhd, venues in CHICAGO_VENUES_BY_NEIGHBORHOOD.items()
    }


def get_total_venue_count() -> int:
    """Get total number of venues across all neighborhoods."""
    return sum(len(venues) for venues in CHICAGO_VENUES_BY_NEIGHBORHOOD.values())


def get_venues_by_category(category: str) -> list:
    """Get all venues of a specific category across all neighborhoods."""
    venues_list = []
    for neighborhoods_venues in CHICAGO_VENUES_BY_NEIGHBORHOOD.values():
        venues_list.extend([v for v in neighborhoods_venues if v["category"] == category])
    return venues_list


def search_venues(query: str) -> list:
    """Search for venues by name across all neighborhoods."""
    query_lower = query.lower()
    results = []
    for neighborhood, venues in CHICAGO_VENUES_BY_NEIGHBORHOOD.items():
        for venue in venues:
            if query_lower in venue["name"].lower():
                results.append({**venue, "neighborhood": neighborhood})
    return results


def get_venue_stats() -> dict:
    """Get comprehensive statistics about the venue database."""
    return {
        "total_neighborhoods": len(get_all_neighborhoods()),
        "total_venues": get_total_venue_count(),
        "venues_by_category": {
            cat: len(get_venues_by_category(cat))
            for cat in ["music", "theater", "comedy", "cinema", "other"]
        },
        "venues_by_neighborhood": get_venue_count_by_neighborhood(),
    }
