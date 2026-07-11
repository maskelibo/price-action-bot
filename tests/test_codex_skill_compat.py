"""Codex migration guards for project-local operational skills."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / ".agents" / "skills"
RESUME_SKILL = ROOT / ".agents" / "skills" / "resume-write" / "SKILL.md"
WATCH_DIR = ROOT / ".agents" / "skills" / "watch"


def _frontmatter(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    assert raw.startswith("---\n")
    header, _ = raw[4:].split("\n---\n", 1)
    metadata = yaml.safe_load(header)
    assert isinstance(metadata, dict)
    return metadata


def test_project_skills_use_minimal_codex_frontmatter() -> None:
    skill_files = sorted(SKILLS_DIR.glob("*/SKILL.md"))

    assert {path.parent.name for path in skill_files} == {
        "bot-status",
        "keep-awake",
        "pool-probe",
        "resume-write",
        "signal-proximity",
        "watch",
    }
    for path in skill_files:
        metadata = _frontmatter(path)
        assert set(metadata) == {"name", "description"}
        assert metadata["name"] == path.parent.name


def test_project_skill_instructions_do_not_require_claude_only_tools() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(SKILLS_DIR.glob("*/SKILL.md"))
    )

    assert "AskUserQuestion" not in combined
    assert "allowed-tools" not in combined
    assert "Read tool" not in combined
    assert "Write tool" not in combined


def test_resume_write_does_not_require_redundant_prewrite_approval() -> None:
    text = RESUME_SKILL.read_text(encoding="utf-8")

    assert "özet göster ve onay al" not in text
    assert "Onay sonrası Write" not in text
    assert "Read et" not in text
    assert "doğrudan oluştur" in text


def test_resume_write_selects_recent_templates_dynamically() -> None:
    text = RESUME_SKILL.read_text(encoding="utf-8")

    assert "find . -maxdepth 1 -type f -name 'RESUME_*.md'" in text
    assert "sort -V | tail -n 2" in text
    assert "en güncel —" not in text


def test_watch_runtime_has_no_unset_claude_path_variables() -> None:
    runtime_files = [WATCH_DIR / "SKILL.md", WATCH_DIR / "hooks" / "hooks.json"]
    runtime_files.extend((WATCH_DIR / "hooks" / "scripts").glob("*"))
    runtime_files.extend((WATCH_DIR / "commands").glob("*.md"))
    runtime_files.extend((WATCH_DIR / "scripts").glob("*.py"))

    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in runtime_files
        if path.is_file()
    )
    assert "CLAUDE_SKILL_DIR" not in combined
    assert "CLAUDE_PLUGIN_ROOT" not in combined
    assert "(+claude-code;" not in combined
    assert "AskUserQuestion" not in combined
    assert "allowed-tools" not in combined
    assert "Read tool" not in combined
    assert "WATCH_SKILL_DIR" in combined


def test_watch_codex_copy_has_valid_runtime_urls_and_no_404_metadata() -> None:
    text_files = [path for path in WATCH_DIR.rglob("*") if path.is_file()]
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in text_files
        if "__pycache__" not in path.parts
    )

    assert "bradautomates/codex-video" not in combined.lower()
    assert "https://console.groq.com/keys" in combined
    assert "https://platform.openai.com/api-keys" in combined
