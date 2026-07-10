"""Runtime-owned paths with an opt-in test/worker root override.

Repository assets (source, configs, prompts) stay under ``REPO_ROOT``. Runtime
state routed through this helper can be redirected with ``PA_RUNTIME_ROOT``.
When the variable is unset, paths resolve to their historical repository
locations.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def resolve_runtime_root(repo_root: Path = REPO_ROOT) -> Path:
    """Return the mutable runtime root without caching environment state."""
    override = os.environ.get("PA_RUNTIME_ROOT", "").strip()
    if not override:
        return repo_root
    return Path(override).expanduser().resolve()


@dataclass(frozen=True)
class RuntimePaths:
    """Canonical mutable paths shared by application components."""

    root: Path

    @classmethod
    def from_env(cls, repo_root: Path = REPO_ROOT) -> RuntimePaths:
        return cls(resolve_runtime_root(repo_root))

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def memory(self) -> Path:
        return self.root / "memory"

    @property
    def knowledge(self) -> Path:
        return self.root / "knowledge"

    @property
    def kill_switch(self) -> Path:
        return self.logs / "kill_switch.json"

    def heartbeat(self, service_name: str) -> Path:
        return self.data / f"dms_heartbeat_{service_name}.txt"
