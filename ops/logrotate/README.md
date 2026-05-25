# ops/logrotate/

macOS log rotation — `newsyslog` (sistem default) için config + cron-based gzip script.

## Mevcut

- `priceaction.newsyslog.conf` — macOS newsyslog formatı
- `rotate_logs.sh` — cron'dan çağrılan script (newsyslog limitlerinin ötesi)

## Yükleme

```bash
# 1. newsyslog config kopyala (root yetki gerekir)
sudo cp ops/logrotate/priceaction.newsyslog.conf /etc/newsyslog.d/

# 2. cron script (kullanıcı)
chmod +x ops/logrotate/rotate_logs.sh

# 3. crontab (her gece 03:00 yerel saatte)
(crontab -l; echo "0 3 * * * /Users/peyman/price-action-bot/ops/logrotate/rotate_logs.sh") | crontab -

# Doğrula
crontab -l | grep rotate_logs
```

## Beklenen davranış

- **Günlük:** `logs/launchd/*.log` ve `logs/futures_daemon.log` rotate edilir
- **30 gün sonra:** gzip'lenir (`.gz` uzantı)
- **180 gün sonra:** silinir
- **Hedef:** `du -sh logs/` < 500MB her zaman

## Manuel test

```bash
# Şu anki disk kullanımı
du -sh /Users/peyman/price-action-bot/logs/

# Manuel rotate (test)
/Users/peyman/price-action-bot/ops/logrotate/rotate_logs.sh

# Sonuçları gör
ls -lah /Users/peyman/price-action-bot/logs/archive/
```
