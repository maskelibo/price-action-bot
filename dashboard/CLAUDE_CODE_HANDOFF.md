# Claude Code Handoff — Price Action Dashboard'u canlıya al

Bu klasör, `price-action-bot` repon için tasarlanmış izleme + kontrol panosunun **HTML/JSX prototipi**. Mock data ile çalışıyor. Görevin: bunu repodaki FastAPI servisine bağlamak ve gerekli yeni endpoint'leri yazmak.

---

## 1. Klasörü repoya yerleştir

Dashboard tek sayfalık bir SPA — repo köküne **`dashboard/`** klasörü olarak koy:

```
price-action-bot/
├── src/price_action/
├── dashboard/                       ← yeni
│   ├── Price Action Dashboard.html
│   ├── styles.css
│   └── js/
│       ├── mock-data.jsx
│       ├── icons.jsx
│       ├── ui-kit.jsx
│       ├── controls.jsx
│       ├── shell.jsx
│       ├── screens-main.jsx
│       ├── screens-side.jsx
│       ├── tweaks-panel.jsx
│       └── app.jsx
```

Sonra `src/price_action/api/server.py` içindeki `/dashboard` endpoint'ini güncelle ki bu yeni HTML'i serve etsin (eski Jinja2 + Plotly versiyonunu emekliye ayır):

```python
from fastapi.staticfiles import StaticFiles
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parents[3] / "dashboard"
app.mount("/dashboard", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
```

Eski `dashboard.py` ve onu çağıran route'u kaldır — yenisi static dosyalardan açılıyor.

---

## 2. Mock data'yı gerçek API'ye bağla

`dashboard/js/mock-data.jsx` dosyasının en altında:

```js
window.PA_BUILD = buildAll;
```

Bu, ekranlardaki tek veri kaynağı. Yapman gereken: `buildAll(scenario)`'u **gerçek API çağrılarına çeviren** bir paralel `PA_FETCH(scenario)` async fonksiyonu yaz; sonra `js/app.jsx` içindeki `setData(window.PA_BUILD(...))` çağrısını `setData(await window.PA_FETCH(...))`'a değiştir + 4 saniyede bir polling ekle.

Mock'ların döndürdüğü şekilleri **AYNEN** koru — UI bu şekillere bağımlı. Aşağıdaki tabloya göre eşleştir:

| UI alanı | Mevcut endpoint | Şekil değişikliği gerekiyor mu? |
|---|---|---|
| `data.equity` | `GET /equity?days=90` | Hayır — `{points:[{ts, equity}]}` zaten doğru |
| `data.trades` | `GET /trades?limit=200` | **Evet** — `TradeRecord`'a `leverage`, `notional_usdt`, `hold_hours` alanları ekle (aşağı bak) |
| `data.positions` | `GET /positions` | **Evet** — `Position`'a `pattern_id`, `confluence_score`, `leverage`, `notional_usdt`, `r_multiple_live`, `strategy_id` ekle |
| `data.pending_signals` | `GET /signals/pending` | **Evet** — `Signal`'e `gate_state`, `pattern_label`, `atr_pct`, `reject_reason` ekle |
| `data.scanner` | **`GET /signals/scan` (YENİ)** | Yeni endpoint yazılacak |
| `data.kpi` | client'ta `trades` + `equity`'den hesaplanıyor | — |
| `data.breakers` | **`GET /risk/breakers` (YENİ)** | Yeni endpoint |
| `data.correlations` | **`GET /portfolio/correlations` (YENİ)** | Yeni endpoint |
| `data.departments` | **`GET /departments/status` (YENİ)** | Yeni endpoint |
| `data.phases` | static (configs içinden okunabilir) | — |
| `data.reports.ceo` | `GET /reports/ceo/latest` ✓ var | — |
| `data.reports.analytics` | `GET /reports/analytics/latest` ✓ var | — |
| `data.halted` | `GET /health` ✓ var (`halted` field'ı) | — |

---

## 3. Contract'ları genişlet

`src/price_action/contracts.py` içindeki Pydantic modellerine alan ekle. Bu repodaki **"contract değişikliği ADR ister"** kuralı geçerli — değişikliği `memory/shared/decisions/ADR-NNN-dashboard-fields.md` olarak kaydet.

```python
# Position
class Position(BaseModel):
    ...
    pattern_id: str
    confluence_score: float
    leverage: float
    notional_usdt: float
    r_multiple_live: float
    strategy_id: str

# TradeRecord
class TradeRecord(BaseModel):
    ...
    leverage: float
    notional_usdt: float
    hold_hours: float

# Signal
class Signal(BaseModel):
    ...
    gate_state: Literal['signal_only', 'awaiting_risk', 'risk_approved', 'risk_rejected']
    atr_pct: float
    pattern_label: str | None = None
    reject_reason: str | None = None
```

Sonra:
- `analytics/journal.py` — Postgres `trades` tablosuna alanları ekle, migration yaz
- `execution/ccxt_paper.py` ve `ccxt_live.py` — fill geldiğinde bu alanları doldur
- `risk/sizing.py` — `gate_state` ve `reject_reason`'ı pending signal'a yaz

---

## 4. Yeni endpoint'leri yaz

`src/price_action/api/server.py` içine ekle:

### `GET /signals/scan`
80 sembolün canlı tarama özeti. Çıktı şekli:
```json
{ "symbols": [
  { "symbol": "BTC/USDT", "trend_1w": "up", "structure": "HH/HL",
    "atr_pct": 4.2, "vol_z": 1.1, "confluence": 4.3,
    "last_price": 67800, "change_24h": 1.8,
    "last_scan_ago_sec": 8, "tag": "setup" }
]}
```
İmplementasyon: `signals/scanner.py` modülü yaz (eğer yoksa). `portfolio/universe.py`'den semboll listesini al, son 1G mum üzerinde pattern detector'ları çalıştır, confluence skoru hesapla, `tag`'i (`setup`/`watch`/null) confluence eşiklerine göre belirle.

### `GET /risk/breakers`
```json
{
  "daily":   { "limit": 0.05, "used": 0.012, "tripped": false },
  "weekly":  { "limit": 0.10, "used": 0.024, "tripped": false },
  "monthly": { "limit": 0.15, "used": 0.041, "tripped": false }
}
```
İmplementasyon: `risk/breakers.py` zaten var; günlük/haftalık/aylık equity penceresinden DD oranını hesaplayıp tripped state'iyle birlikte döndür.

### `GET /portfolio/correlations`
```json
{ "syms": ["BTC","ETH","SOL",...],
  "matrix": [[1, 0.74, 0.42, ...], ...] }
```
Yalnızca **açık pozisyonlardaki** sembollerin 90g getiri korelasyonu (Pearson). `portfolio/correlation.py` modülünden hesapla.

### `GET /departments/status`
10 departmanın canlı sağlık snapshot'ı. Çıktı şekli `mock-data.jsx`'teki `DEPARTMENTS` constant'ı ile birebir aynı:
```json
{ "departments": [
  { "key":"ceo", "name":"CEO Office", "pkg":"agents/ceo", "llm":true,
    "kpi":"orkestrasyon", "last":"2 dk", "status":"ok", "note":"..." }
]}
```
İmplementasyon: her departman için `last_run_at`, `status` (ok/warn/error), kısa note alanını topla. Ops dept'in (`agents/ops_engineer`) zaten yaptığı health check'lere bağla.

### `POST /positions/{symbol}/close`
Açık pozisyonu market emirle kapat. `execution/order_manager.py`'yi `reduce_only=true` ile çağır. **Auth:** mevcut `verify_token` dependency'sini kullan. Loglara `manual_close` reason yaz.

### `POST /admin/risk-config`
Body: `{"key": "risk_per_trade", "value": 0.02}`. `configs/risk.yaml`'ı güncellemek yerine **runtime override katmanı** kullan (kalıcı değişiklik için ADR + git PR şart, bu kuralı koru). Override `Settings`'e yansısın; restart sonrasında yaml'den geri okusun. Tüm değişiklikleri `memory/shared/decisions/runtime-overrides.jsonl`'a yaz.

---

## 5. Mimari kurallarını koru

- **LLM emir vermez** — kontrol butonları (halt, close, risk-config) sadece insan onayı. Dashboard'daki butonlar zaten modal ile onay alıyor. Backend tarafında bu butonların çağırdığı endpoint'lere LLM agent erişimi vermeyin.
- **Reproducibility** — her manuel close, `manifest_hash` ile journal'a yazılsın.
- **Faz gate'leri** — `/admin/risk-config` Faz 7'ye kadar `PA_LIVE_CONFIRM=YES_I_KNOW` env'i istemeli.

---

## 6. Tweaks paneli

`js/app.jsx` içindeki `TWEAK_DEFAULTS` JSON block'u (EDITMODE markers arasında) tema/dil/yoğunluk tercihlerini tutuyor. Production'da bu sadece client-side state — sunucuya bir şey iletmez. İstersen kullanıcı başına tercih kaydı için `GET/POST /user/prefs` ekleyebilirsin ama ihtiyaç değil.

---

## 7. Geliştirme döngüsü

```bash
# server
uv run uvicorn price_action.api.server:app --reload --port 8000

# dashboard'a git
open http://localhost:8000/dashboard
```

JSX dosyaları Babel tarafından runtime'da derlendiği için **build adımı yok** — düzenle, kaydet, sayfayı yenile. Production istersen Vite ile pre-compile edebilirsin ama opsiyonel.

---

## 8. Mock senaryosu

Tweaks panelinden "Mock Senaryo: Normal / Kazanan / Breaker" seçenekleri var. Bunlar şu an `PA_BUILD(scenario)` ile mock veri üretiyor; canlıya geçtikten sonra **bu seçenekleri kaldır** (tweaks-panel'den ilgili `TweakRadio`'yu sil ve `setData` her zaman `PA_FETCH()` çağırsın). Geliştirme sırasında scenario flag'i tutman gerekiyorsa `?scenario=breaker` query param ekleyebilirsin.

---

Bitti. Sorun yaşarsan ilk önce console error'larına bak, sonra Network tab'ından endpoint response shape'ini mock şekille karşılaştır.
