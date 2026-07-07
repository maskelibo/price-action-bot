---
name: resume-write
description: Gün sonu RESUME_YYYY-MM-DD.md handoff dokümanı üretir. Bu oturumdaki commit'ler, bot durumu, açık kararlar, dürüst şerhler bölümleriyle. Use when user asks "günü kapat", "resume yaz", "handoff", "devir yaz", "session özet".
---

# Resume Write — gün sonu handoff dokümanı

Mevcut RESUME pattern'ine sadık kalarak günün dokümanını üretir.

## Çıktı dosyası

```
~/price-action-bot/RESUME_YYYY-MM-DD.md
```

Tarih sistemden çek: `date +%Y-%m-%d`. **Aynı gün zaten varsa** `-v2`, `-v3` suffix ekle.

## Referans şablonlar (önceki RESUME'lar)

Pattern'i bu dosyalardan öğren — TON ve YAPI bunlara birebir uysun:

- `RESUME_2026-05-22.md` (en güncel — Windows→Mac devir)
- `RESUME_2026-05-21.md`
- `RESUME_2026-05-19_v1.md`
- `RESUME_2026-05-17_v3.md` (en uzun, ayrıntılı)

Önce bunlardan 1-2 tanesini Read et, format/ton uyumunu sağla.

## Zorunlu bölümler

1. **Başlık + tarih** — `# RESUME — YYYY-MM-DD (kısa konu)`
2. **⚡ İLK YAPILACAKLAR** (eğer makine/branch değişimi varsa)
3. **⚠️ BU VERSİYON NE ÇALIŞTIRIR — KRİTİK**
   - Bot şu an hangi stratejiyi çalıştırıyor
   - Honest beklenti (BACKTEST ≠ canlı, vurgula)
4. **Bot Durumu (devir anı)**
   - PID, uptime, açık pozisyonlar, son tarama
5. **Bu Oturumda Yapılanlar**
   - Commit'ler (hash + tek satır özet)
   - Yapılmayan / yarım kalan işler ayrı liste
6. **HEDEF: dürüst aylık ≥%10 — DURUM**
   - Her aktif/aday strateji için: backtest sayıları + gate durumu
7. **AÇIK KARARLAR**
   - Bekleyen Principal kararları, sıradaki adımlar
8. **Dürüst Şerhler**
   - "Bu rakamlar BACKTEST = hipotez. Kanıt = canlı fill."
   - Validate edilmemiş varsayımlar
   - Bilinen riskler

## Veri toplama adımları

Resume yazmadan ÖNCE topla:

```bash
cd ~/price-action-bot

# 1. Bu oturumun commit'leri (son N saat veya kullanıcının söylediği başlangıçtan)
git log --oneline --since="6 hours ago"

# 2. Branch durumu
git status
git branch --show-current

# 3. Bot durumu (bot-status skill'inden kullan)
# 4. Açık pozisyonlar
cat data/state/positions.json 2>/dev/null || echo "no state file"

# 5. Son log özeti (ENTRY var mı?)
grep -cE "ENTRY|ACCEPT|FILL" logs/futures_daemon_v15p2.log

# 6. Diff istatistik
git diff --stat
```

## Honest framework (dürüstlük kuralları)

Kullanıcı bu projeye özel kurallar koymuş — RESUME'larda **mutlaka** uygulanır:

1. **"Backtest = hipotez, fill = kanıt"** — her backtest rakamına bu şerhi düş
2. **Negatif sonuçları üste al** — "edge çalışmadı" yazısı "edge olabilir" yazısından önce gelir
3. **Validate edilmemiş varsayım** = açıkça işaretle (örn. "Post-only fill oranı canlı doğrulanmadı")
4. **Sayıları gizleme** — kötü ay (2023 +%7.6) iyi ayların yanında yazılır
5. **Açık karar = açık yazılır** — "Wide-stop deploy için karar bekliyor" gibi

## Final review

Yazmadan önce kullanıcıya **özet göster ve onay al** — RESUME yanlış yazılırsa devir hatası olur:
- "Şunları içerecek: [bölüm başlıkları]. Şu commit'leri kapsayacak: [hash listesi]. Açık karar olarak şunu yazacağım: [...]. OK mi?"

Onay sonrası Write ile dosyayı oluştur.

## Çapraz referans

- Bot durumu için `bot-status` skill'inden veri çek
- Strateji geçmişi için `pool-probe`
- Önceki RESUME pattern'i: `RESUME_2026-05-*.md`
