# DEPLOY SPEC — 15m wide-stop config canlıya alma

**Durum:** Wide-stop edge backtest'te doğrulandı (honest +%12.67/ay konservatif,
DD −%21, WF OOS 0/34 neg) AMA canlı engine'e wire EDİLMEDİ. Canlı bot hâlâ
C2+V5 (honest ~%0) çalıştırıyor. Bu doküman wire adımını mekanik hale getirir.

**Bu bir öneri/spec — kod değişikliği değil. Uygulama = Principal kararı + review.**

---

## DÜRÜST ÖN-UYARI (deploy'dan önce oku)

1. **Backtest = hipotez, canlı fill = kanıt.** +%12.67/ay bir backtest sonucu.
2. **Her ay %10 GARANTİ DEĞİL.** Yıllık kırılım: 2021 +13.6 / 2022 +12.3 /
   **2023 +7.6** / 2024 +13.1 / 2025 +20.4 / **2026-YTD +4.6** %/ay. Zayıf
   rejimlerde (2023, 2026) %10 ALTINA düşüyor. Gerçek beklenti: **uzun-vade
   ortalama ≥%10, ama rejime göre +%5–20 bandında dalgalanır.**
3. **Post-only fill oranı canlı doğrulanmadı.** Konservatif senaryo (+%12.67)
   taker maliyeti varsayar; post-only tutmazsa bu geçerli, tutarsa +%23'e çıkar.
4. Önce **paper/shadow** koştur, sonra canlı — aşağıdaki Aşama planı.

---

## DEPLOYABLE CONFIG (hedef parametre seti)

```
sl_pct_min:        0.025     # YENİ — entry sl_pct < %2.5 sinyalleri REJECT
risk_pct:          0.005     # mevcut %2 → %0.5 (DD kontrolü)
daily_dd:          0.02      # mevcut 0.04 → 0.02
weekly_dd:         0.05      # mevcut 0.08 → 0.05
pyramid_enabled:   false     # wide-stop analizi pyramid-OFF doğrulandı
```
Honest sonuç (taker +55bps): continuous DD −%20.7, aylık-mean +%12.67, neg 3/61.

---

## WIRE ADIMI 1 — engine/backtest tarafı (parity için ŞART)

`src/price_action/backtest/lab.py`:
- `ProductionConfig`'e alan ekle: `sl_pct_min: float = 0.0` (default 0.0 =
  kapalı = byte-identical, geri uyumlu).
- `from_yaml`'da oku: `sl_pct_min = float(raw.get("execution", {}).get("sl_pct_min", 0.0))`.
- `production_replay` başında girdi trade'lerini filtrele:
  `trades = [t for t in trades if abs(t["initial_sl"]-t["entry_price"])/t["entry_price"] >= cfg.sl_pct_min]`
  (sl_pct entry'de ATR'den bilinir → causal, look-ahead YOK).
- Test: `sl_pct_min=0.0` → mevcut replay'lerle byte-identical; `sl_pct_min=0.025`
  → `scripts/lab_15m_widestop_dd_opt.py` sonucunu (+%12.67/ay) üretmeli.

## WIRE ADIMI 2 — canlı daemon tarafı

`scripts/futures_daemon.py`, 15m sinyal işleme döngüsü (entry/SL hesaplandıktan
SONRA, risk-check'ten ÖNCE):
```python
_sl_pct = abs(_entry - _sl) / _entry if _entry > 0 else 0.0
if _sl_pct < _cfg_sl_pct_min:          # _cfg_sl_pct_min config'den, default 0.0
    log(f"  15M_REJECT_WIDESTOP: {sym} sl_pct={_sl_pct:.4f} < {_cfg_sl_pct_min}")
    continue
```
`_cfg_sl_pct_min` aynı `execution:` bloğundan okunur. Default 0.0 → davranış değişmez.

## WIRE ADIMI 3 — config

Tercih: yeni dosya `configs/risk_phoenix_scalp_15m_widestop.yaml`
(c2v5'in kopyası + yukarıdaki DEPLOYABLE CONFIG değerleri). Daemon'ı bu config
ile başlat. Eski c2v5 dosyası dokunulmadan kalır (geri dönüş kolay).

## WIRE ADIMI 4 — test + parity

- `tests/` altına `sl_pct_min` filtre testi (0.0 → no-op; 0.025 → n azalır).
- Parity: widestop config ile engine backtest, `lab_15m_widestop_dd_opt.py`
  konservatif satırını (DD −%20.7, aylık +%12.67) ±%2 üretmeli.
- `pytest tests/risk tests/execution` yeşil kalmalı.

---

## AŞAMALI ROLLOUT (önerilen)

1. **Adım 1–4'ü uygula, `sl_pct_min` default 0.0 → canlı bot DEĞİŞMEZ.** Commit.
2. **Paper/shadow:** widestop config'i paper modda 1–2 hafta koştur. Gerçek
   fill ekonomisi + post-only fill oranı ölç (`data/execution_fills.duckdb`).
3. **Kill-criteria:** maker fill ≥%60 ∧ total RT cost ≤25bps → canlıya geç.
   Aksi halde taker-senaryo geçerli (yine +%12.67 backtest ama canlı doğrula).
4. **Canlı:** widestop config + küçük sermaye → 4–8 hafta → aylık honest ROI
   ölç → hedefle (≥%10 ortalama) kıyasla.

## NE ZAMAN "HEDEF TUTTU" DENİR
Canlı (paper değil) ≥8 hafta, honest aylık ortalama ≥%10, ve hiçbir ay
katastrofik değil (DD ≤ −%25). O zamana kadar: backtest umut veriyor, kanıt yok.
