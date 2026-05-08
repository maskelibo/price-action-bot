# Price Action — Otonom Swing Trading Şirketi

Kripto piyasalarında klasik price action (1D + 1W) ile swing trade yapan, kendini sürekli geliştiren, **şirket gibi** organize 10-departmanlı otonom sistem. Hibrit zekâ: deterministik kod emir verir, LLM agent'lar (Claude Agent SDK) yalnızca araştırma/strateji/raporlama yapar.

> **Faz hedefi (gate):** Out-of-sample yıllık net **>%70**, Sharpe **>1.5**, MaxDD **<%20**. Gate düşerse ileri faza geçilmez.

## Hızlı başlangıç

```bash
# 1) Bağımlılıklar (uv tavsiye edilir)
uv sync

# 2) .env hazırla
cp .env.example .env  # Binance/Bybit testnet anahtarlarını gir

# 3) Servisler (Postgres + Grafana + Prometheus + DuckDB)
docker compose up -d

# 4) Tarihsel veri çek
uv run python -m price_action.data.ingest_ccxt --venue binance --tf 1d 1w --years 5

# 5) Backtest
uv run python scripts/run_backtest.py --strategy classic_pa --symbols configs/symbols.yaml

# 6) Departman toplantısı (CEO döngüsü)
uv run python -m price_action.orchestrator.ceo_loop --mode daily
```

## Mimarinin tek-cümle özeti

10 departman → her biri net girdi/çıktı kontratlı bir Python paketi → 4 departmanın LLM (Claude Agent SDK) "şefi" var → CEO orkestrasyonu, raporları konsolide eder → **emir veren tek katman deterministik kod** (LLM emir vermez).

## Departmanlar

| Dept | Şefi (LLM?) | Kod paketi | Detay |
|---|---|---|---|
| CEO Office | LLM ✓ | `agents/ceo` | Üst seviye karar, sermaye tahsisi, kriz protokolü |
| Data Engineering | — | `data/` | OHLCV ingest, kalite, feature store |
| Research & Quant | LLM ✓ | `agents/researcher` | Hipotez, backtest, walk-forward, parametre opt. |
| Signal Engineering | — | `signals/` | Pattern detector, S/R, confluence skoru |
| Risk Management | — | `risk/` | Pozisyon sizing, DD breaker, kaldıraç tavanı |
| Portfolio | — | `portfolio/` | Sembol evreni, sermaye dağıtımı, korelasyon |
| Execution | — | `execution/` | ccxt order routing, paper/live, slippage |
| Analytics & PM | LLM ✓ | `agents/analyst` | KPI, post-mortem, narrative raporu |
| Operations | — | `agents/ops_engineer` (devops loop) | Monitoring, alert, uptime |
| Self-Improvement Lab | LLM ✓ | `agents/lab_scientist` | Drift, turnuva, sürekli iyileştirme |

## Memory & RAG

- `memory/` — her agent için **identity / learning / know_how / decisions** katmanları + paylaşılan **lessons / facts**.
- `knowledge/` — RAG corpus (price action makaleleri + YouTube transkriptleri + kitaplar). `knowledge/seeds.yaml` canonical kaynak listesi.
- Embedding store: ChromaDB (lokal, persistent).
- Lab haftalık RAG'i tazeler; Researcher hipotezlerini RAG bulguları ile gerekçelendirir.

Detaylar için: [`ARCHITECTURE.md`](./ARCHITECTURE.md).

## Faz durumu

- [x] Faz 0 — Repo, Docker, agent kuralları, memory/RAG iskelesi
- [ ] Faz 1 — Pattern detectors + naive backtest (gate: precision > %75)
- [ ] Faz 2 — Walk-forward + ROI gate (yıllık > %70, Sharpe > 1.5, DD < %20)
- [ ] Faz 3 — Risk + portföy katmanı
- [ ] Faz 4 — ML sinyal filtresi (opsiyonel)
- [ ] Faz 5 — LLM agent orkestrasyon + Telegram brief
- [ ] Faz 6 — Paper trading (testnet, 4 hafta)
- [ ] Faz 7 — Mikro canlı + sürekli self-improvement loop

## Güvenlik

- Tüm API anahtarları `.env` ve docker secrets üzerinden; **git'e asla commit edilmez**.
- LLM **emir veremez** — yalnızca öneri ve rapor üretir, deterministik kod karar verir.
- Faz 7'ye kadar her parametre değişikliği insan onayı gerektirir.
- Her trade reproducibility manifestosuyla diske yazılır (commit hash + config hash + data hash).
