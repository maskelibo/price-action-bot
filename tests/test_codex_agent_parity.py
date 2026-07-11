"""Regression guards for the canonical Markdown -> Codex agent bridge."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "agents"
TARGET_DIR = ROOT / ".codex" / "agents"
GENERATOR = ROOT / "scripts" / "generate_codex_agents.py"
READ_ONLY_AGENTS = {
    "audit_chief",
    "audit_data",
    "audit_execution",
    "audit_ops",
    "audit_research",
    "audit_risk",
}


def _canonical(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    assert raw.startswith("---\n")
    frontmatter, body = raw[4:].split("\n---\n", 1)
    metadata = yaml.safe_load(frontmatter)
    assert isinstance(metadata, dict)
    return metadata, body.strip()


def _description(name: str, title: str) -> str:
    return (
        f"{title}. Use for `{name}` work covered by the canonical "
        f"`agents/{name}.md` mandate and hard limits; do not absorb adjacent roles."
    )


def test_codex_agent_inventory_exactly_matches_canonical_profiles() -> None:
    canonical = {path.stem for path in SOURCE_DIR.glob("*.md")}
    codex = {path.stem for path in TARGET_DIR.glob("*.toml")}

    assert len(canonical) == 20
    assert codex == canonical


def test_every_codex_agent_is_minimal_and_byte_exact_to_canonical_body() -> None:
    for source in sorted(SOURCE_DIR.glob("*.md")):
        metadata, body = _canonical(source)
        target = TARGET_DIR / f"{source.stem}.toml"
        payload = tomllib.loads(target.read_text(encoding="utf-8"))

        expected_keys = {"name", "description", "developer_instructions"}
        if source.stem in READ_ONLY_AGENTS:
            expected_keys.add("sandbox_mode")
        assert set(payload) == expected_keys
        assert payload["name"] == metadata["agent"] == source.stem
        assert payload["description"] == _description(source.stem, metadata["title"])
        assert payload["developer_instructions"] == body
        if source.stem in READ_ONLY_AGENTS:
            assert payload["sandbox_mode"] == "read-only"


@pytest.mark.subprocess
def test_generator_is_idempotent_in_check_mode() -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "OK (20 canonical agents)" in result.stdout


def test_non_audit_agents_inherit_parent_sandbox() -> None:
    for target in sorted(TARGET_DIR.glob("*.toml")):
        if target.stem in READ_ONLY_AGENTS:
            continue
        payload = tomllib.loads(target.read_text(encoding="utf-8"))
        assert "sandbox_mode" not in payload
