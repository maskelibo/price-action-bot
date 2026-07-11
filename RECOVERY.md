# Recovery Procedures

**FIX 2026-05-28 (audit-F8):** Recovery prosedürleri önceden yazılı değildi → operatör paniğe panik eder. Bu doküman 5 acil senaryoyu **komut + beklenen çıktı** olarak verir.

Her senaryoda **önce durum tespit**, sonra **adım adım komut**, sonra **kanıtla çözüldü mü**.

> **Güncel canlı servis sınırı (2026-07-11):** yalnız
> `com.priceaction.futures_v15p2` / `logs/futures_daemon_v15p2.log` kullanılır.
> `futures15m`, `_v11`, `_v63` ve `futures5m` emeklidir; onları load/bootstrap
> etmek split-brain yaratabilir.

---

## Senaryo 1: Bot canlı görünüyor ama hiç sinyal üretmiyor

### Belirtiler
- `tail logs/futures_daemon_v15p2.log` → `15M_SCAN: 0 sinyal, latency=0.0s` ardışık
- Saatler boyunca 0 sinyal, scan latency 5-8s yerine 0.0s
- Process canlı (`ps -p <PID>` cevap veriyor)

### Hipotezler (sıralı)
1. **DuckDB lock conflict** (en yaygın — CEO + v15p2 aynı DB'ye yazma isteyince)
2. Strategy resolver empty list
3. Config drift (PA_15M_CONFIG yanlış)
4. Ingest down — market data stale

### Tespit
```bash
# 1. App log'unda silent fail var mı?
grep "scan15m._scan_symbol.read_fail" logs/app.log | tail -20

# 2. launchd stderr'de SCAN15M_READ_FAIL özeti var mı? (audit-FIX-VER3-2 sonrası)
tail -50 logs/launchd/futures_v15p2.stderr.log | grep SCAN15M_READ_FAIL

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

# Sonra yalnız güncel v15p2'yi kickstart:
launchctl kickstart -k gui/$(id -u)/com.priceaction.futures_v15p2

# Kanıt: 15 dakika sonra scan latency 5-8s'e dönmeli
tail logs/futures_daemon_v15p2.log | grep 15M_SCAN
```

---

## Senaryo 2: market.duckdb corrupt — "IO Error: malformed database"

### Belirtiler
- `duckdb data/market.duckdb ".tables"` → error
- Bot startup'ta `DUCKDB_PARSE_ERROR` veya `IOException`
- WAL dosyası (`market.duckdb.wal`) anormal büyük (>500 MB)

### Adımlar
```bash
# 1. Emekli/v14 label'lardan biri loaded ise önce sebebini incele ve manuel
# bootout et. Restore bunları hiçbir koşulda otomatik geri başlatmaz.
for label in \
  com.priceaction.futures_v14 \
  com.priceaction.futures15m \
  com.priceaction.futures15m_v11 \
  com.priceaction.futures15m_v63 \
  com.priceaction.futures5m; do
  launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1 && echo "ABORT loaded: $label"
done

# 2. Mevcut backup'ları listele.
bash scripts/restore_duckdb.sh --list market.duckdb

# 3. En son sağlam backup'tan staged+atomic restore (script exact yes ister).
# Script destekli DB kullanıcılarının loaded label + gerçek plist yolunu önce
# kaydeder, onaydan sonra exact seti bootout eder ve işlem sonunda yalnız aynı
# seti geri bootstrap eder. İnaktif E13/forward/multitf sırf plist'i var diye
# başlatılmaz. Captured plist kayıpsa DB'ye dokunmadan fail-visible durur.
bash scripts/restore_duckdb.sh market.duckdb

# 4. Kanıt: RESTORE_RESTART_OK satırları yalnız captured label'ları göstermeli;
# ilk scan latency 5-8s + bot log temiz olmalı.
rg "RESTORE_(PRE_ACTIVE_CAPTURED|RESTART_OK|RESTART_FAIL)" logs/restore_duckdb.log | tail -30
tail -f logs/futures_daemon_v15p2.log
```

### Backup nereden geliyor?
A9 fix: `scripts/backup_duckdb.sh` yerel saatle 00:00 TR çalışır, en yeni 3
backup'ı tutar ve SHA256 manifesti üretir. Açık kaynak holder'ını gözlemleyip
canlı prosesi durdurmaz: DB+varsa WAL'i gizli stage'e alır, yalnız stage kopyada
DuckDB `CHECKPOINT` + tüm tablo `COUNT(*)` doğrulaması yapar. Başlangıçta atomik
`data/backups/.backup_duckdb.lock` alır; ikinci eşzamanlı
çalışma/stale lock rc=3 ile fail-visible durur ve yayımlanmış sete dokunmaz.
Stale lock, kayıtlı PID'nin öldüğü kanıtlanmadan otomatik silinmez. Her snapshot
denemesinde kopya öncesi/sonrası kaynak DB+WAL çifti `lstat` fingerprint'i
(existence, regular/symlink, inode, size, `mtime_ns`) exact aynı olmalıdır;
WAL'in oluşması veya
kaybolması da denemeyi reddeder. Stage DB/WAL boyutları pre-fingerprint ile
eşleşmeden checkpoint başlamaz. Böylece kaynak checkpoint'inin eski DB + boş/
yeni WAL ile sessiz commit kaybettirmesi fail-closed retry olur. Torn/değişen
kopya üç kez doğrulanamazsa önceki yayımlanmış backup korunur. Başarılı snapshot
WAL gerektirmeyen tek `.duckdb` dosyasıdır ve tüm set+manifest bitmeden tarih
dizini atomik yayınlanmaz. Manuel tetikleme gerçek çok-GB snapshot üretir;
operasyon ihtiyacı olmadan çalıştırma:
```bash
launchctl kickstart gui/$(id -u)/com.priceaction.dbbackup
```

11 Temmuz 2026 02:38 TR saha kanıtı: 39/39 snapshot tam-okuma geçti,
39 satırlı manifest doğrulandı, WAL yayımlanmadı ve retention tam newest-3
(`20260709/10/11`) oldu.

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
launchctl print gui/$(id -u)/com.priceaction.futures_v15p2 | grep -iE "last exit|state"

# Resource semaphore leak?
grep "resource_tracker" logs/launchd/futures_v15p2.stderr.log | tail -5
```

### Çözüm
A1 fix: launchd `KeepAlive=true` boolean → her exit'te 30s içinde restart. Eğer ThrottleInterval'a takıldıysa:
```bash
launchctl kickstart -k gui/$(id -u)/com.priceaction.futures_v15p2
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
launchctl bootout gui/$(id -u)/com.priceaction.futures_v15p2

# 2. Crash sebebini EMİR/TARAMA üretmeden doğrula.
# Base futures_daemon.py --once kullanma: c2v5 kimliğiyle gerçek testnet scan ve
# submit yoluna girebilir. Bu komut yalnız v15p2 wrapper import/config/patch
# doğrulamasını disposable runtime altında yapar; main loop çağrılmaz.
_check_root="$(mktemp -d)"
PA_V14_PHASE=v15p2 PA_TESTING=1 PYTHON_DOTENV_DISABLED=1 \
PA_RUNTIME_ROOT="$_check_root" PYTHONPATH=src \
  .venv/bin/python -c \
  'import scripts.futures_daemon_v14 as v; print("V15P2_CONFIG_OK", v.V14_CONFIG)'
_check_rc=$?
rm -rf "$_check_root"
test "$_check_rc" -eq 0
# Hata mesajına göre düzelt (yaml syntax, missing import/env, vs)

# 3. Yeniden başlat
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.priceaction.futures_v15p2.plist
```

---

## Senaryo 6: Binance testnet HTTP 418 / `-1003` rate ban

### Kural

- Banı "test etmek" için yeni REST çağrısı yapma; bu ban süresini uzatabilir.
- Exchange cevabındaki `banned until` zamanını bekle.
- Açık pozisyon varken yalnız yeni cooldown kodunu yüklemek amacıyla daemonı
  restart etme. Borsa-tarafı koruma emirlerini UI'dan gözle, yeni API sorgusu
  üretme.

### Tespit

```bash
rg -n "418|code.*-1003|banned until" logs/futures_daemon_v15p2.log | tail -30
```

### Mitigasyon ve kapanış

Process-local cooldown guard, time-sync cache ve same-bar state reuse 11 Temmuz
2026'da kodlandı/testlendi; çalışan daemon güvenli doğal restarta kadar eski
bellektedir. Restart sonrası 48 saat yeni 418 sayımı ve cooldown logu izlenir.
Incident kaydı:
`memory/shared/incidents/INC-2026-07-11-binance-testnet-rate-ban.md`.

---

## Genel kontrol listesi — her senaryo sonrası

```bash
# Bot canlı mı?
launchctl list | grep priceaction

# Log freshness (son 30 dk içinde yazılıyor mu?)
stat -f "%Sm" logs/futures_daemon_v15p2.log

# Scan latency normal mi?
tail -20 logs/futures_daemon_v15p2.log | grep "15M_SCAN.*latency"
# Beklenen: latency=5.0-8.5s aralığı

# Silent fail var mı?
tail -10 logs/launchd/futures_v15p2.stderr.log | grep SCAN15M_READ_FAIL
# Beklenen: boş çıktı
```

---

**Bu doküman canlı olmalı.** Yeni recovery senaryosu yaşadığında bu dosyaya ekle.
