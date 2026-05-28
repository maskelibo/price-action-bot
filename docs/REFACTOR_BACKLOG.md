# Refactor Backlog — Sonraki Major Release

**FIX 2026-05-28 (audit-F9):** Bu turda yakalanan ama **paper deploy öncesi yapılması RİSKLİ** 4 büyük iş. Hepsi gerçek bug değil **tasarım borcu** — sistem doğru çalışıyor ama uzun vadede sürdürülebilirlik düşük.

Her madde için: **problem + öneri + migration plan + tahmini effort + risk**.

---

## 1. Variant DB Consolidation (4 aile × 3 variant = 11 DB)

### Problem
Faz 14.26 fix'i (2026-05-27) multi-bot için **per-bot DB ayrımı** getirdi:
- `futures_journal.duckdb` + `_5m`, `_rsi2`, `_vwap` = 4 dosya
- `idempotency.duckdb` + `_rsi2`, `_vwap` = 3 dosya
- `pyramid_store.duckdb` + `_rsi2`, `_vwap` = 3 dosya
- (paper_journal de var = 1+1)

Toplam **11 DB**, hepsi aynı şema. Hızlı fix olarak yapıldı ama:
- Backup script 11 dosya kopyalıyor (840 MB/gün)
- Schema drift yakalandı: `idempotency_vwap.duckdb`'de `heartbeat_log` tablo eksik (audit ajanı)
- Yeni bot eklemek için 3 yeni DB oluşturmak gerekir
- Query yazmak karmaşık (hangi DB hangi bot?)

### Öneri
Tek DB + `bot_name` kolonu:
```sql
-- Tek futures_journal.duckdb:
CREATE TABLE futures_trades_closed (
    trade_id TEXT,
    bot_name TEXT NOT NULL,
    ... (other columns)
    PRIMARY KEY (bot_name, trade_id)
);
CREATE INDEX idx_trades_bot ON futures_trades_closed (bot_name);
```

### Migration plan
1. Yeni schema'yı script'le oluştur (`scripts/migrate_to_unified_db.py`)
2. Her variant DB'sini oku → `bot_name` kolonu ekle → unified'a INSERT
3. Eski DB'leri `data/legacy_databases/` altına taşı
4. `futures_daemon.py` / `bot_factory.py` / trade_journal.py code'unu güncelle
5. Test: 4 bot ayrı ayrı paper run, ayrı PnL takibi doğru mu

### Effort: **8-12 saat** (kod + test + dry run)
### Risk: **YÜKSEK** — bu turda bot'lar çalışırken yaparsam veri kaybı. Paper bot duracak.
### Karar: **Sonraki major release**, paper bot 1-2 hafta stabilize olduktan sonra.

---

## 2. Circular Import: risk/breaker ↔ risk/sizing

### Problem
```python
# risk/breaker.py
from price_action.risk.sizing import AccountState
# risk/sizing.py
from price_action.risk.breaker import DDBreaker
```
Python bunu **lazy import** ile tolere ediyor (runtime'da patlamıyor), ama:
- Test'te bir modülü izole import edemiyorsun
- Refactor sırasında "neden bu obje hâlâ tanımlanıyor?" sorusu çıkıyor

### Öneri
Foundation katmanına extract:
- `_breaker_state.py` → `BreakerState` dataclass (no deps)
- `_account_state.py` → `AccountState` dataclass (no deps)
- `breaker.py` sadece `_account_state` import eder
- `sizing.py` sadece `_breaker_state` import eder

### Migration plan
1. 2 yeni dosya oluştur, sınıfları taşı
2. Tüm import'ları güncelle (~12 yer grep ile bulunur)
3. Test: full pytest yine geçer

### Effort: **2-3 saat**
### Risk: **DÜŞÜK** — refactor, semantic değişim yok.
### Karar: **Sonraki major release**, paper bot 1 hafta stabilize olduktan sonra.

---

## 3. 87 Hardcoded `0.025` Threshold

### Problem
`_thresholds.py` (audit-Y2'de eklendi) var ama sadece 3 yerden import ediliyor. Diğer 84 yerde hâlâ literal `0.025` yazıyor. Threshold değiştirmek istediğimizde 84 yerde edit gerekecek.

### Öneri
- Grep + sed ile `0.025` → `WIDESTOP_SL_PCT_DEFAULT` değiştir
- Bazıları farklı amaçla kullanılıyor olabilir (örn: bir test fixture'da hardcoded olması gerekiyor) — manuel review

### Migration plan
1. `grep -rn "0\.025" src/ scripts/ --include="*.py"` → 87 satır
2. Her satıra bak: **semantik aynı mı** (widestop sl_pct ile)? Aynıysa import et.
3. Test koş, regression olmadığından emin ol.

### Effort: **3-4 saat** (titiz olunca)
### Risk: **ORTA** — yanlış değişiklik backtest sonucunu kaydırır.
### Karar: **Sonraki major release**.

---

## 4. Strategies Code-Reuse (70 strateji, 50'si `classic_pa` hub kullanmıyor)

### Problem
70 strateji var, hepsi kendi `_atr`, `_ema`, `_fractal_swings` helper'ını yazmış. 20'si `classic_pa.py`'dan import ediyor, 50'si kopyala-yapıştır.

### Öneri
`strategies/_indicators.py` modülü oluştur:
```python
def atr14(df: pd.DataFrame, period: int = 14) -> pd.Series:
def ema(df: pd.DataFrame, span: int) -> pd.Series:
def fractal_swings(df: pd.DataFrame, lookback: int = 5) -> tuple:
def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
def bb_bands(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> tuple:
```
50 strateji'yi `from price_action.strategies._indicators import atr14` ile değiştir.

### Migration plan
1. Yeni modül + 5-10 fonksiyon
2. Her strateji'nin private helper'larını grep + replace
3. Test: strategy scaffold testleri yine geçer + determinism testi yine pass

### Effort: **6-8 saat** (70 dosya scan)
### Risk: **DÜŞÜK** — pure helper extract, behavior change yok.
### Karar: **Sonraki major release**, strategi optimization sprint'i ile birlikte.

---

## Genel sıralama (öncelik)

1. **Circular import** (2-3 saat, risk DÜŞÜK) — paper bot 1 hafta sonra
2. **Variant DB consolidation** (8-12 saat, risk YÜKSEK) — paper bot 2 hafta sonra, bot tamamen durdur
3. **87 threshold** (3-4 saat, risk ORTA) — Variant DB ile birlikte yapılabilir
4. **Strategies code-reuse** (6-8 saat, risk DÜŞÜK) — bağımsız, ne zaman olursa

Toplam: ~20-30 saatlik refactor sprint'i.

---

**Bu doküman canlı tutulmalı.** Major iş yapıldıkça bu liste güncellenir. Yeni "büyük iş ama paper deploy öncesi riskli" bulgu çıkarsa buraya eklenir.
