"""Semantic search over the local events table.

Keyword search answers "which events contain this word". This answers "which
events are *about* this", which is what catches "foraging wild plants" for a
query of "plant workshops" - no shared keyword, same subject.

Uses model2vec static embeddings rather than a transformer: encoding is a token
lookup plus pooling, so there is no torch dependency, the whole corpus indexes
in well under a second, and a query costs a fraction of a millisecond.
"""

import logging
import threading
from typing import Optional

import numpy as np
from sqlalchemy import select

from shared.database import EventModel, upcoming_events_filter

logger = logging.getLogger(__name__)

MODEL_NAME = "minishlab/potion-base-8M"

# Cosine floor for a match to count as related at all. Below this the nearest
# neighbour is just the least-unrelated row in the table, not a real result.
MIN_SIMILARITY = 0.25


class SemanticEventIndex:
    """In-memory embedding index over upcoming events.

    Small enough to hold entirely in memory (~1.4 MB for 1,400 events) and
    cheap enough to rebuild from scratch after a scrape rather than maintain
    incrementally.
    """

    def __init__(self, model_name: str = MODEL_NAME):
        self._model_name = model_name
        self._model = None
        self._lock = threading.Lock()
        self._event_ids: list[int] = []
        self._vectors: Optional[np.ndarray] = None

    @property
    def is_ready(self) -> bool:
        return self._vectors is not None and len(self._event_ids) > 0

    def _load_model(self):
        """Load the model on first use, not at import time.

        Downloads the model on the very first call, so it must not sit in the
        import path of the web app.
        """
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from model2vec import StaticModel

                    logger.info(f"Loading semantic model {self._model_name}")
                    self._model = StaticModel.from_pretrained(self._model_name)
        return self._model

    @staticmethod
    def _document(event: EventModel) -> str:
        """The text an event is indexed under.

        Category and venue are included because they carry most of the signal
        for short, cryptic event names.
        """
        parts = [event.name or ""]
        if event.category:
            parts.append(event.category)
        if event.venue_name:
            parts.append(event.venue_name)
        return ". ".join(p for p in parts if p)

    async def rebuild(self, session) -> int:
        """Re-embed every upcoming event. Returns the number indexed."""
        result = await session.execute(
            select(EventModel).where(upcoming_events_filter())
        )
        events = [e for e in result.scalars().all() if e.name]
        if not events:
            logger.info("Semantic index: no upcoming events to index")
            with self._lock:
                self._event_ids, self._vectors = [], None
            return 0

        model = self._load_model()
        vectors = np.asarray(model.encode([self._document(e) for e in events]))
        # Pre-normalise so a query is a single dot product.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.maximum(norms, 1e-12)

        with self._lock:
            self._event_ids = [e.id for e in events]
            self._vectors = vectors

        logger.info(f"Semantic index: embedded {len(events)} events")
        return len(events)

    def _similarities(self, query: str) -> Optional[np.ndarray]:
        if not self.is_ready or not query.strip():
            return None
        model = self._load_model()
        vector = np.asarray(model.encode([query])[0], dtype=self._vectors.dtype)
        norm = np.linalg.norm(vector)
        if norm == 0:
            return None
        return self._vectors @ (vector / norm)

    def search(self, query: str, limit: int = 20, min_similarity: float = MIN_SIMILARITY) -> list[tuple[int, float]]:
        """Most semantically similar events as (event_id, similarity), best first."""
        sims = self._similarities(query)
        if sims is None:
            return []
        # argpartition avoids a full sort when the corpus is large.
        top = np.argsort(-sims)[:limit]
        return [(self._event_ids[i], float(sims[i])) for i in top if sims[i] >= min_similarity]

    def scores_for(self, query: str, event_ids: list[int]) -> dict[int, float]:
        """Similarity of `query` to each given event, for ranking already-found rows."""
        sims = self._similarities(query)
        if sims is None:
            return {}
        position = {eid: i for i, eid in enumerate(self._event_ids)}
        return {
            eid: float(sims[position[eid]])
            for eid in event_ids
            if eid in position
        }


# Module-level singleton: the model and its vectors are shared process-wide.
event_index = SemanticEventIndex()
