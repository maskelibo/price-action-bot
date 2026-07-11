---
name: signal-proximity
description: WIDESTOP eşiğine (%2.5) en yakın sinyal adaylarını güncel daemon restart sınırı içinde listeler. Top N candidates with symbol+UTC/TR time and per-symbol breakdown. Use when user asks "en yakın kim", "%X'e yaklaşan", "kaça yaklaştı", "kim aday".
---

# Signal Proximity — eşiğe en yakın WIDESTOP'lar

`15M_REJECT_WIDESTOP` satırlarını parse eder, sl_pct'e göre sıralar.

## Argümanlar

- `N` (default 5): kaç adet göster
- `scope` (default `current-process`): yalnız güncel daemon restart segmenti.
  Log satırlarında tarih olmadığı için kesin "son N saat" veya "tüm günler"
  sayımı bu kaynaktan kanıtlanamaz.

## Log satır formatı

```
[18:00:11]   15M_REJECT_WIDESTOP: ADA/USDT sl_pct=0.0247 < 0.0250
```
Timestamp UTC. Sembol "WIDESTOP: " sonrası, sl_pct = sonraki sayı.

## Güncel süreç sınırı

`futures_daemon_v15p2.log` yalnız `HH:MM:SS` taşır ve birden çok günü/restartı
aynı dosyada biriktirir. Bu yüzden saat-of-day filtresi **kullanma**: önce son
`FUTURES 15M DAEMON STARTED` satırından sonraki güncel süreç segmentini al.

```bash
LOG=~/price-action-bot/logs/futures_daemon_v15p2.log
START_LINE=$(rg -n "FUTURES 15M DAEMON STARTED" "$LOG" | tail -1 | cut -d: -f1)
test -n "$START_LINE" || { echo "Güncel restart sınırı kanıtlanamadı"; exit 2; }
tail -n +"$START_LINE" "$LOG"
```

## Top N en yakın aday (güncel süreç)

```bash
cd ~/price-action-bot && \
LOG=logs/futures_daemon_v15p2.log && \
START_LINE=$(rg -n "FUTURES 15M DAEMON STARTED" "$LOG" | tail -1 | cut -d: -f1) && \
test -n "$START_LINE" && \
tail -n +"$START_LINE" "$LOG" | grep "15M_REJECT_WIDESTOP" | \
  sed -E 's/\[([^]]+)\].*WIDESTOP: ([^ ]+) sl_pct=([0-9.]+).*/\3 \2 \1/' | \
  sort -rn | head -N
```

Çıktı: `0.0247 ADA/USDT 01:15:10`

## Son N saat isteği

Bu log tarih taşımadığı için `14:00-18:00` gibi saat-of-day filtresi eski
günlerin aynı saatlerini de toplar. Kullanıcı "son N saat" isterse:

1. Kesin pencerenin bu logdan kanıtlanamadığını açıkça söyle.
2. Güncel süreç segmentini sun ve bunu "son N saat" diye etiketleme.
3. Kesin saat penceresi gerekiyorsa tarih damgalı journal/structured log iste;
   tahmini sayıyı kesin sonuç gibi verme.

## Sembol bazlı dağılım

```bash
LOG=~/price-action-bot/logs/futures_daemon_v15p2.log && \
START_LINE=$(rg -n "FUTURES 15M DAEMON STARTED" "$LOG" | tail -1 | cut -d: -f1) && \
test -n "$START_LINE" && \
tail -n +"$START_LINE" "$LOG" | grep "15M_REJECT_WIDESTOP" | \
  sed -E 's/.*WIDESTOP: ([^ ]+).*/\1/' | \
  sort | uniq -c | sort -rn
```

## Rapor formatı

```
## Eşiğe en yakın (güncel daemon süreci, eşik %2.5)

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
