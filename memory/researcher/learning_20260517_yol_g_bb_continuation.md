# Learning Note: Yol G - BB Band Continuation (2026-05-17)

## RED (pre-reg WR gate single miss; mR+p strong)

### Hipotez
HYP-2026-05-17-bb-continuation-15m: BB close-beyond + RSI extreme + momentum
candle -> trigger direction CONTINUATION (15m crypto, fade'in tam tersi).

### 3-line verdict
1. Standalone n=16,340, mR +0.20, p=0.000 - **istatistiksel olarak guclu edge**.
2. AMA WR %51.4 < %55 gate (3.6pp eksik) -> pre-reg "HEPSI" disiplinine gore RED.
3. Ensemble retest pre-reg karar agacina gore yapilmadi (PASS yok); R4 baseline
   mandate gap (Neg 7, CV 144) bu sprintte kapatilmadi.

### Yan-bulgu (Lab tournament adayi)
mR +0.20 + p=0.000 + 3/3 regime + symout sapma %5.8 + concentration %11.3
kombinasyonu = **gercek edge**. High-RR profile (WR border, mR strong).
1.2R TP biraz tight - 2R TP variant retesti Lab'in W3 challenger sprint
adayi (post-hoc, pre-reg ihlali degil cunku farkli hipotez).

### Critical learning - pre-reg disiplin agitasyonu

Bu sonuc "borderline disipliner test." Pre-reg "HEPSI zorunlu" yazdim.
Sonuc 5/6 PASS, 1 FAIL. Eski Researcher iki yola sapardi:
- A) "WR border, mR muthi, partial PASS yapip ensemble dene"
- B) "Pre-reg disiplini, RED"

Ben B) ile gittim. Sebep:
1. Pre-reg disiplini bozulursa **p-hacking** baslar. Bir kez "WR esnek
   yorumlanir" denirse, sonraki sprintte "ya neg ay esnek yorumlanirsa"
   denir.
2. Yan-bulgu Lab'a backlog olarak gitmeli - **farkli sprint, farkli
   pre-reg, farkli gate.**
3. RED'i dururce kabul etmek mevcut surun parcasi - 5 sprint zinciri MR
   pool RED dedi, bu 6. RED'i de ayni standartla raporlamak gercegi
   gosteriyor.

### Yapisal bulgu (6 sprint zinciri)

15m R4 TOP-4 pool **lokal optimum**. Strategy ekleme hipotezi resmi
olarak RED. Sonraki path:

- **Engine/risk parameter** (cooldown sweep, side-cond DD, pyramid R)
- **TF pivot** (1h - SEC32 sonrasi)
- **Multi-pool ensemble** (1d champion + 15m R4 + 1h pool weighted)

Yeni standalone strategy aramak bos zaman.

### Methodology playbook update

Pre-reg "HEPSI" gate'leri secerken **safety margin** kullan:
- Pre-test (raw fade rev) WR %59.6 idi
- Pre-reg gate %55 koydum (4.6pp safety)
- Gercek %51.4 geldi - safety margin yetersizmis (8.2pp drop)
- Sebep: fee adjusment %59.6'da yapildi (10bps RT), AMA gercek backtest
  fee+slippage stack daha agir (taker 7.5bps x2 + slip 5bps = 20bps RT;
  ben 10bps proxy kullandim, %2x faktor underestimation).

**Future pre-reg gate calibration:** raw "ideal" metricten en az %15
asagi cik (1 sigma noise + fee underestimation buffer). Yol G'de %55
yerine %52-53 gate olsaydi PASS olurdu - AMA o zaman da "post-hoc cherry
gate" suclamasi gelir. Daha iyisi: **pre-reg multiple gate levels**:
- "Tier-A PASS" (strict): >= %55 -> ensemble + production candidate
- "Tier-B PASS" (relaxed): >= %50 + mR>+0.15 -> ensemble only
- "Tier-C RED": < %50 OR mR<+0.10 -> archive

Bu disiplini bozmadan "partial PASS" tanir.

### Reproducibility
- pre-reg: `memory/researcher/hypotheses/2026-05-17-bb-continuation-15m.md` (15:10:56Z)
- code: `src/price_action/strategies/bb_band_continuation.py`
- script: `scripts/sec_s5_yol_g_standalone.py`
- data: `data/sec_s5_yol_g_bb_cont_v1_pool.pkl` (n=16,340)
- report: `reports/researcher/2026-05-17_yol_g_summary.md`
