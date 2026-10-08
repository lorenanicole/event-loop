# Deprecated: import from shared.schemas instead.
# shared/models/ is kept only for backward compatibility during migration.
from shared.schemas import Event, EventCreate, EventSearch  # noqa: F401

__all__ = ["Event", "EventCreate", "EventSearch"]
