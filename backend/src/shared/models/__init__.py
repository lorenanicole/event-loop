# Deprecated: import from shared.schemas instead.
# shared/models/ is kept only for backward compatibility during migration.
from shared.schemas import Event, EventCreate, EventSearch

__all__ = ["Event", "EventCreate", "EventSearch"]
