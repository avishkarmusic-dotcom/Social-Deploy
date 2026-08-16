"""Adapter lookup. Import-time registration keeps wiring in one place."""
from __future__ import annotations

from app.connectors.base import Connector

_REGISTRY: dict[Connector] = {}


def register(adapter_cls: type[Connector]) -> type[Connector]:
    _REGISTRY[adapter_cls.source_kind] = adapter_cls()
    return adapter_cls


def get(kind: ChannelKind | str) -> Connector:
    try:
        return _REGISTRY[kind]
    except KeyError:  # pragma: no cover - guarded by the enum
        raise LookupError(f"No adapter registered for {kind}") from None


def all_adapters() -> list[Connector]:
    return list(_REGISTRY.values())


def pollable() -> list[Connector]:
    return [a for a in _REGISTRY.values() if not a.supports_push]


def load_all() -> None:
    """Called once at startup; every adapter module self-registers on import."""
    from app.connectors import gbp, gmail, meta, microsoft, polling, slack, telegram  # noqa: F401  # noqa: F401
