# YOL HARİTASI — 2026-07-09 (Dalga-5 Sentezi)

> Principal direktifi: "Full review + dünyanın en iyi trade bot şirketi + canlı botu
> yükselt + yeni TF botları + buglar/iyileştirmeler/roadmap, gerekçeleriyle."
> Kaynak: 5 dalga denetim (≈350 bulgu) + dalga-5'in 5 stratejik raporu
> (reports/audit/dalga5/A1..A5). Her öneri kanıt-referanslı; hiçbiri tahmin değil.

---

## 0. YÖNETİCİ ÖZETİ

**Sistem bugün:** v15p2 canlı (testnet $5k), NET +$21.7 (7.3 gün), F1-sonrası temiz
pencere +$33.9/2.2 gün — beklenti bandının (+8-12%/ay) içinde ama n=9, kanıt değil.
Denetim: ≈350 belgelenmiş bulgu, ~55 kapalı, doğrulanmış açık **10 CRIT + ~60 HIGH**.

**Üç büyük dürüst teşhis (dalga-5'in ana katkısı):**

1. **Para kaçağı execution'da:** Girişlerin %79'u taker; slippage ölçümü kırık
   (196/201 fill "0.0 bps"). Beklentinin ~%25-30'u sessizce fee'ye gidiyor. Bu,
   yeni strateji aramaktan daha ucuz ve daha kesin bir getiri kaynağı. (A4)
2. **Araştırma fabrikası kapasite duvarında, edge duvarında değil:** 550 seed →
   0 terfi hunisinde "piyasada edge yok" ölümü sadece ~%3. %64 hiç koşulmadan
   öldü; bütçenin %37'si kırık istatistiğin (F3) motive ettiği temaya gitti;
   diskte verisi HAZIR 3 aile (XS-carry 114.949 satır funding!) hiç denenmedi. (A2)
3. **1h/4h meşru bakir alan:** "Sinyal uzayı tükendi" hükmü yalnız 15m+1d'de
   verildi. Sistemin tek tarihsel OOS edge'i 4H'lıydı (brooks EUR/USD PF 1.93).
   1h pool 1-2 günde 15m'den resample edilebilir. (A3)

**Tek cümlelik strateji:** Önce kanamayı durdur (P1 canlı-yol + execution), sonra
teraziyi tamir et (P2 istatistik + boru), sonra yeni alanlara genişle (XS-carry,
1h bot, yeni veri modaliteleri) — bu sırayla, çünkü kırık teraziyle genişlemek
"güvenilmez ürün çıkaran fabrika" üretir (A2'nin şerhi).

---

## 1. BUG ENVANTERİ — DOĞRULANMIŞ AÇIKLAR

Master tablo: `reports/audit/dalga5/A5_acik_bulgu_master.md` (artık tek kaynak).
Örnekleme dürüstlüğü: 14 bulgu koda karşı test edildi → 12 açık teyit, 2 bayat düşüldü.

### Açık CRIT'ler (10)

| ID | Özet | Paket |
|---|---|---|
| W3-C1 | Replay equity açık-poz marjinini düşürüyor (lab.py:1137 `equity=cash`) → tüm MaxDD şüpheli | P2 |
| W3-C2 | WF p-değerleri `t=sr·√n` ile ~19× şişik → FDR anlamsız | P2 |
| D4T7-F1 | feature_sweep örtüşen-pencere p-şişmesi (%74 FDR-pass imkânsız) | P2 |
| W8-C1/C2 | ccxt_live cancel-yutma + beklenen-değer-fill kaydı (latent, gerçek-canlı ŞARTI) | P3 |
| DR1 | Reboot→login'e kadar filo offline (96dk kanıtlı; FileVault → yazılımla çözülmez) | P0 karar |
| A1-01 | **YENİ:** W1-S1 yan etkisi — partial tespiti yapısal öldü → ts30 runner time-stop canlıda ateşlenemiyor | P1 |
| A1-02 | **YENİ:** 8 Tem kazası kalıcı defter hasarı (~$29.5 eksik; idempotency doğru kapanışı çöpe attı) | P1 (veri onarımı, Principal onaylı) |
| F2 | TP merdiveni ters (TP1=2-2.5R/TP2=1.5R; doğrulanan 1R/1.5R) — R-dağılımı kıyaslanamaz | P1 |
| F3-breaker | Aylık breaker ölü kod (canlıda aylık fren YOK) | P1 |
| F4 | Deferred-retry başarısı korumasız+journal'sız pozisyon | P1 |

### Açık HIGH'lar (~60) — öne çıkanlar

- **A1-04 (YENİ):** Korelasyon gate canlıda kör — açık pozisyon sembolü o barki sinyal matrisinde yoksa gate (True, 1.0) dönüyor
- **A1-05 (YENİ):** VSA SL çapası fiilen ölü (hep ATR-fallback) — parite bozulmuyor ama tasarım-dışı; fix yeniden-validasyon ister
- **A1-06..17 (YENİ):** cooldown canlı yolda yok; daemon kapanışta signal status kapatmıyor (heal zorunlu çöpçü); heal koruma satırını emekli etmiyor (zombi 'placed'); PROT_FILL %100 triggerPrice fallback...
- DR3 (kapalı-pencere partial körlüğü), DR4 (DMS process-ölümü koruması yok), T5-01/02 (hayalet owner + ölü CT-OPS-02), B-2/B-3 (inbox ack), T6 (9 CVE + token), T1 (+3h ts kayması), D4T7-F6 (fee/funding modeli)

### MED/LOW (~195)
Sınıf-bazlı (A5): ölü-config etiketleme ~25 (sıfır-risk batch), sessiz-except ~22,
persona-doküman ~18, DuckDB hijyeni ~10... Sprint aralarında batch'lerle.

---

## 2. KAPANIŞ PAKETLERİ — SIRA VE GEREKÇE

**P0 — Principal karar günü (bugün/yarın, S):**
1. `git push` (branch main'den 170, origin'den ~75 commit ileride — tek disk = şirket tarihi + tüm fix'ler)
2. Telegram token rotasyonu (BotFather — 42 gündür bekliyor)
3. DR1 kararı: Mac-dışı dead-man bekçisi (healthchecks.io, $0) — reboot körlüğünün tek gerçek çaresi
4. PA_DASHBOARD_ADMIN_TOKEN set (acil-durdurma butonu bugün fiilen pasif — A1 teyidi)
5. E2/F9 kararları (vol_target canlıya mı, yeniden-validasyon mu; dd_throttle state)
6. A1-02 defter onarımı onayı (~$29.5; income-kanıtlı düzeltme scripti ben hazırlarım)

**P1 — Canlı para yolu (M-L, 2-4 gün, test-first):**
A1-01 partial-tespit onarımı (ts30'u geri getirir) → F2 TP merdiveni → F3 aylık
breaker → F4 retry-koruma → A1-04 korelasyon gate → W8 state sahaları.
*Gerekçe: para şu anda burada dönüyor; her gün açık kalması bileşik maliyet.*

**P2 — Lab istatistik + boru (L, 3-5 gün):**
W3-C1 replay equity → W3-C2 WF p → feature_sweep p-şişmesi → fee/funding modeli
(F6) → F8 sıfır-trade placeholder → sentetik-GO kanaryası (A2-Ö3).
*Gerekçe: A2'nin şerhi — boru + terazi birlikte düzelmeli; sadece kapıları
gevşetmek "güvenilmez ürün" üretir. Tüm eski verdicts'e pre-fix damgası.*

**P3 — Reconcile/DR kalanları (M):** DR3 partial-backfill, DMS ayrı-process
bekçi, ccxt_live kardeşleri (gerçek-canlı öncesi şart sınıfı).

**P4 — İzleme (M):** dış bekçi entegrasyonu, CT-OPS-02 diriltme, hayalet-owner
düzeltme, inbox tüketici matrisi (B-2/B-3).

**P5-P7:** Test/CI sertleştirme → hafıza/persona onarımı → config fail-closed +
tz-migration (tek koordineli commit — bağımlı sorgular aynı anda).

---

## 3. CANLI BOTU YÜKSELTME (v15p2 → v16 yolu)

**3a. Execution paketi (en yüksek ROI, ~1 hafta):**
- Slippage ölçüm tamiri (arrival-price referanslı; 0.0 bps bug'ı) — *ölçemediğini yönetemezsin*
- Post-only pencere kalibrasyonu: maker %21 → %50+ hedef (fee 4bps vs 15bps;
  %30 maker artışı ≈ aylık beklentiye +1-2 puan, YENİ RİSK ALMADAN)
- Fee/funding'in backtest modeline doğru yansıtılması (F6) — sahte-RED'leri de azaltır

**3b. Risk paritesi:** vol_target + rejim-uyarlı sizing backtest'te var canlıda
yok (E2) — ya canlıya ekle ya vol_target'sız yeniden doğrula. "Backtest ne
yaşıyorsa canlı onu yaşar" ilkesi (A4-eksen3). Kelly/portföy-optimizasyonu
edge≥3 strateji olana kadar ERTELE (ölçek gerçekçiliği).

**3c. Çıkış bacağı onarımı:** A1-01 (ts30 geri gelsin) + F2 (TP merdiveni) —
turnuva-valide çıkış modeli şu an canlıda YARIM çalışıyor; GO/NO-GO kriter-3
yorumu bunlar düzelmeden yapılamaz.

**3d. Veri modaliteleri (paralel, $0-50/ay):** Likidasyon WS collector ($0,
BUGÜN başlamalı — geriye veri YOK, her gün kayıp) → OI backfill (~$25-50/ay)
→ bybit basis (veri diskte, okuyucu yok).

---

## 4. ARAŞTIRMA FABRİKASI ONARIMI (0 terfi → üretken)

Sıra (A2): **istatistik+boru (P2) → XS-carry ilk koşu → kapasite → hijyen**

1. **XS-carry ilk gerçek koşu** — funding.duckdb'de 114.949 satır (2021→bugün,
   19 sembol) HAZIR; "kalan tek kaldıraç" denilen aile hiç test edilmemiş.
   Borunun canlı testi de olur (sentetik-GO kanaryasıyla birlikte).
2. **Kapasite duvarını yık (Ö1):** NO_DETECTOR/NOT_EXECUTABLE → signal_chief
   iş-emri + raf genişleyince oto-rerun. %64'lük ölüm kovası burada.
3. **Jeneratöre kapasite-manifesti + test-ledger (Ö2):** %57 tekrar-koşu israfı
   + "dış veri yok" sahte-ölümleri biter (F&G 2.000 satır yerelde!).
4. **Seed yaşam-döngüsü (Ö5):** ACTIVE→FALSIFIED/BLOCKED durum makinesi —
   tek seed'in 162 abort-doc yakması bir daha olmasın.
5. **Sahte-RED revizyonu:** order-block-4h (Sharpe 1.99) + grimes tp-çelişkisi
   düzelen fee modeliyle YENİDEN koşulsun.
6. **meta_labeling v2:** 731 satır hazır kod; yeni modalite feature'ları
   (funding/OI/liq) gelince hammadde sorunu çözülür — sıra o zaman.

---

## 5. YENİ BOT PROGRAMI (30m / 1h / 4h)

**Neden meşru:** "Tükendi" hükmü 1h/4h'yi kapsamıyor (A3); tek tarihsel OOS
edge 4H'lıydı; TF-arası korelasyon 0.12-0.26 (ılımlı çeşitlendirme — ama crash'te
aynı beta, "bağımsız gelir" bekleme).

**Aşamalı plan:**
1. **Hafta 1:** `build_pool_1h.py` — 15m'den resample (19 sembol × 5.1 yıl) +
   parite doğrulaması (verify_resample_parity emsali). 30m aynı script'ten.
   *Sıfır canlı risk; tf_exploration'ın NO_POOL_DATA duran kolonunu doldurur.*
2. **Hafta 1-2:** Raf taraması 1h/4h pool'da (failed-breakout/trap sınıfı
   öncelikli — tarihsel kanıt orada) + tam robustness suite.
3. **Hafta 2-3:** GO adayı çıkarsa: 1h paper-bot. **AYRI testnet hesabı ŞART**
   (A3-kritik: DMS hesap-geneli flatten, one-way netleşme, PnL atıf çakışması).
   Daemon 1h desteği ~50-150 satır (scan_signals_1h + argparse + boundary).
4. **+30 gün paper → Principal GO/NO-GO.**

Kritik yol: ~5-10 iş günü kod + 7 gün parite + 30 gün paper.

---

## 6. DÜNYA-KLASMANI ALTYAPI (ölçek-gerçekçi)

**Operasyon (%80'i $0, toplam ~$10-15/ay):**
push (bugün) → healthchecks.io dış bekçi ($0) → rclone off-site yedek (~$2/ay)
→ Hetzner VPS'e önce bekçi, sonra para-hattı (€5-9/ay). Hedef bölünme:
**VPS = deterministik para hattı, Mac = araştırma fabrikası.** DR1'in (reboot
körlüğü) tek gerçek çözümü de bu.

**Organizasyon budaması (A4-eksen6):** 20 koltuktan ~7 gerçek değer üretiyor.
6 LLM-audit ajanı törensel (gece elle ~140 bulgu vs otomatik ~0) → deterministik
CT-kontrollerine çevir + çeyreklik insan-yönetimli derin-denetim kurumsallaşsın.
Tasarruf (~$50-90/ay LLM) → eval harness'e. Hayalet koltuklar (execution_chief,
portfolio_manager kodu yok) ya doldurulsun ya silinsin.

**Bilinçli SKIP'ler (gerekçeli):** L2/tape verisi (15m bar sistemine lüks),
Kelly-optimal sizing (edge<3), müşteri/API ürünleşmesi (önce kendi edge'ini
kanıtla), HFT-sınıfı execution (ölçek yok).

---

## 7. ZAMAN ÇİZELGESİ (öneri)

| Hafta | İş | Çıktı |
|---|---|---|
| Bu hafta | P0 kararlar + P1 canlı-yol + liq-WS collector başlat | Kanama durdu; veri birikmeye başladı |
| Hafta 2 | P2 istatistik+boru + slippage/maker paketi + 1h pool | Terazi doğru; execution ROI'si ölçülüyor |
| Hafta 3 | XS-carry ilk koşu + sahte-RED revizyonları + 1h raf taraması | Fabrikanın ilk dürüst verdicts'i |
| Hafta 4 | VPS bekçi + off-site + organizasyon budaması + 1h paper-bot (GO ise) | DR kapalı; 2. bot paper'da |
| Ay 2 | P3-P7 kalanlar + meta-labeling v2 (veri birikince) + 30m değerlendirme | "Sistem temiz" cümlesine ilk gerçek yaklaşma |

**Toplam fatura:** ~1 ay yoğun iş + ~$50/ay işletme. Engel para değil, sıralama.

---

## 8. NEDEN BU SIRA? (gerekçe zinciri)

1. **Execution/P1 önce** çünkü canlı botun kaybettiği her bps bileşik; yeni
   strateji aramaktan kesin getirili ve tamamen kendi kontrolümüzde.
2. **İstatistik+boru birlikte (P2)** çünkü A2 kanıtladı: kapıları düzeltip
   boruyu bırakmak sahte-güven üretir; boruyu açıp teraziyi bırakmak çöp taşır.
3. **XS-carry yeni-TF'den önce** çünkü verisi hazır, altyapı değişikliği
   istemiyor, ve boru onarımının canlı testi.
4. **1h bot 30m'den önce** çünkü 1h "prime hedef" olarak zaten hazırlanmış
   (manifest+config taslağı var) ve bar sayısı/fee oranı 30m'den avantajlı.
5. **VPS "sonra" ama bekçi "hemen"** çünkü taşıma riskli bir operasyon (split-brain
   tarihçesi), ama izleme körlüğü (DR1: 96dk) bugün $0'a kapanabilir.
6. **Organizasyon budaması sürekli-iş** çünkü token tasarrufu her ay bileşik;
   ama önce ölçüm (eval), sonra budama — tiyatroyu tiyatroyla değiştirmemek için.

---

## 9. AÇIK PRİNCİPAL KARARLARI (özet)

| # | Karar | Bedel/Risk |
|---|---|---|
| 1 | git push onayı | 0 — DR riskinin ~%80'i ölür |
| 2 | Token rotasyonu (BotFather) | 5 dk elle iş |
| 3 | healthchecks.io hesabı + DR1 bekçi | $0 |
| 4 | PA_DASHBOARD_ADMIN_TOKEN | acil-durdurma aktifleşir |
| 5 | A1-02 defter onarımı (~$29.5) | journal yazımı, script hazır olacak |
| 6 | vol_target: canlıya mı, re-validasyon mu | P1 kapsamını belirler |
| 7 | 2. testnet hesabı açılması (1h bot için) | 10 dk elle iş |
| 8 | VPS bütçesi (€5-9/ay) | ay-2 operasyon hedefi |
