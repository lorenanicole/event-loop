"""
Smart search tool with NLTK semantic similarity and event matching.
Uses TF-IDF + cosine similarity to find semantically similar events.
"""

from __future__ import annotations

import logging
from typing import Optional
import nltk
from nltk.corpus import stopwords, wordnet
from nltk.tokenize import word_tokenize
from nltk.stem import WordNetLemmatizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

from src.logging import get_logger

logger = get_logger(__name__)

# Download required NLTK data (run once)
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')
    nltk.download('stopwords')
    nltk.download('wordnet')
    nltk.download('averaged_perceptron_tagger')


class SmartSearchTool:
    """
    NLP-powered search tool for semantic event matching.
    Uses NLTK for tokenization, lemmatization, and similarity scoring.
    """

    def __init__(self):
        self.lemmatizer = WordNetLemmatizer()
        self.stop_words = set(stopwords.words('english'))
        self.vectorizer = TfidfVectorizer(
            analyzer='word',
            lowercase=True,
            stop_words='english',
            max_features=1000,
        )

    def _tokenize_and_lemmatize(self, text: str) -> list[str]:
        """Tokenize and lemmatize text for similarity matching."""
        tokens = word_tokenize(text.lower())
        lemmatized = [
            self.lemmatizer.lemmatize(token)
            for token in tokens
            if token.isalnum() and token not in self.stop_words
        ]
        return lemmatized

    def _expand_query_with_synonyms(self, query: str) -> str:
        """Expand query with synonyms for broader matching."""
        tokens = self._tokenize_and_lemmatize(query)
        expanded = set(tokens)

        for token in tokens:
            # Find synonyms
            for synset in wordnet.synsets(token):
                for lemma in synset.lemmas():
                    if lemma.name() != token:
                        expanded.add(lemma.name())

        return " ".join(expanded)

    async def expand_query(self, user_query: str) -> dict[str, any]:
        """
        Expand user query with synonyms and related terms.

        Example:
            "jazz concert" →
            {
              "original": "jazz concert",
              "expanded": "jazz concert music band performance show",
              "tokens": ["jazz", "concert", "music", "band"],
              "synonyms": ["music", "performance", "show"]
            }
        """
        expanded = self._expand_query_with_synonyms(user_query)
        tokens = self._tokenize_and_lemmatize(user_query)
        synonyms = set(expanded.split()) - set(tokens)

        return {
            "original": user_query,
            "expanded": expanded,
            "tokens": tokens,
            "synonyms": list(synonyms),
        }

    async def extract_intent(self, query: str) -> dict[str, any]:
        """
        Extract search intent and key filters from query.
        Uses NLP to identify event type, date, price, and vibe.
        """
        tokens = self._tokenize_and_lemmatize(query)
        tokens_lower = [t.lower() for t in tokens]

        # Category detection
        category_keywords = {
            "music": ["concert", "music", "band", "dj", "jazz", "rock", "hip-hop", "indie"],
            "comedy": ["comedy", "stand-up", "standup", "laugh", "funny"],
            "theater": ["theater", "theatre", "play", "drama", "broadway", "show"],
            "sports": ["sports", "game", "match", "tournament", "athletic"],
            "art": ["art", "gallery", "exhibition", "installation", "sculpture", "museum"],
            "food": ["food", "dining", "restaurant", "chef", "cooking", "tasting"],
            "film": ["film", "movie", "cinema", "screening", "documentary"],
            "festival": ["festival", "fair", "carnival", "celebration"],
        }

        detected_categories = []
        for category, keywords in category_keywords.items():
            if any(kw in tokens_lower for kw in keywords):
                detected_categories.append(category)

        # Time detection
        time_keywords = {
            "today": ["today", "tonight"],
            "this_weekend": ["weekend", "saturday", "sunday"],
            "this_week": ["week", "weekday"],
            "this_month": ["month"],
            "next_week": ["next"],
        }

        detected_time = None
        for time_frame, keywords in time_keywords.items():
            if any(kw in query.lower() for kw in keywords):
                detected_time = time_frame
                break

        # Price detection
        price_keywords = {
            "free": ["free", "no cost"],
            "cheap": ["cheap", "affordable", "budget"],
            "expensive": ["expensive", "luxury", "premium"],
        }

        detected_price = None
        for price_level, keywords in price_keywords.items():
            if any(kw in query.lower() for kw in keywords):
                detected_price = price_level
                break

        # Vibe detection
        vibe_keywords = {
            "casual": ["casual", "chill", "relax"],
            "energetic": ["energetic", "party", "dance", "wild"],
            "cultural": ["cultural", "sophisticated", "art"],
            "family": ["family", "kids", "children"],
            "date": ["date", "romantic", "intimate"],
        }

        detected_vibe = None
        for vibe, keywords in vibe_keywords.items():
            if any(kw in query.lower() for kw in keywords):
                detected_vibe = vibe
                break

        return {
            "intent_type": "discovery",  # or "recommendations", "compare", "save"
            "categories": detected_categories,
            "time_frame": detected_time,
            "price_level": detected_price,
            "vibe": detected_vibe,
            "raw_tokens": tokens,
        }

    async def find_similar_events(
        self,
        event_id: int,
        limit: int = 5,
    ) -> list[dict]:
        """
        Find semantically similar events using TF-IDF cosine similarity.

        Uses event names and categories to find "nearest neighbors".
        Example: User liked jazz concert → show similar jazz/music events
        """
        # Note: Database access disabled during async migration
        # This method should be updated to use async database calls
        # For now, return empty list to avoid blocking
        return []

        # Prepare documents for TF-IDF
        documents = [
            f"{event.name} {event.category or ''}"
            for event in all_events
        ]
        target_doc = f"{target.name} {target.category or ''}"

        try:
            # Fit vectorizer and transform
            tfidf_matrix = self.vectorizer.fit_transform(documents + [target_doc])

            # Calculate cosine similarity with target (last document)
            similarities = cosine_similarity(tfidf_matrix[-1], tfidf_matrix[:-1])[0]

            # Get top N similar events (excluding the target itself)
            top_indices = np.argsort(similarities)[::-1][:limit]

            similar_events = []
            for idx in top_indices:
                if similarities[idx] > 0.1:  # Minimum similarity threshold
                    event = all_events[idx]
                    similar_events.append({
                        "id": event.id,
                        "name": event.name,
                        "date": event.date.isoformat(),
                        "category": event.category,
                        "similarity_score": float(similarities[idx]),
                        "url": event.origination_url,
                    })

            return similar_events

        except Exception as e:
            logger.error(f"Similarity search error: {e}")
            return []

    async def query_expansion_and_search(
        self,
        user_query: str,
        category_filter: Optional[str] = None,
    ) -> dict[str, any]:
        """
        Full pipeline: expand query → extract intent → return enhanced search context.
        Used by the REACT agent to make smarter decisions.
        """
        expansion = await self.expand_query(user_query)
        intent = await self.extract_intent(user_query)

        return {
            "user_query": user_query,
            "query_expansion": expansion,
            "intent": intent,
            "recommendation": {
                "search_with": expansion["expanded"],  # Use expanded query for DB search
                "filter_by_category": intent["categories"],
                "filter_by_time": intent["time_frame"],
                "filter_by_price": intent["price_level"],
                "enhance_with_vibe": intent["vibe"],
            },
        }


# Singleton instance for use in chatbot
_smart_search_instance: Optional[SmartSearchTool] = None


def get_smart_search_tool() -> SmartSearchTool:
    """Get or create the singleton SmartSearchTool."""
    global _smart_search_instance
    if _smart_search_instance is None:
        _smart_search_instance = SmartSearchTool()
    return _smart_search_instance
