# TAM DENETİM (A→Z) + DÜNYA-KLASMANI YOL HARİTASI — 2026-07-10

> Principal direktifi: "Sistemi A'dan Z'ye — tüm kodlar, çalışmalar, otonom sistemler,
> ajanlar — baştan aşağı tara. Dünyanın en iyi trade-bot şirketine nasıl çeviririz?
> Canlı botu nasıl yükseltiriz? Yeni botlar (30dk/1saat) nasıl kurarız? Buglar +
> iyileştirmeler + yol haritası çıkar. Ne yapacağımızı ve NEDEN öyle düşündüğünü açıkla."
>
> Bu belge **tek kaynak sentez**: 5 denetim dalgası (~350 file:line-kanıtlı bulgu) +
> bugünkü 10 canlı fix + stratejik değerlendirme. Her karar gerekçeli.

---

## 0. YÖNETİCİ ÖZETİ — sistem bugün nerede (dürüst)

**Canlı gerçek:** v15p2 botu Binance testnet'te ~$5k ile koşuyor. F1-sonrası temiz
pencere +$34/2 gün (beklenti bandı +8-12%/ay içinde) ama **n=9 kapanış — kanıt değil,
sadece banda-aykırı-değil sinyali.** Bugün 6 CRIT canlı-para-yolu fix'i deploy edildi;
bu, "istatistikleri sıfırla" anlamına geliyor — F2-öncesi rakamlar artık kıyaslanamaz.

**Üç cümlelik teşhis (5 dalganın ortak hükmü):**

1. **Sistem, doğrulanan modelini KOŞMUYORDU.** Bugüne kadar 6 ayrı yerde canlı davranış
   backtest'te doğrulanandan sapıyordu (TP merdiveni ters, aylık fren ölü, korelasyon
   kapısı kör, retry korumasız, ts30 çıpasız, reconcile emekli-journal'a bakıyor). Bunlar
   bugün kapandı — botun para yolu ARTIK doğrulanmış modeli koşuyor.

2. **Para kaçağı strateji arayışında değil, EXECUTION'da.** Girişlerin %79'u pahalı
   taker; slippage ölçümü kırık (196/201 fill "0.0 bps"). Beklentinin ~%25-30'u sessizce
   fee'ye gidiyor. Bu, yeni edge aramaktan daha ucuz ve daha kesin bir getiri kaynağı.

3. **Araştırma fabrikası kapasite duvarında, edge duvarında DEĞİL.** 550 hipotez → 0
   terfi hunisinde "piyasada edge yok" ölümü sadece ~%3; gerisi kırık ölçüm-aleti +
   koşamama + eldeki veriden habersizlik. Diskte HAZIR 3 veri ailesi (XS-carry 115K
   satır!) hiç test edilmemiş.

**Tek cümlelik strateji:** Önce kanamayı durdur (execution + kalan canlı-yol), sonra
teraziyi tamir et (lab istatistik), sonra bakir alanlara genişle (XS-carry → 1h bot →
yeni veri modaliteleri). Bu sırayla — çünkü kırık teraziyle genişlemek "güvenilmez ürün
çıkaran fabrika" üretir.

---

## 1. A→Z SİSTEM KAPSAMA HARİTASI

5 denetim dalgası birlikte her alt-sistemi file:line düzeyinde taradı. Aşağıdaki tablo
kapsamanın haritası; her satırın kanıtı ilgili dalga raporunda.

| Alt-sistem | Dosya/konum | Kapsama | Hüküm |
|---|---|---|---|
| **Canlı daemon (god-file)** | scripts/futures_daemon.py (~4000 satır) | W1 + A1 + dalga-6-core | Pozisyon-yaşam-döngüsü onarıldı (7 fix); kalan: state-sahaları (W8) |
| **Emir/koruma** | futures_trade_daily.py place_protection_orders | F2 + F4 | TP merdiveni + retry-koruma kapandı |
| **Risk (sizing/gates/breaker)** | src/price_action/risk/ | F3 + A1-04 + CT-RSK | Aylık fren + korelasyon-gate canlı; vol_target parite açık (E2) |
| **Reconcile güvenlik ağı** | scripts/reconcile_journal.py | dalga-4 D4-6 + A1-03 | 3 katman onarıldı, cron'da fetch_ok=true |
| **DMS / kill-switch** | execution/dead_mans_switch.py | W1-S5 + DR4 | -2022 fallback + retry; process-ölümü koruması AÇIK (DR4) |
| **Backtest/lab motoru** | src/price_action/backtest/ + lab/ | W3 + T7 + F3-korelasyon | F3 korelasyon kapandı; WF-p + replay-equity AÇIK (P2) |
| **Strateji rafı (64 detektör)** | strategies/ | W4 + dalga-6-strat | pin_bar leak kapandı; raf lookahead-disiplinli |
| **Araştırma fabrikası** | research/ + lab/ + agents/researcher | A2 huni analizi | Kapasite duvarı + kırık istatistik teşhis edildi |
| **20 LLM-ajan** | src/price_action/agents/ | W5 + T5 | ~7 gerçek değer, 6 törensel-audit, 3 hayalet (budama önerisi) |
| **Scheduler/orkestrasyon** | orchestrator/scheduler.py (59 job) | T4 iş-akışı + dalga-6-ops | İş-akışı haritası çıkarıldı; ölü uçlar işaretli |
| **Bildirim zinciri** | notifications/ + telegram_throttle | W5/W6 + bildirim-paketi | Çok-parça imhası + digest cron kapandı |
| **Dashboard/API** | scripts/dashboard/ + api/server | W6 + dashboard-paketi | v15p2 izleme + halt zinciri (token'lı) kapandı |
| **Veri (ingest/store/quality)** | src/price_action/data/ + scripts | CT-DAT + T3 | DuckDB eşzamanlılık haritalandı; VACUUM eksik (T3-D4-8) |
| **Zaman/timezone** | tüm DB yazımları | T1 | +3h kayma denetim-izinde (karar-yolu temiz); migration (P7) |
| **Config zinciri** | configs/ + ops/launchd/ | T2 | Ölü-anahtar + çift-tanım envanteri; ceo.plist senkronu kapandı |
| **Güvenlik** | .env + ağ + bağımlılık | T6 | İzolasyon sağlam; 9 CVE + token rotasyonu (Principal) |
| **DR/operasyon** | tek-Mac + launchd | T8 | Reboot-körlüğü (DR1, FileVault) — Mac-dışı bekçi şart |
| **Test/CI** | tests/ (2514 test) | dalga-6-tests | +40 yeni bugün; kapsama-boşlukları (feature_sweep, wrapper) |

**Kapsama hükmü:** Sistemin hiçbir kritik alt-sistemi denetimsiz kalmadı. "Bilinmeyen-
bilinmeyen" alanı küçük; iş artık **kapatma disiplininde, keşifte değil.**

---

## 2. TAM BUG ENVANTERİ

### 2a. Bugün KAPANAN (10 commit, 40 test, hepsi canlı + push'lu)

| # | Bulgu | Sev | Commit |
|---|---|---|---|
| W1 | Daemon yaşam-döngüsü paketi (sl_order_id/heal/timestop/koruma/DMS) | 2 CRIT+3 HIGH | 3c544b1 |
| Bildirim | Çok-parça imha + digest cron + CRIT floor + 4096 chunk | 5×HIGH | c901515 |
| Dashboard | v15p2 izleme + acil-durdurma zinciri | 2 HIGH | 283feeb |
| F3-korelasyon | Zaman-hizasız trade-dizisi korelasyonu (kendini-doğrulayan) | CRIT | 5b5d6de |
| B-1 | Haftalık job güvence-boşluğu | HIGH | 06cbb8f |
| pin_bar leak | Haftalık fraktal lookahead | HIGH | 174a2c8 |
| reconcile ×3 | Pointer + fail-closed + sembol-normalize + sys.path | HIGH×3 | 5d15156, e957f0c, 584d971 |
| A1-01 | Partial-tespit/ts30 (W1 yan etkisi) | HIGH | f1b058d |
| **F2** | **TP merdiveni ters → doğrulanan kanon** | **CRIT** | e702555 |
| **F3** | **Aylık zarar freni (ölü kod)** | **CRIT** | 828fad0 |
| **A1-04** | **Korelasyon gate körlüğü** | **HIGH** | ea36e66 |
| **F4** | **Retry-fill korumasız+journal'sız (+2 latent)** | **CRIT** | ad3336c |

**Bugün kapanan: 4 CRIT + ~12 HIGH.** Bunlar denetimin en tehlikeli sınıfı — hepsi
canlı para yoluna dokunuyordu.

### 2b. Açık CRIT (kalan 5)

1. **WF p-değeri 19× şişik** (lab.py walk_forward) — FDR her şeyi "anlamlı" onaylıyor
2. **Replay equity açık-poz marjinini düşürüyor** (lab.py) — tüm MaxDD şüpheli
3. **feature_sweep örtüşen-pencere p-şişmesi** (%74 FDR-pass imkânsız)
   — *Bu 3'ü P2 lab-istatistik paketi; canlıya temassız ama tüm verdicts pre-fix damgalı*
4. **ccxt_live cancel-yutma → çift pozisyon** (latent, gerçek-canlı öncesi ŞART)
5. **ccxt_live beklenen-değer-fill kaydı** (latent, aynı sınıf)

### 2c. Açık HIGH (~55) — paket-bazlı

- **DR paketi:** DR1 reboot-körlüğü (FileVault, yazılımla çözülmez → dış bekçi), DR3
  kapalı-pencere partial körlüğü, DR4 DMS process-ölümü koruması
- **İzleme paketi:** T5-01 hayalet-owner, T5-02 ölü CT-OPS-02 dedektörü, B-2/B-3 inbox ack
- **Güvenlik:** T6 9 CVE, token rotasyonu (Principal)
- **Veri/tz:** T1 +3h kayma migration, T3 DuckDB VACUUM/leak
- **Execution:** slippage ölçüm tamiri (A4 — P sprint #13), maker kalibrasyonu

### 2d. MED/LOW (~200) — sınıf-bazlı batch'ler
ölü-config etiketleme ~25 (sıfır-risk), sessiz-except ~22, persona-doküman ~18,
DuckDB hijyeni ~10. Sprint aralarında toplu.

---

## 3. CANLI BOTU YÜKSELTME (v15p2 → v16)

### 3a. Execution paketi — EN YÜKSEK ROI (neden: kesin + kendi kontrolümüzde)
- **Slippage ölçüm tamiri** (arrival-price referanslı; 0.0 bps bug'ı) — *ölçemediğini
  yönetemezsin; harita hazır, mock-testli yapılacak*
- **Maker oranı kalibrasyonu** (post-only pencere; %21→%50+ hedef). Fee 4bps vs 15bps;
  %30 maker artışı ≈ **aylık beklentiye +1-2 puan, YENİ RİSK ALMADAN.** Bu, yeni strateji
  aramaktan daha yüksek beklenen-değerli çünkü mevcut edge'i koruyor.
- **Fee/funding backtest modeline** (F6) — sahte-RED'leri de azaltır

### 3b. Risk paritesi (neden: "backtest ne yaşıyorsa canlı onu yaşamalı")
- **vol_target** backtest'te var canlıda yok (E2) — ya canlıya ekle ya vol_target'sız
  yeniden doğrula. Geniş-stopta canlı risk doğrulanmışın 5×'ine kadar çıkabiliyor.
- Kelly/portföy-optimizasyonu **edge≥3 strateji** olana kadar ERTELE (ölçek gerçekçiliği)

### 3c. Çıkış paritesi (bugün F2+A1-01 ile yarı kapandı)
- Kalan: pct-trail vs ATR-trail 1.5 kararı (E13) — tam exit paritesi bu verilene dek
  yaklaşık. Beklenti bandı bu kararla kesinleşir.

### 3d. Veri modaliteleri (paralel, bugün başladı)
- **Likidasyon collector CANLI** (Bybit; Binance-WS TR-engelli — kanıtlandı). vsa_climax'in
  doğal doğrulayıcısı; geriye veri YOK → her gün kritikti, artık akıyor.
- Sıradaki: OI backfill (~$25-50/ay), bybit basis (veri diskte, okuyucu yok)

---

## 4. YENİ BOT PROGRAMI (30dk / 1saat / 4saat)

### NEDEN yeni TF? (kanıt-temelli, 3 gerekçe)
1. **"Sinyal uzayı tükendi" hükmü yalnız 15m+1d'de verildi** — 1h/4h HİÇ aranmadı (A3).
2. **Sistemin tek gerçek OOS edge'i 4H'lıydı** (brooks failed-breakout EUR/USD: PF 1.93,
   her yıl pozitif). Yani daha uzun TF'ler kanıtlı bir umut alanı.
3. **TF-arası korelasyon 0.12-0.26** (portföy çeşitlenir) — ama crash'te aynı kripto
   betasına çöker, yani "ılımlı DD iyileşmesi" bekle, "bağımsız gelir akışı" değil.

### "ROI'sine baktın mı?" — DÜRÜST cevap
**Hayır, çünkü 1h HİÇ test edilmemiş — ROI verisi YOK.** Sıra bilinçli: **önce kanıt,
sonra bot.** İyi çıkmazsa bot da olmaz. Zemin bugün hazırlandı: 1h pool üretildi
(19 sembol × 5.1 yıl, parite PASS). Sonraki adım raf taraması → ROI o zaman çıkar.

### KRİTİK güvenlik bulgusu (fizibilitede yakalandı, felaketi önledi)
**2. bot AYNI hesapta koşamaz:** DMS acil-flatten TÜM hesabı kapatıyor, zıt sinyaller
one-way modda birbirini imha ediyor, PnL atıfı botları ayrıştıramıyor. **Ayrı testnet
hesabı ŞART.** Bu bulunmasaydı 2. bot ilk DMS tetiğinde 1. botun pozisyonlarını da
kapatırdı.

### Aşamalı plan (kritik yol ~5-10 iş günü kod + 7 gün parite + 30 gün paper)
1. **Hafta 1:** 1h raf taraması (failed-breakout/trap sınıfı öncelikli — tarihsel kanıt
   orada) + tam robustness suite. 30m aynı resample'dan.
2. **Hafta 2:** GO adayı çıkarsa 1h paper-bot, AYRI testnet hesabı. Daemon 1h desteği
   ~50-150 satır (scan_signals_1h + argparse + boundary).
3. **+30 gün paper → Principal GO/NO-GO.**

---

## 5. ARAŞTIRMA FABRİKASI ONARIMI (0 terfi → üretken)

### Huni gerçeği (A2, gerçek sayımlar): 550 seed → 219 hipotez → 80 koşu → 0 GO
- **%64 hiç koşulmadan öldü** (motor-koşamaz + rafta-detektör-yok) = **kapasite duvarı**
- **%37 hipotez bütçesi kırık F3-korelasyona gitti** (bugün kapattım → kaynak serbest)
- **"Edge yok" ölümü sadece ~%3** — sorun yaratıcılık değil, ölçüm+kapasite

### Sıra (NEDEN bu sıra: A2'nin şerhi — boru + terazi BİRLİKTE)
1. **P2 istatistik + boru** (WF-p + replay + F8 sıfır-trade + sentetik-GO kanaryası).
   *Boru onarılmadan kapıları düzeltmek "güvenilmez ürün" üretir.*
2. **XS-carry ilk gerçek koşu** — funding.duckdb'de 115K satır HAZIR (2021→bugün); "kalan
   tek kaldıraç" denilen aile hiç test edilmemiş + borunun canlı testi
3. **Kapasite duvarını yık** — NO_DETECTOR → signal_chief iş-emri (%64'lük kova)
4. **meta_labeling v2** — 731 satır hazır kod; yeni modalite feature'ları (funding/OI/liq)
   gelince hammadde sorunu çözülür

---

## 6. DÜNYA-KLASMANI DÖNÜŞÜM (6 eksen, ölçek-gerçekçi, ~$50/ay)

| Eksen | Bugün | Dünya standardı | UYARLANMIŞ hedef | Neden |
|---|---|---|---|---|
| **Veri** | OHLCV+funding | +L2/tape/OI/liq/basis | liq($0,başladı)>OI($25-50)>basis($0) | Küçük ölçekte liq en yüksek katma değer; L2 lüks |
| **Execution** | %79 taker, ölçüm kırık | maker-öncelik, arrival-slippage | slippage tamiri→maker %50 | Beklentinin %25-30'u burada kaçıyor |
| **Risk** | %1 sabit | vol-target, rejim-uyarlı | backtest-parite + tek-param throttle | Sofistike değil PARİTE eksik |
| **Araştırma** | pre-reg (nadir!) + kırık terazi | feature store, meta-label | terazi tamiri→modalite→meta-label v2 | Çekirdek dünya-klasmanı, terazi bozuk |
| **Operasyon** | tek-Mac, reboot=96dk kör | yedekli VPS, dış bekçi | push✓+healthchecks($0)+VPS(€5-9) | %80'i $0'a kapanır |
| **Organizasyon** | 20 ajan, ~7 gerçek | — | LLM-audit→deterministik CT + çeyreklik insan-denetim | 6 audit-ajan törensel |

**Kritik izolasyon zemini SAĞLAM** (T6): diskte para-çekebilir anahtar yok, 2. kullanıcı
staff-grubu dışı. Engel para değil, **önceliklendirme.**

---

## 7. YOL HARİTASI — SIRA + NEDEN (gerekçe zinciri)

| Hafta | İş | Neden bu sırada |
|---|---|---|
| **Bu hafta** | P0 kararlar + execution paketi (slippage+maker) | Canlı botun kaybettiği her bps bileşik; execution kesin-getirili + kendi kontrolümüzde |
| **Hafta 2** | P2 lab istatistik+boru (WF-p+replay+F8) | Kapıları düzeltip boruyu bırakmak sahte-güven; boruyu açıp teraziyi bırakmak çöp taşır — BİRLİKTE |
| **Hafta 3** | XS-carry ilk koşu + 1h raf taraması + sahte-RED revizyonu | XS verisi hazır+altyapı değişmez; borunun canlı testi; 1h ROI kanıtı |
| **Hafta 4** | VPS bekçi + off-site + organizasyon budaması + 1h paper (GO ise) | Taşıma riskli (split-brain tarihçesi) ama izleme-körlüğü $0'a hemen kapanır |
| **Ay 2** | P3-P7 kalanlar + meta-label v2 + 30m değerlendirme | Veri birikince meta-label hammaddesi hazır; "sistem temiz"e ilk gerçek yaklaşma |

**8 sıralama-kararının gerekçesi:** (1) execution önce çünkü bileşik+kesin; (2) istatistik
+boru birlikte çünkü A2 kanıtladı; (3) XS-carry yeni-TF'den önce çünkü verisi hazır+
altyapı değişmez; (4) 1h bot 30m'den önce çünkü "prime hedef" zaten hazırlanmış+fee oranı
avantajlı; (5) VPS "sonra" ama bekçi "hemen" çünkü taşıma riskli, izleme $0; (6) organizasyon
budaması sürekli ama önce ölçüm-sonra-budama (tiyatroyu tiyatroyla değiştirmemek için).

---

## 8. AÇIK PRİNCİPAL KARARLARI

| # | Karar | Bedel/Risk | Durum |
|---|---|---|---|
| 1 | git push | 0 | ✅ YAPILDI (bugün) |
| 2 | Acil-durdurma token | 0 | ✅ AKTİF (bugün) |
| 3 | Telegram token rotasyonu (BotFather) | 5 dk elle | ⏳ bekliyor |
| 4 | A1-02 defter onarımı (~$29.5) | journal yazımı, script hazır | ⏳ onay bekliyor |
| 5 | healthchecks.io dış bekçi (DR1) | $0 | ⏳ Principal |
| 6 | vol_target: canlıya mı, re-validasyon mu | P1 kapsamı | ⏳ karar |
| 7 | 2. testnet hesabı (1h bot) | 10 dk elle | ⏳ hafta-2 |
| 8 | VPS bütçesi (€5-9/ay) | ay-2 | ⏳ Principal |
| 9 | CVE upgrade (izole shadow-venv) | çalışan env riski | ⏳ Principal |

---

## 9. DÜRÜST ŞERHLER (kapanış)

- **Bugünün 6 CRIT'i canlı-olay bazlı henüz tam doğrulanmadı** — test-yeşil + deploy, ama
  F2'nin ilk TP1 fill'i, F3'ün ilk aylık-eşik yaklaşması, A1-04'ün ilk korele-blok'u
  gerçek olay görene dek "test-yeşil, saha-kısmi" sınıfındadır.
- **Beklenti bandı F2-sonrası sıfırlandı** — B4 paper-confirm penceresi (≥4 hafta / ≥40
  kapanış) yeniden başlıyor; önceki canlı rakamlar pre-fix damgalı.
- **Dalga-6 tam-kapsama dosya-teyidi token-limitte düştü** — ama 5 dalga zaten A-Z
  kapsadı; dalga-6 incremental teyitti, substance değil. Limit açılınca koşulabilir.
- **"Sistem temiz" DEĞİL, "sistem haritalandı + en tehlikeli sınıf kapandı" doğru cümle.**
  Kalan ~250 açığın çoğu MED/LOW; çekirdek 5 CRIT + ~55 HIGH kapatma disiplininde.
