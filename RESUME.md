# 🔄 PC AÇTIĞINDA NE YAPILACAK?

**Son shutdown:** 2026-05-15 ~22:00 UTC
**State snapshot:** `logs/RESUME_STATE.json`
**GitHub repo:** https://github.com/maskelibo/price-action-bot (private, commit 92a64af)

---

## Durum Snapshot (PC kapanmadan önce)

| Bot | Equity | Pozisyon | Realized |
|-----|--------|----------|----------|
| 🔥 PHOENIX Futures Testnet | $5,000.00 USDT | 0 | $0 |
| 🏛️ Paper ATLAS | $10,000.00 | 0 | $0 |
| 🔥 Paper PHOENIX | $10,000.00 | 0 | $0 |

**Daemon process'leri:** Hepsi durduruldu (graceful kill).
**Açık testnet pozisyon:** 0 (önceki test'lerden geriye kalan 3 SHORT kapatıldı, fresh state).

---

## PC Açtığında Botları Yeniden Başlat

### 1. Terminal aç + proje klasörüne git
```bash
cd "C:\Users\koray\projeler\Price Action"
```

### 2. Durum doğrula
```bash
# Testnet bağlantı + bakiye
python scripts/futures_testnet_preflight.py

# Önceki paper state'i göster
python scripts/paper_ab_compare.py
```

### 3. Bot'ları yeniden başlat

**Terminal 1 — Paper ATLAS (control):**
```bash
python scripts/paper_daemon_atlas.py
```

**Terminal 2 — Paper PHOENIX (control):**
```bash
python scripts/paper_daemon_phoenix.py
```

**Terminal 3 — Phoenix Futures Testnet (gerçek emir, testnet USDT):**
```bash
python scripts/futures_daemon_phoenix.py
```

Her terminal'i ayrı aç, bot'lar background'da çalışmaya devam eder.

---

## İzleme

```bash
# Anlık A/B karşılaştırma
python scripts/paper_ab_compare.py

# Futures testnet anlık bakiye + pozisyon
python -c "import sys;sys.path.insert(0,'.');sys.path.insert(0,'src');from dotenv import load_dotenv;load_dotenv();from scripts.futures_trade_daily import get_futures_exchange;ex=get_futures_exchange();a=ex.fapiPrivateV2GetAccount();print(f\"Wallet: ${float(a['totalWalletBalance']):,.2f}\")"

# Daemon log
type logs\futures_daemon_phoenix.log
```

---

## Önemli Notlar

- **Backtest baseline:** PHOENIX 13-pencere ort yıllık +%200.3, DD -%32, WR %69.7
- **Beklenen aktivite:** Aylık ~26 trade, günlük ortalama 3.1 sinyal (10 strateji × 11 sembol)
- **Sinyal scan timing:** Daemon UTC 00:10 sonrası yeni 1d bar için scan tetikler
- **WYK-001:** Wyckoff lookahead leak documented, fix sprint pending

## Acil Durum

**Kill switch** (tüm bot'ları durdur):
```bash
echo '{"halted": true, "reason": "manual_halt", "ts": "2026-XX-XX"}' > logs/kill_switch.json
```

**Açık testnet pozisyonları temizle:**
```bash
python scripts/futures_testnet_close_all.py
```

---

## GitHub Repo

- URL: https://github.com/maskelibo/price-action-bot
- Branch: main
- Last commit: 92a64af (v2.0.4: ATLAS + PHOENIX dual bot setup)
- Repo private, sadece sen erişebilirsin

## TODO (Pending)

- WYK-001: Wyckoff coordinated hotfix (code + 6 test rewrite + replay re-baseline)
- HYP-001 implementation: DD-aware dynamic leverage (Researcher Priority #1)
- microstructure_proxy + naked_poc proper confluence_score (Signal Chief sprint)
- 2. testnet hesabı → ATLAS futures testnet paralel deploy
