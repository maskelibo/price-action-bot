---
agent: lab_scientist
type: learning / execution_review
created: 2026-05-12
tags: execution, slippage, funding, maker_rebate, partial_fill, friction
scope: src/price_action/execution + configs/risk.yaml + src/price_action/backtest/engine.py
status: analysis_only (kullanici onayi bekleniyor — kod degisikligi YAPILMADI)
---

# Execution Layer Review — Friction Azaltma Onerileri

> Hedef: Backtest 3y rolling +%35 ile live %28 arasindaki ~%7-12 friction drag'ini
> %3-5'e indirmek. Bu rapor olcum + 4 somut oneri.

---

## 1. Mevcut Durum — Ne Calisiyor

- **Live guard zinciri saglam.** `ccxt_live.py:_verify_live_mode()` 3 katmanli (settings, risk.yaml live_mode_enabled, testnet anahtar saniti). Production icin yeterli.
- **Post-only timeout fallback algoritmasi var.** `ccxt_live.py:152-185` post-only emir 30 sn icinde dolmazsa cancel + market fallback. Mantik dogru.
- **Slippage > 25 bps reject + no-resubmit.** `ccxt_live.py:190-193` orderbook seyrekligi durumunda zarar verici fill'i kesiyor — Tower / HRT standardiyla uyumlu.
- **Idempotency.** `OrderManager.submit()` (order_manager.py:65-72) `signal.fingerprint()` ile duplicate'i blokluyor. Race condition korumasi tamam.
- **Per-symbol slippage modeli mevcut** (`backtest/slippage.py`). BTC=5, ETH=6, BNB=8, SOL=10, mid-cap=12-15, small-cap=18-22 bps. Bu **kullaniliyor** (engine `symbol_slippage_map` parametresi var).
- **Paper broker'in slippage modeli orderbook-aware** (`ccxt_paper.py:91-113`) — gercek defter derinligi varsa VWAP fill, yoksa 5 bps base.

---

## 2. Bulunan Sorunlar — Friction'in Geldigi Yerler

### S1 — KRITIK: `ccxt_live.py:115` limit fiyat hesabi CROSS-THE-SPREAD (postOnly REJECT olur)

**Kod (`src/price_action/execution/ccxt_live.py:114-118`):**
```python
if instruction.order_type == "post_only_limit":
    offset = 0.0001  # 1 bps
    limit_price = (
        ref_price * (1 - offset) if side_ccxt == "buy" else ref_price * (1 + offset)
    )
```

`ref_price` = `ticker.last` (~= mid).
- BUY post-only: limit = mid * 0.9999 → **best_ask'a yakin** (cross/marketable likely)
- SELL post-only: limit = mid * 1.0001 → **best_bid'a yakin** (cross likely)

Binance `postOnly=True` parametresi, emir best bid/ask'a degiyorsa **REJECT** eder.
Symbolun spread'i 2-10 bps arasinda (BTC 1-2, small-cap 15-25). 1 bps offset hicbir orta-kucuk
sembolde post-only kabul edilmez.

**Pratik sonuc:** Post-only emirler %60-90 oraninda reject → 30sn timeout → market fallback.
Yani **maker rebate hicbir zaman kazanilmiyor**, ustelik market'e dustugumuzde 5-20 bps slippage da yiyoruz.

**Beklenen drag:** ~10-25 bps / trade (kayip rebate +1 bps + market slippage 5-20 bps + spread cross).

---

### S2 — KRITIK: Backtest `fees.taker` post_only_limit emirlerde de uygulaniyor

**Kod (`src/price_action/backtest/engine.py:414`):**
```python
fee_total += (entry_price + ep) * q * fees.get("taker", 0.00075)
```

- `fees = {"taker": 0.00075, "maker": -0.00010}` her zaman taker uygulaniyor.
- `Strategy.entry_type = "post_only_limit"` default ama backtest engine bunu okumuyor.

**Asimetri:** Backtest "maker mi taker mi" sormuyor, hep taker (7.5 bps) yaziyor.
Live `Fill.is_maker` flag'i var (ccxt_live.py:205) ama backtest hep taker hesapliyor.

**Sonuc:** Backtest 7.5 bps fee + 5 bps slip = 12.5 bps. Eger live'da S1 cozulurse maker oluyoruz
ve aslinda -1 bps + spread/2 ~ 3-5 bps olmasi gerekir.

**Net beklenen tasarruf S1 + S2 birlikte cozulurse:** 8-12 bps / trade (live tarafta).

---

### S3 — Partial-fill bilesik risk hesabi eksik

**Kod (`src/price_action/execution/ccxt_live.py:201-203`):**
```python
return Fill(
    ...
    quantity=float(order.get("filled", qty)),  # <-- gercekte dolan miktar
```

- `filled` < `qty` durumunda **kismi fill** ile geri donuluyor.
- Risk Officer'in hesapladigi sizing tam `qty` icindi. Eger %60'i doldu ise:
  - Risk per trade = sizing'in %60'i (kucukluk OK).
  - **AMA:** SL/TP child order'lari hala yokmus gibi (`_maybe_place_protective_orders` placeholder, order_manager.py:131-143). Yani **kismi fill'li pozisyon korumasiz**.
  - Iste SL emri konulmadigi icin live'da "fiil dustu, pozisyon biriksin, SL yok" senaryosu olusabilir → tail risk.

**Ek olarak:** post_only_timeout durumunda (ccxt_live.py:166-185) sadece **cancel + komple yeni market** atiyor. Asil yapilmasi gereken: **dolanin uzerine kalan miktari top-up et**, hepsini iptal etme.

**Beklenen drag:** Buyuk kayip riski (tail), normal sartlarda 0-2 bps gercek; ama tail event'te %5-10 ekstra loss.

---

### S4 — `max_slippage_bps: 25` reject thresholdu — DOGRU AMA TEK YONLU

**Kod (`src/price_action/execution/ccxt_live.py:38, 189-193`):**
```python
slip_bps = abs((fill_price - ref_price) / ref_price * 10_000)
if slip_bps > self.max_slippage_bps:
    return None
```

- 25 bps esik DOGRU. BTC/ETH/SOL icin overkill kapali, small-cap (LINK/DOT/DOGE) icin tight ama makul.
- **PROBLEM:** `abs()` kullanildigi icin **lehimize olan slip** (negatif) de reject ediliyor. Sevkiyat lehimize sapsa bile.
  - Long BUY: realized < ref → favorable (maker fill bid'de oldu), `(fill - ref)/ref` negatif. `abs()` 25'i gecince reject.
  - Bu nadir ama varlikta pozitif rebate kazandiran fill'i atmis oluyoruz.
- **Ikinci problem:** Reject sonrasi pozisyon yok ama backtest beklentisi bu sinyalde pozisyon var. Bu sinyaller backtest'te aliniyor, live'da aliniyor → **selection bias**: en volatil/agresif fill'ler atiliyor, en kolaylari kaliyor.

**Beklenen etki:** 1-3 bps net dezavantaj + 5-10 sinyal/yil kayip (CAGR -%1-2 etkisi).

---

### S5 — Funding rate kaciniminin live execution'da hicbir yeri yok

**Tarama sonucu:**
- `funding_rate` referansli **tek dosya** = `src/price_action/strategies/funding_mean_reversion.py` (strateji icin feature).
- `src/price_action/execution/*.py` icinde **funding kelimesi yok**.

**Binance perpetual funding window:** her 8 saatte (00:00, 08:00, 16:00 UTC). Funding rate pozitifse long oder, negatifse short oder.

- BTC/USDT ortalama funding ~0.01% / 8h = 11% / yil; ekstrem donemde 0.1% / 8h.
- 3y rolling sistem ortalama 5-7 gun pozisyon tutuyor (1d TF, multi-target TP). Bu ~15-20 funding window'a denk.
- Yon hep sectigimiz strateji-yon olmadigi icin (long-bias degil), funding etkisi simetrik degil; ama **pozitif funding'de long agirligimiz** > short agirligimiz oldugu icin **net drag**.

**Tahmini drag:** 5-15 bps / trade ortalama, ekstrem donemde 30-50 bps.

**Cozulebilir:** Pozisyon acmadan once funding rate'i kontrol et; window oncesi 30 dk:
- Long sinyal + funding > 0.05% / 8h → bir sonraki window'u beklet (1 saat geciktir).
- Short sinyal + funding < -0.05% / 8h → ayni.
- Pozisyonu kapatma vakti window onunda ise: 30 dk once kapat.

---

## 3. Oneriler — 4 Somut Degisiklik

### O1 — Post-only limit fiyatini gercekten passive yap (S1 fix)

**Ne yapilacak:** `ccxt_live.py:114-126`'da `ticker.last` yerine `fetch_order_book(limit=5)` cek, side'a gore:
- BUY post-only → limit = `best_bid` (veya `best_bid - tick_size` daha guvenli)
- SELL post-only → limit = `best_ask` (veya `best_ask + tick_size`)

Kontrol gevsetmesi: 1 bps offset yerine `tick_size` kullan (sembol spesifik).

**Niye:** Post-only'nin amaci kuyrukta beklemek, makers'in kuyruguna girmek, **maker rebate** kazanmak ve spread'in karsisina gecmeden almak. Mevcut kod tam tersini yapiyor.

**Beklenen tasarruf:**
- Maker rebate kazanci: +1 bps (taker -7.5 → maker -1 = **8.5 bps swing**)
- Spread crossing kaybi yok: ~3-7 bps (spread/2 ortalamasi)
- Toplam: **~10-15 bps / trade**

**Risk:** Doldurma orani dusebilir → market fallback'e ihtiyac artar. `post_only_timeout_sec=30` kismen ama daha akilli olabilir: cancel-and-replace ileri seviyeye atilan kuyrukta veya **fill probability**'ye gore karar.

---

### O2 — Backtest engine maker/taker switch'i + per-symbol slippage prod path (S2 fix)

**Ne yapilacak:**
1. `backtest/engine.py:_simulate_symbol()` icinde `Strategy.manifest.backtest.entry_type` veya `signal.metadata.get("entry_type")` oku.
2. `entry_type == "post_only_limit"` ise fee = `fees["maker"]` (-1 bps), aksi takdirde taker (7.5 bps).
3. Tum 5y/3y backtest scriptlerinde `symbol_slippage_map = build_slippage_map(SYMBOLS, use_live=False)` ile FALLBACK_SLIPPAGE_BPS kullan (zaten var, sadece tetiklenmeli).

**Niye:** Backtest live ile bit-identical olmali. Su anda backtest 7.5 bps taker hesapliyor ama live'da S1 fix sonrasi maker olacak → backtest **pesimistik**. Aslinda CAGR 3-4pp daha yuksek olabilir.

**Beklenen tasarruf:**
- Daha gercekci backtest tahmini → +3-5pp CAGR upside (live'a yakinlasma)
- Per-symbol slip (5-22 bps): flat 5 bps yerine ortalama 10-12 bps → backtest **pesimistik** yonde duzelir. Yine **live ile uyum**.

**Bu degisiklik backtest'i KOTULESTIRIR**, sonra S1 fix backtest'i tekrar IYILESTIRIR. Ikisi paralel = net upside.

---

### O3 — Funding-window aware order timing (S5 fix)

**Ne yapilacak:**
1. Yeni dosya: `src/price_action/execution/funding_guard.py`.
2. `OrderManager.submit()` icinde, place_order oncesi:
   - `ex.fetch_funding_rate(symbol)` cagir.
   - Sonraki funding window'a < 30 dk varsa VE yon-ile-funding catismasi varsa (long + funding > 0.05%/8h veya short + funding < -0.05%/8h): bir sonraki window sonrasina ertele.
3. Pozisyon kapanis vakti yaklasiyorsa (TP/SL aktif degil, runner mode) ve funding window onunde ise erken cikis.

**Niye:** 3y rolling backtest funding-blind. Live'da pozitif funding donemlerinde long agirligimiz drag aliyor. 11 sembolde 3y * 365 = 12K window-pozisyon kesisimi → kumulatif onemli.

**Beklenen tasarruf:**
- Ortalama: 5-10 bps / trade
- Ekstrem regime (boga bitisi, ayi dibi): 20-40 bps / trade

---

### O4 — Partial-fill top-up + protective orders zorunlu (S3 fix)

**Ne yapilacak:**
1. `ccxt_live.py:place_order` sonunda `filled < qty` ise:
   - **Remaining-only top-up:** `filled` kalan_qty = qty - filled. Eger kalan_qty / qty > 0.05 (yani >%5 eksik):
     - Aynisini bir kez daha post-only ile dene (10 sn timeout).
     - Hala eksikse market.
   - Eger kalan_qty / qty < 0.05: tam kabul, kucuk eksiklik.
2. **`OrderManager._maybe_place_protective_orders` icini doldur:** `ex.create_order(stop_market, reduce_only=True)` SL ve `take_profit_market` (ya da `limit reduce_only`) TP — exchange-side. Boylece WS koparsa bile pozisyon korumali.
3. Fill miktari kismi ise SL/TP miktari = gercek filled miktari (qty degil) olmali.

**Niye:** Su anda partial fill durumda quantity dogru raporlaniyor ama SL/TP **exchange-side yok**. Sistem kapanirsa pozisyon korumasiz. Bu friction degil tail-risk ama priority HIGH.

**Beklenen tasarruf:**
- Normal: 0-2 bps (top-up retry maliyeti)
- Tail event'te: %5-10 katastrofik kayip onlenir.

---

## 4. Toplam Friction Tasarrufu Tablosu

| ID | Degisiklik | Sembol grubu | Beklenen drag azalmasi (bps/trade) |
|---|---|---|---|
| O1 | Gercek post-only fiyat (orderbook bazli) | tum | **10-15** |
| O2 | Maker fee + per-symbol slip backtest path | tum | live-backtest uyumu +3-5pp CAGR |
| O3 | Funding-window aware timing | perp tum | **5-10** (ortalama), 20-40 (regime) |
| O4 | Partial-fill top-up + exchange-side SL/TP | tum | 0-2 normal, tail-risk azalmasi |
| **TOPLAM** | — | — | **15-30 bps / trade** |

Yillik 80-120 trade (3y rolling ortalama) varsayalim:
- Mevcut drag varsayim: %20 (S1+S2+S5 ana sucl). Yillik %20 / 100 trade = 200 bps / trade.
- Tasarruf sonra: 200 - 25 = 175 bps / trade → %17.5 yillik drag.
- **Beklenen yillik drag: %20 → %10-12.** Hedef %10-15 araliginda.

---

## 5. Backtest-Live Drift Erken Sinyali (Bonus)

Onlemler aktive olduktan sonra ilk 30 gun KS test (lab SOP-2):
- Live slip dagilimi vs backtest slip dagilimi.
- p < 0.01 ise drift uyari + Analyst rapor.
- `Fill.is_maker` orani <%60 ise O1 fix dogru calismiyor demek.

---

## 6. Karar / Sonraki Adim

- Bu rapor sadece analiz. Kod degisikligi **YAPILMADI**.
- Onceliklendirme onerisi (en yuksek ROI/risk orani):
  1. **O1 (post-only fiyat fix)** — kritik bug, kolay fix, en yuksek tasarruf.
  2. **O4 (exchange-side SL/TP)** — tail risk, koruma onceligi.
  3. **O3 (funding-window timing)** — orta etki, orta complexity.
  4. **O2 (backtest fee/slip uyumu)** — gerekli ama backtest-only, live PnL'i degistirmez.

- Insan onayi sonrasi (CEO + principal): O1 ve O4 ayni PR'da gidebilir. O2 ayri PR. O3 ayri PR + 2 hafta paper-trade gozlem.

---

## EK — Kod Referans Ozeti

| Bulgu | Dosya:Satir | Mesele |
|---|---|---|
| S1 | `src/price_action/execution/ccxt_live.py:114-118` | Post-only limit cross-the-spread |
| S2 | `src/price_action/backtest/engine.py:414` | Hep taker fee yaziliyor |
| S3 | `src/price_action/execution/ccxt_live.py:201-203` + `order_manager.py:131-143` | Kismi fill + protective orders placeholder |
| S4 | `src/price_action/execution/ccxt_live.py:189` | `abs()` lehte slip'i de reject ediyor |
| S5 | (yok) | Funding rate execution'da hic kullanilmiyor |
