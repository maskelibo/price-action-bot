# Geliştirme Rehberi

## Kurulum

```bash
uv sync
uv run pre-commit install
```

## Test Çalıştırma

```bash
uv run pytest                   # tüm hızlı testler
uv run pytest -m "not slow"     # gece testleri hariç
uv run pytest -m integration    # network gerektiren (manuel)
uv run pytest -m live           # gerçek borsa (manuel)
uv run pytest --cov             # coverage
```

## Lint / Type Check

```bash
uv run ruff check .
uv run ruff format .
uv run mypy src/
```

## Yeni Pattern Detector Eklerken

1. `signals/candles.py` veya `signals/structure.py`'a vektörize fonksiyon ekle.
2. `tests/test_signals.py`'a 2-3 unit test (bilinen mum dizileri).
3. `tests/test_lookahead.py`'a explicit causality testi.
4. `docs/patterns/<id>.md` (varsa) görsel + senaryo.
5. Strateji manifestoda parametre referansı.

## Yeni Strateji Eklerken

1. `Researcher` agent'ı çağır → hipotez pre-registration `memory/researcher/hypotheses/`.
2. `configs/strategies/<name>.yaml` taslak (manifest).
3. `strategies/<name>.py` Strategy ABC implementasyonu.
4. Backtest çalıştır → `reports/research/<name>-<date>.html`.
5. Robustness suite çalıştır.
6. Lab tournament'a sok.
7. Onay sonrası `memory/shared/decisions/` ADR.

## Yeni LLM Agent Eklerken (nadir)

1. `agents/<name>.md` rule dosyası (persona + mandate + hard limits + KPI + SOP + memory protocol + output format).
2. `memory/<name>/identity.md`, `know_how.md`, `learning.md` seed.
3. `src/price_action/agents/<name>.py` `LLMAgentBase` türevi.
4. `orchestrator/scheduler.py`'a job kayıt.
5. Test: dry-run + boot context yüklemesi.

## Memory Yazım Kuralları

- Identity dışında append-only.
- Tarih + agent + slug + confidence zorunlu.
- Hassas bilgi (API key, kullanıcı verisi) YASAK.
- `runtime/` JSONL — kısa vadeli; konsolidasyonu Lab yapar.

## Commit / PR

- Conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.
- Pre-commit hook'ları geçmeli.
- Test coverage düşürmemeli.
- Yeni faz gate'i veya hard limit değişikliği → ADR zorunlu.
