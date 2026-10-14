"""Alle Quellen-Module importieren, damit sie sich in der Registry anmelden.

Eigene Plugins: Datei in diesem Ordner anlegen und hier importieren
(oder per `plugins:` in config.yaml laden – siehe README)."""
from .base import REGISTRY, Source, create_source, register  # noqa: F401
from . import petzi, venues, generic  # noqa: F401
