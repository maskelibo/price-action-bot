# Notebook 00 — Sistemin Tanıtımı

> Bu dosyayı Jupyter'da değil, basit metin olarak oku. İhtiyaç duyduğunda kopyala-yapıştır ile interaktif çalıştır.

## Sistemin Hızlı Resmi

```
        ┌────────────┐
        │  Insan     │ ← onay kapısı (Faz 7'ye kadar)
        └─────┬──────┘
              │
        ┌─────▼──────┐
        │   CEO      │ (LLM, Opus 4.7) — orkestrasyon
        └─────┬──────┘
   ┌──────────┴──────────┬──────────┐
   ▼          ▼          ▼          ▼
[Researcher] [Analyst] [Lab]    [Ops]
  (LLM)      (LLM)    (LLM)    (LLM hybrid)
   │          ▲          │          │
   │          │          │          │
   ▼          │          ▼          │
[Backtest]  [Journal] [Tournament] │
   ▲           ▲           ▲       │
   │           │           │       │
   └─────[ Deterministik hat ]─────┘
   ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐
   │ Data │▶│Signal│▶│ Risk │▶│Portf │▶│Execut│▶│ Fill │
   └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘
```

## Mini Demo Senaryolar

### 1. Tek bir sembolde bir gün simülasyon

```python
from price_action.data.store import OHLCVStore
from price_action.signals.confluence import emit_signals
from price_action.strategies.classic_pa import ClassicPriceActionStrategy

store = OHLCVStore()
df = store.read("BTC/USDT", "1d", "2024-01-01", "2024-12-31")
strategy = ClassicPriceActionStrategy.load_from_yaml("configs/strategies/classic_pa.yaml")
signals = strategy.generate_signals(df)
print(f"Üretilen sinyal sayısı: {len(signals)}")
print(signals[0])
```

### 2. Risk Officer'ı çağır

```python
from price_action.risk.sizing import RiskOfficer
from price_action.contracts import Signal  # mevcut signals[0]

officer = RiskOfficer.from_config("configs/risk.yaml")
account_state = {"equity_usdt": 10_000, "open_positions": []}
result = officer.evaluate(signals[0], account_state, [], strategy.config)
print(result)  # RiskedOrder veya Reject
```

### 3. Walk-forward backtest

```python
from price_action.backtest.walk_forward import WalkForward

wf = WalkForward.from_yaml("configs/strategies/classic_pa.yaml")
result = wf.run()
print(f"OOS Sharpe: {result.oos_sharpe:.2f}")
print(f"OOS DD: {result.oos_max_drawdown:.2%}")
print(f"Pozitif dilim oranı: {result.positive_slice_ratio:.0%}")
print(f"Gate geçer mi? {result.passes_gate('classic_pa')}")
```

### 4. RAG sorgu

```python
from price_action.rag.retrieve import retrieve

hits = retrieve("bullish pin bar at S/R uptrend", k=5)
for h in hits:
    print(f"[{h.source_id}] {h.text[:200]}...")
```

### 5. CEO morning brief (LLM)

```python
from price_action.agents.ceo import CEOAgent

ceo = CEOAgent()
brief = ceo.daily_brief()  # markdown string
print(brief)
# reports/ceo/YYYY-MM-DD-brief.md dosyası da oluşur
```

## Sonraki Adımlar

- `notebooks/01_eda_template.ipynb` — sembol bazlı EDA
- `notebooks/02_signal_inspection.ipynb` — sinyal görselleştirme
- `notebooks/03_walk_forward_tuning.ipynb` — parametre tarama

(Bu notebook'lar oluşturulduğunda buraya eklenir.)
