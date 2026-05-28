# Recovery Procedures

**FIX 2026-05-28 (audit-F8):** Recovery prosedürleri önceden yazılı değildi → operatör paniğe panik eder. Bu doküman 5 acil senaryoyu **komut + beklenen çıktı** olarak verir.

Her senaryoda **önce durum tespit**, sonra **adım adım komut**, sonra **kanıtla çözüldü mü**.

---

## Senaryo 1: Bot canlı görünüyor ama hiç sinyal üretmiyor

### Belirtiler
- `tail logs/futures_daemon.log` → `15M_SCAN: 0 sinyal, latency=0.0s` ardışık
- Saatler boyunca 0 sinyal, scan latency 5-8s yerine 0.0s
- Process canlı (`ps -p <PID>` cevap veriyor)

### Hipotezler (sıralı)
1. **DuckDB lock conflict** (en yaygın — CEO + futures15m aynı DB'ye yazma isteyince)
2. Strategy resolver empty list
3. Config drift (PA_15M_CONFIG yanlış)
4. Ingest down — market data stale

### Tespit
```bash
# 1. App log'unda silent fail var mı?
grep "scan15m._scan_symbol.read_fail" logs/app.log | tail -20

# 2. launchd stderr'de SCAN15M_READ_FAIL özeti var mı? (audit-FIX-VER3-2 sonrası)
tail -50 logs/launchd/futures15m.stderr.log | grep SCAN15M_READ_FAIL

# 3. CEO env doğru mu?
launchctl print gui/$(id -u)/com.priceaction.ceo | grep PA_DUCKDB
```

### Çözüm — DuckDB lock conflict ise
```bash
# CEO plist'inde PA_DUCKDB_READ_ONLY=true OLMALI
# Eksikse plist'i edit et + reload:
launchctl bootout gui/$(id -u)/com.priceaction.ceo
sleep 2
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.priceaction.ceo.plist

# Sonra futures15m'i kickstart:
launchctl kickstart -k gui/$(id -u)/com.priceaction.futures15m

# Kanıt: 15 dakika sonra scan latency 5-8s'e dönmeli
tail logs/futures_daemon.log | grep 15M_SCAN
```

---

## Senaryo 2: market.duckdb corrupt — "IO Error: malformed database"

### Belirtiler
- `duckdb data/market.duckdb ".tables"` → error
- Bot startup'ta `DUCKDB_PARSE_ERROR` veya `IOException`
- WAL dosyası (`market.duckdb.wal`) anormal büyük (>500 MB)

### Adımlar
```bash
# 1. Tüm bot'ları durdur (DB'ye dokunmasın)
launchctl bootout gui/$(id -u)/com.priceaction.futures15m
launchctl bootout gui/$(id -u)/com.priceaction.futures5m
launchctl bootout gui/$(id -u)/com.priceaction.ceo

# Doğrula: launchctl list | grep priceaction → boş

# 2. Mevcut backup'ları listele
bash scripts/restore_duckdb.sh --list market.duckdb

# 3. En son sağlam backup'tan restore (script onay isteyecek)
bash scripts/restore_duckdb.sh market.duckdb

# 4. Restore sonrası bot'ları geri al
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.priceaction.ceo.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.priceaction.futures15m.plist

# 5. Kanıt: ilk scan latency 5-8s + bot log temiz
tail -f logs/futures_daemon.log
```

### Backup nereden geliyor?
A9 fix: `scripts/backup_duckdb.sh` her gece 00:00 UTC çalışır, 7 günlük rolling backup tutar. Manuel tetiklemek:
```bash
launchctl kickstart gui/$(id -u)/com.priceaction.dbbackup
```

---

## Senaryo 3: Bot sessizce öldü (process kayboldu)

### Belirtiler
- `launchctl list | grep priceaction` → PID kolonu `-` (process yok)
- Son log satırı normal görünüyor, crash log yok
- Mac ekran kilitlenmedi (pmset uyku değil)

### Tespit
```bash
# Crash forensics
log show --predicate 'eventMessage contains "futures_daemon"' --last 1h 2>&1 | grep -i "exit\|crash\|signal\|kill"

# launchd exit code
launchctl print gui/$(id -u)/com.priceaction.futures15m | grep -iE "last exit|status"

# Resource semaphore leak?
grep "resource_tracker" logs/launchd/futures15m.stderr.log | tail -5
```

### Çözüm
A1 fix: launchd `KeepAlive=true` boolean → her exit'te 30s içinde restart. Eğer ThrottleInterval'a takıldıysa:
```bash
launchctl kickstart -k gui/$(id -u)/com.priceaction.futures15m
sleep 10
launchctl list | grep priceaction  # PID şimdi olmalı
```

---

## Senaryo 4: Veri delik — son N bar eksik

### Belirtiler
- `15M_MISSED_BARS: 3 bar kaçırıldı` log'da
- Quality check `data/quality/YYYY-MM-DD.json` → `gaps > 0`
- Backtest sonuçları beklenmedik şekilde değişti

### Tespit
```bash
# Manuel gap kontrol
PYTHONPATH=src .venv/bin/python -c "
from price_action.data.store import OHLCVStore
from datetime import datetime, timezone, timedelta
s = OHLCVStore()
df = s.read('BTC/USDT', '15m', start=datetime.now(timezone.utc)-timedelta(hours=24))
print(f'rows: {len(df)}, beklenen ~96 (24h × 4 bar/h)')
print(f'son ts: {df.ts.iloc[-1]}, şimdi: {datetime.now(timezone.utc)}')
"
```

### Çözüm — manuel backfill
```bash
# Son 36 gün'ü tekrar fetch (50-bar overlap zaten gap'leri kapatır)
PYTHONPATH=src .venv/bin/python -m price_action.data.ingest_ccxt \
  --venue binance --years 0.1

# Doğrula
PYTHONPATH=src .venv/bin/python -m price_action.data.quality
```

---

## Senaryo 5: launchd KeepAlive throttle'a takıldı (sürekli restart loop)

### Belirtiler
- `launchctl list | grep priceaction` → PID değişiyor sürekli (10 saniyede bir)
- launchd log'da `Throttled service` mesajları
- `top` → CPU %100 spike

### Tespit
```bash
# launchd internal log
log show --predicate 'subsystem == "com.apple.xpc.launchd"' --last 10m 2>&1 | grep priceaction | tail -20
```

### Çözüm
```bash
# 1. Durdur
launchctl bootout gui/$(id -u)/com.priceaction.futures15m

# 2. Crash sebebini bul (genelde import error veya config eksik)
PYTHONPATH=src .venv/bin/python scripts/futures_daemon.py --timeframe 15m --once
# Hata mesajına göre düzelt (yaml syntax, missing env var, vs)

# 3. Yeniden başlat
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.priceaction.futures15m.plist
```

---

## Genel kontrol listesi — her senaryo sonrası

```bash
# Bot canlı mı?
launchctl list | grep priceaction

# Log freshness (son 30 dk içinde yazılıyor mu?)
stat -f "%Sm" logs/futures_daemon.log

# Scan latency normal mi?
tail -20 logs/futures_daemon.log | grep "15M_SCAN.*latency"
# Beklenen: latency=5.0-8.5s aralığı

# Silent fail var mı?
tail -10 logs/launchd/futures15m.stderr.log | grep SCAN15M_READ_FAIL
# Beklenen: boş çıktı
```

---

**Bu doküman canlı olmalı.** Yeni recovery senaryosu yaşadığında bu dosyaya ekle.
