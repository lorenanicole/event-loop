"""Categorizing an event title by embedding similarity, where rules are silent.

This is the measured answer to "should we use similarity instead of hardcoded
rules?", and the answer is neither-exactly: use the rules first, and use
similarity only where they say nothing and only when it is confident.

Two different questions were tested, and they came out differently.

Mapping one category LABEL to another ("Arts & Theatre" -> Theater) does not
work by similarity at all, because it ranks the wrong answer above the right
one - see the header of `shared.categories`. That mapping stays a table.

Classifying a TITLE is a better fit, because a title carries far more signal
than a two-word label. Measured over the 69 uncategorized TimeOut events:

    keyword rules and cosine agreed                28
    they disagreed                                  7
    only cosine offered anything at all            34

So cosine reaches titles the rules cannot: "Drunk Shakespeare Chicago" ->
Theater, "Renegade Craft Fair" -> Shopping, "Hot Chocolate Run" -> Sports,
"Oktoberfestiversary" -> Food & Drink. None of those contains a keyword.

But it is confidently wrong on its own: "Night of 1,000 Jack-o'-Lanterns" ->
Film, "The Odyssey Reimagined" -> Karaoke/Trivia/Open Mics, "Jonas Brothers"
-> Film, "Lee Miller: Fearless" -> Karaoke/Trivia/Open Mics. It has no way to
say "I do not know" - it always returns its nearest neighbour, however far
away that is.

The score is what separates the two cases. Everything it got right scored
roughly 0.35 and up; the bad answers sat at 0.25 and below, because they are
nearest-neighbours-by-default rather than actual matches. Hence
`SIMILARITY_FLOOR`: below it, the honest answer is no category.

Where the rules disagree with cosine, the rules win - they were written
against specific observed titles and are exact, and "Chicago Art Fair" is
better served by Arts (rules) than Shopping (cosine).

Scored against the labelled set, which is the point - every number here comes
from `evaluate_categorization.py` rather than from an impression:

    strategy                coverage   precision   correct
    keyword rules only          56%        94%       53%
    semantic only (0.45)        39%        88%       34%
    hybrid (0.45)               65%        95%       61%

Both halves earn their place. The hybrid beats the rules on coverage and
precision at once, so the model is not decoration. And an ablation that
removes the keyword vocabulary - leaving the model to carry it - drops the
hybrid from 61% correct to 42%, so the word lists are not bloat either. The
two cover different things: rules know that "Oktoberfest" is a beer festival,
the model knows that "Drunk Shakespeare Chicago" is theater.
"""

import logging

logger = logging.getLogger(__name__)

MODEL_NAME = "minishlab/potion-base-8M"

# Below this, a nearest neighbour is not a match.
#
# Chosen by sweeping it against the labelled set - `evaluate_categorization.py
# --sweep`, 62 hand-labelled titles - not by eye:
#
#   floor   hybrid coverage   hybrid precision
#   0.15          94%               78%
#   0.25          77%               88%
#   0.35          69%               91%
#   0.45          65%               95%
#   0.55          60%               95%
#
# 0.45 is where the hybrid beats the keyword rules alone on BOTH axes - 65%
# coverage against 56%, and 95% precision against 94% - so adopting it costs
# nothing and labels another 9% of events. Lowering it to 0.15 labels 94% but
# gets a fifth of them wrong, which is the wrong trade here: a wrong category
# files an event under a filter nobody expects and hides it from the one they
# would use, so declining is better than guessing.
SIMILARITY_FLOOR = 0.45

# Phrases that describe each parent category, rather than its bare name.
# "Arts" alone is a poor anchor - a two-word label has little to embed - while
# a handful of phrases describes the region of the space actually meant.
CATEGORY_EXEMPLARS: dict[str, list[str]] = {
    "Music": ["live music concert", "band playing", "dj set", "jazz show", "album release show"],
    "Theater": [
        "stage play",
        "theater performance",
        "musical theatre",
        "ballet",
        "shakespeare production",
    ],
    "Arts": [
        "art exhibition",
        "gallery show",
        "museum exhibit",
        "painting sculpture",
        "photography retrospective",
    ],
    "Comedy": ["stand up comedy", "comedy show", "improv night"],
    "Film": ["film screening", "movie night", "cinema"],
    "Community": ["neighborhood meeting", "community gathering", "volunteer day", "town hall"],
    "Tech / Educational": [
        "lecture",
        "panel discussion",
        "workshop class",
        "science talk",
        "author reading",
    ],
    "Health & Wellness": ["yoga class", "meditation", "wellness fitness"],
    "Food & Drink": ["food festival", "beer tasting", "restaurant dinner", "oktoberfest"],
    "Sports": ["marathon race", "basketball game", "running 5k"],
    "LGBTQ": ["pride event", "drag show", "queer party"],
    "Karaoke/Trivia/Open Mics": ["karaoke night", "trivia quiz", "open mic"],
    "Holiday & Seasonal": [
        "halloween haunted house",
        "christmas holiday lights",
        "costume party",
        "day of the dead",
    ],
    "Festival": ["street festival", "multi day festival", "block party"],
    "Shopping": ["vintage market", "craft fair", "makers market"],
}

_model = None
_exemplar_vectors = None
_exemplar_owners: list[str] = []


def _load():
    """Load the model and encode the exemplars once.

    Lazily, and tolerantly: this is an enrichment, so a missing model must
    leave the rules-based path working rather than break a scrape.
    """
    global _model, _exemplar_vectors, _exemplar_owners  # noqa: PLW0603
    if _exemplar_vectors is not None:
        return True
    try:
        import numpy as np
        from model2vec import StaticModel
    except ImportError:
        logger.info("model2vec unavailable; semantic categorization disabled")
        return False
    try:
        _model = StaticModel.from_pretrained(MODEL_NAME)
        phrases, owners = [], []
        for parent, exemplars in CATEGORY_EXEMPLARS.items():
            for phrase in exemplars:
                phrases.append(phrase)
                owners.append(parent)
        vectors = _model.encode(phrases)
        _exemplar_vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
        _exemplar_owners = owners
        return True
    except Exception as exc:
        logger.warning("semantic categorization unavailable: %s", exc)
        _exemplar_vectors = None
        return False


def semantic_category(title: str | None) -> tuple[str, float] | None:
    """The closest parent category to this title, and how close, or None.

    Returns None when nothing clears `SIMILARITY_FLOOR`. That is the point:
    the model always has a nearest neighbour, and reporting one regardless of
    distance is what produces "Jonas Brothers -> Film".
    """
    if not title or not title.strip():
        return None
    if not _load():
        return None

    import numpy as np

    vector = _model.encode([title])
    vector = vector / np.linalg.norm(vector, axis=1, keepdims=True)
    scores = (vector @ _exemplar_vectors.T)[0]
    best = int(np.argmax(scores))
    score = float(scores[best])
    if score < SIMILARITY_FLOOR:
        return None
    return _exemplar_owners[best], score
