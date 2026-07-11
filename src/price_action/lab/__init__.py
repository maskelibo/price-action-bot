"""Lab utilities with side-effect-free package import.

Keep the legacy aggregation helper lazy so ``python -m price_action.lab.*``
workers can establish their logging/output contract before importing modules
that configure process-wide sinks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .sweep_aggregator import top_cells_as_challengers

__all__ = ["top_cells_as_challengers"]


def __getattr__(name: str) -> Any:
    if name == "top_cells_as_challengers":
        from .sweep_aggregator import top_cells_as_challengers

        return top_cells_as_challengers
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
