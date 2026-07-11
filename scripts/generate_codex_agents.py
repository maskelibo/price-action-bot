#!/usr/bin/env python3
"""Generate project-scoped Codex agents from canonical Markdown profiles.

``agents/*.md`` is the only editable source of role instructions.  Codex
discovers the generated TOML wrappers in ``.codex/agents``.  Keeping the
bridge deterministic prevents a second, silently drifting persona copy.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "agents"
TARGET_DIR = REPO_ROOT / ".codex" / "agents"
READ_ONLY_AGENTS = frozenset(
    {
        "audit_chief",
        "audit_data",
        "audit_execution",
        "audit_ops",
        "audit_research",
        "audit_risk",
    }
)


@dataclass(frozen=True)
class AgentProfile:
    """Validated canonical agent profile."""

    name: str
    title: str
    body: str
    source_path: Path


def load_profile(path: Path) -> AgentProfile:
    """Load one canonical profile and remove only its YAML frontmatter."""
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n") or "\n---\n" not in raw[4:]:
        raise ValueError(f"{path}: expected YAML frontmatter")

    frontmatter_text, body = raw[4:].split("\n---\n", 1)
    metadata = yaml.safe_load(frontmatter_text)
    if not isinstance(metadata, dict):
        raise ValueError(f"{path}: frontmatter must be a mapping")

    name = metadata.get("agent")
    title = metadata.get("title")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{path}: missing non-empty 'agent' field")
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"{path}: missing non-empty 'title' field")
    if path.stem != name:
        raise ValueError(f"{path}: filename stem {path.stem!r} != agent {name!r}")

    canonical_body = body.strip()
    if not canonical_body:
        raise ValueError(f"{path}: canonical instruction body is empty")
    if "'''" in canonical_body:
        raise ValueError(
            f"{path}: canonical body contains TOML literal delimiter; "
            "extend the serializer before generating"
        )

    return AgentProfile(
        name=name,
        title=title.strip(),
        body=canonical_body,
        source_path=path,
    )


def codex_description(profile: AgentProfile) -> str:
    """Build stable routing guidance without duplicating mutable details."""
    return (
        f"{profile.title}. Use for `{profile.name}` work covered by the canonical "
        f"`agents/{profile.name}.md` mandate and hard limits; do not absorb adjacent roles."
    )


def expected_keys(profile: AgentProfile) -> set[str]:
    """Return the exact schema emitted for a profile."""
    keys = {"name", "description", "developer_instructions"}
    if profile.name in READ_ONLY_AGENTS:
        keys.add("sandbox_mode")
    return keys


def render_agent(profile: AgentProfile) -> str:
    """Render the supported Codex custom-agent TOML schema."""
    lines = [
        f"name = {json.dumps(profile.name, ensure_ascii=False)}",
        f"description = {json.dumps(codex_description(profile), ensure_ascii=False)}",
    ]
    if profile.name in READ_ONLY_AGENTS:
        lines.append('sandbox_mode = "read-only"')
    lines.extend(
        [
            "developer_instructions = '''",
            f"{profile.body}'''",
            "",
        ]
    )
    return "\n".join(lines)


def validate_rendered(path: Path, rendered: str, profile: AgentProfile) -> None:
    """Validate TOML syntax and semantic parity before writing anything."""
    payload = tomllib.loads(rendered)
    required = expected_keys(profile)
    if set(payload) != required:
        raise ValueError(f"{path}: expected exactly {sorted(required)}, got {sorted(payload)}")
    if payload["name"] != profile.name:
        raise ValueError(f"{path}: rendered name mismatch")
    if payload["description"] != codex_description(profile):
        raise ValueError(f"{path}: rendered description mismatch")
    if payload["developer_instructions"] != profile.body:
        raise ValueError(f"{path}: rendered canonical body mismatch")
    if profile.name in READ_ONLY_AGENTS and payload["sandbox_mode"] != "read-only":
        raise ValueError(f"{path}: audit agent must be read-only")


def generate(*, check: bool) -> tuple[list[Path], list[str]]:
    """Generate wrappers or return every inventory/content drift in check mode."""
    profiles = [load_profile(path) for path in sorted(SOURCE_DIR.glob("*.md"))]
    if not profiles:
        raise ValueError(f"{SOURCE_DIR}: no canonical agent profiles found")

    names = [profile.name for profile in profiles]
    if len(names) != len(set(names)):
        raise ValueError("duplicate canonical agent name")

    rendered_profiles: list[tuple[AgentProfile, Path, str]] = []
    for profile in profiles:
        target = TARGET_DIR / f"{profile.name}.toml"
        rendered = render_agent(profile)
        validate_rendered(target, rendered, profile)
        rendered_profiles.append((profile, target, rendered))

    expected_names = set(names)
    existing_names = {path.stem for path in TARGET_DIR.glob("*.toml")}
    unexpected = sorted(existing_names - expected_names)
    errors = (
        [f"unexpected Codex agent without canonical source: {name}" for name in unexpected]
        if check
        else []
    )
    changed: list[Path] = []

    if not check:
        TARGET_DIR.mkdir(parents=True, exist_ok=True)
        for name in unexpected:
            path = TARGET_DIR / f"{name}.toml"
            path.unlink()
            changed.append(path)

    for _profile, target, rendered in rendered_profiles:
        actual = target.read_text(encoding="utf-8") if target.exists() else None
        if actual == rendered:
            continue
        if check:
            reason = "missing" if actual is None else "out of sync"
            errors.append(f"{target.relative_to(REPO_ROOT)}: {reason}")
            continue
        target.write_text(rendered, encoding="utf-8")
        changed.append(target)

    return changed, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate .codex/agents/*.toml from canonical agents/*.md profiles."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit non-zero if inventory or content has drifted.",
    )
    args = parser.parse_args(argv)

    try:
        changed, errors = generate(check=args.check)
    except (OSError, ValueError, tomllib.TOMLDecodeError, yaml.YAMLError) as exc:
        print(f"codex-agent-generator: ERROR: {exc}", file=sys.stderr)
        return 2

    if errors:
        for error in errors:
            print(f"codex-agent-generator: {error}", file=sys.stderr)
        return 1

    count = len(list(SOURCE_DIR.glob("*.md")))
    if args.check:
        print(f"codex-agent-generator: OK ({count} canonical agents)")
    else:
        print(f"codex-agent-generator: updated {len(changed)} file(s) from {count} agents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
