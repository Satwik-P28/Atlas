"""Phase 2 terminal: HTTP read models, indicators, screener, workspaces, persistence.

The package is a presentation layer. It reads through the Phase 1 contracts and never
writes evidence; user data (watchlists, workspaces, settings) lives in its own tables,
added by schema migration 003.
"""

from . import indicators, read_models, screener, workspaces
from .store import SettingsStore, WatchlistStore, WorkspaceStore

__all__ = [
    "SettingsStore",
    "WatchlistStore",
    "WorkspaceStore",
    "indicators",
    "read_models",
    "screener",
    "workspaces",
]
