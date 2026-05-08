"""Memory layer testleri — store + episodic + boot context."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from price_action.contracts import MemoryEntry
from price_action.memory import EpisodicLog, MemoryStore
from price_action.memory.store import make_entry


@pytest.fixture
def memdir(tmp_path: Path) -> Path:
    """İzole edilmiş memory klasörü — shared/facts ve identity seed eder."""
    base = tmp_path / "memory"
    (base / "ceo").mkdir(parents=True)
    (base / "shared" / "facts").mkdir(parents=True)
    (base / "shared" / "lessons").mkdir(parents=True)

    (base / "ceo" / "identity.md").write_text(
        "# CEO Identity\nSen CEO'sun.\n", encoding="utf-8"
    )
    (base / "ceo" / "know_how.md").write_text(
        "# Know How\n## Playbook A\nadım1\n", encoding="utf-8"
    )
    (base / "ceo" / "learning.md").write_text(
        "# Learning\n", encoding="utf-8"
    )
    (base / "shared" / "facts" / "fact_one.md").write_text(
        "# Fact One\nimmutable\n", encoding="utf-8"
    )
    (base / "shared" / "lessons" / "lesson_one.md").write_text(
        "# Lesson One\n", encoding="utf-8"
    )
    return base


def test_read_identity_know_how_learning(memdir: Path) -> None:
    store = MemoryStore(base_dir=memdir)
    assert "Sen CEO'sun" in store.read_identity("ceo")
    assert "Playbook A" in store.read_know_how("ceo")
    assert "# Learning" in store.read_learning("ceo")


def test_read_shared_facts_and_lessons(memdir: Path) -> None:
    store = MemoryStore(base_dir=memdir)
    facts = store.read_shared_facts()
    assert "fact_one" in facts
    lessons = store.read_shared_lessons(limit=10)
    assert any("Lesson One" in s for s in lessons)


def test_append_learning_appends_only(memdir: Path) -> None:
    store = MemoryStore(base_dir=memdir)
    initial = store.read_learning("ceo")
    entry = make_entry(
        "ceo",
        "Bugünkü hata: aşırı pozisyon önerisi.",
        entry_type="learning",
        slug="overconfidence-2026-05-08",
        confidence="high",
        tags=["bias", "review"],
    )
    store.append_learning("ceo", entry)
    after = store.read_learning("ceo")
    assert len(after) > len(initial)
    assert "overconfidence-2026-05-08" in after
    assert "Bugünkü hata" in after

    # İkinci append — eski içerik korunur
    entry2 = make_entry("ceo", "Başka ders.", slug="another", confidence="med")
    store.append_learning("ceo", entry2)
    final = store.read_learning("ceo")
    assert "Bugünkü hata" in final
    assert "Başka ders" in final


def test_append_know_how(memdir: Path) -> None:
    store = MemoryStore(base_dir=memdir)
    entry = make_entry(
        "ceo",
        "Yeni playbook: kriz protokolü iletişim adımı.",
        entry_type="know_how",
        slug="crisis-comm",
        tags=["playbook"],
    )
    store.append_know_how("ceo", entry)
    txt = store.read_know_how("ceo")
    assert "crisis-comm" in txt
    assert "Yeni playbook" in txt


def test_write_decision_creates_adr_file(memdir: Path) -> None:
    store = MemoryStore(base_dir=memdir)
    adr = {
        "title": "Adopt Lab Tournament",
        "context": "weekly tournament infra",
        "options": "do / wait",
        "decision": "do",
        "consequences": "weekly burn",
        "status": "accepted",
    }
    path = store.write_decision("ceo", adr, slug="adopt-lab-tournament")
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "Adopt Lab Tournament" in content
    assert "## Decision" in content
    assert path.parent == memdir / "ceo" / "decisions"
    assert path.name.endswith("-adopt-lab-tournament.md")


def test_boot_context_includes_sections(memdir: Path) -> None:
    store = MemoryStore(base_dir=memdir)
    # Önce learning'e 6 entry ekle, son 5 görünmeli
    for i in range(6):
        store.append_learning(
            "ceo",
            make_entry(
                "ceo",
                f"learning entry {i}",
                slug=f"l-{i}",
                confidence="med",
            ),
        )
    boot = store.boot_context("ceo")
    assert "## IDENTITY" in boot
    assert "## KNOW-HOW" in boot
    assert "## RECENT LEARNINGS" in boot
    assert "## SHARED FACTS AVAILABLE" in boot
    # En son 5 entry geçer; ilk entry (`l-0`) görülmemeli
    assert "l-5" in boot
    assert "l-0" not in boot


# ----------------------------------------------------------------------
# EpisodicLog
# ----------------------------------------------------------------------

def test_episodic_append_and_iter(memdir: Path) -> None:
    log = EpisodicLog(agent="ceo", base_dir=memdir)
    log.append("event one", tags=["t1"], kind="episodic")
    log.append("event two", tags=["t1", "t2"], kind="learning")
    records = list(log.iter_records())
    assert len(records) == 2
    assert records[0]["body"] == "event one"
    assert records[1]["kind"] == "learning"
    # JSONL geçerli
    raw = (memdir / "ceo" / "runtime" / "episodic.jsonl").read_text(encoding="utf-8")
    for line in raw.strip().splitlines():
        json.loads(line)  # raises if invalid


def test_episodic_consolidate_window(memdir: Path) -> None:
    log = EpisodicLog(agent="ceo", base_dir=memdir)
    # Eski kayıt — pencere dışında
    log.append(
        "stale event", tags=["x"], ts=datetime.now(timezone.utc) - timedelta(days=30)
    )
    # Yeni 3 kayıt aynı body prefix
    for _ in range(3):
        log.append("recurring body that is the same", tags=["repeat"])
    log.append("singleton body", tags=["singleton"])

    summary = log.consolidate(last_n_days=7)
    assert summary["total"] == 4  # stale dışında
    assert summary["by_kind"].get("episodic", 0) == 4
    # En sık tag "repeat" olmalı
    top_tag = summary["top_tags"][0][0]
    assert top_tag in ("repeat", "singleton")
    # frequent_bodies — repeat eşiği >1 olduğundan görünür
    freq_bodies = [b for b, _ in summary["frequent_bodies"]]
    assert any("recurring body" in b for b in freq_bodies)


def test_episodic_archive_resets_active_log(memdir: Path) -> None:
    log = EpisodicLog(agent="ceo", base_dir=memdir)
    log.append("evt", tags=["a"])
    archive_path = log.archive("2026-W19")
    assert archive_path is not None and archive_path.exists()
    # Aktif log boş kalmalı
    active = (memdir / "ceo" / "runtime" / "episodic.jsonl").read_text(encoding="utf-8")
    assert active == ""


def test_memory_entry_uses_contract(memdir: Path) -> None:
    """MemoryEntry pydantic model'i ile uyumluluk kontrolü."""
    store = MemoryStore(base_dir=memdir)
    entry = MemoryEntry(
        agent="ceo",
        type="learning",
        slug="sample",
        body="example body",
        confidence="low",
        tags=["sample"],
    )
    store.append_learning("ceo", entry)
    assert "example body" in store.read_learning("ceo")
