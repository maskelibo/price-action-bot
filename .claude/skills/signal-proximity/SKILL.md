---
name: signal-proximity
description: WIDESTOP eşiğine (%2.5) en yakın sinyal adaylarını listeler. Top N candidates with symbol+time, plus per-symbol breakdown over a time window. Use when user asks "en yakın kim", "%X'e yaklaşan", "kaça yaklaştı", "kim aday".
---

# Signal Proximity — eşiğe en yakın WIDESTOP'lar

`15M_REJECT_WIDESTOP` satırlarını parse eder, sl_pct'e göre sıralar.

## Argümanlar

- `N` (default 5): kaç adet göster
- `hours` (default 24): kaç saatlik pencere; `all` = tüm log

## Log satır formatı

```
[18:00:11]   15M_REJECT_WIDESTOP: ADA/USDT sl_pct=0.0247 < 0.0250
```
Timestamp UTC. Sembol "WIDESTOP: " sonrası, sl_pct = sonraki sayı.

## Top N en yakın aday (parsing pattern)

```bash
cd ~/price-action-bot && \
grep "15M_REJECT_WIDESTOP" logs/futures_daemon_v15p2.log | \
  sed -E 's/\[([^]]+)\].*WIDESTOP: ([^ ]+) sl_pct=([0-9.]+).*/\3 \2 \1/' | \
  sort -rn | head -N
```

Çıktı: `0.0247 ADA/USDT 01:15:10`

## Zaman pencereli filtre (son N saat)

Log timestamp'leri UTC. TR saatinden N saat geri = UTC saatinden N saat geri.
Şu anki UTC saati: `date -u +%H`. Pencere başı: `(UTC_HOUR - hours) % 24`.

Örnek (son 4 saat, şu an UTC 18:00 → pencere 14:00-18:00):

```bash
awk '/^\[(14|15|16|17):[0-9][0-9]:[0-9][0-9]\]/ && /15M_REJECT_WIDESTOP/' \
  ~/price-action-bot/logs/futures_daemon_v15p2.log | \
  sed -E 's/\[([^]]+)\].*WIDESTOP: ([^ ]+) sl_pct=([0-9.]+).*/\3 \2 \1/' | \
  sort -rn | head -N
```

Saat aralığı string'ini dinamik üret (UTC mevcut saatten geriye N adım), basit dakika hassasiyeti şart değil.

## Sembol bazlı dağılım

```bash
grep "15M_REJECT_WIDESTOP" ~/price-action-bot/logs/futures_daemon_v15p2.log | \
  sed -E 's/.*WIDESTOP: ([^ ]+).*/\1/' | \
  sort | uniq -c | sort -rn
```

## Rapor formatı

```
## Eşiğe en yakın (son Xh, eşik %2.5)

| sl_pct | Sembol | Saat TR |
|---|---|---|
| 0.0247 | ADA/USDT | 04:15 |  ← (UTC 01:15 + 3h)
...

**Sembol bazında red sayısı:**
| Sembol | Adet |
|---|---|
| DOGE | 37 |
| LINK | 30 |
...
```

UTC → TR dönüşümünü tabloda mutlaka göster (kullanıcı TR düşünür).

## Yorumlama notları

- **sl_pct 0.020-0.0249** = "çok yakın aday", eşiği gevşetmek değerlendirilmeli
- **sl_pct 0.010-0.020** = "orta uzak"
- **sl_pct < 0.010** = "uzak dar bant", eşik düşmesi bile fayda etmez
- Tek sembolün üst üste 3+ red'i = volatilite o sembolde yükseliyor, izlemeye al

## Çapraz referans

- Eşik değiştirme simülasyonu için `pool-probe` skill'i kullan
- Bot genel durumu için `bot-status` skill'i çağır
