# Learning — Phoenix-Scalp v1.0 Bundle Pre-Registration (2026-05-17)

**Sprint:** PHOENIX-SCALP v1.0 Phase 2 Research (master plan §4.3)
**Status:** PRE-REG TAMAM, kod/backtest YOK
**Output:** `reports/researcher/hypotheses/2026-05-17-scalp-bundle.md`

## 5 Hipotez Ozeti

| ID | TF | Iddia | PASS olasiligi | RED riski | Teorik dayanak |
|---|---|---|---:|---|---|
| scalp-01 | 15m | Session ORB (NY/London/Asia) breakout | %35-50 | dusuk-orta | Crabel, Mark Fisher ACD |
| scalp-02 | 5m | Session VWAP ±2sigma MR (ADX<20 chop) | %25-40 | orta | Brian Shannon AVWAP, Bollinger |
| scalp-03 | 1m | L2 order book imbalance fade | %15-25 | YUKSEK | Cont&Kukanov, Cartea/Jaimungal |
| scalp-04 | 15m | Funding spike fade (>+0.05%, <-0.03%) | %45-55 | orta | SEC8 1d kanitli + Soska |
| scalp-05 | 5m | OBV/CVD divergence + RSI confirm | %25-40 | orta-yuksek | Phoenix 1d port + Wyckoff VSA |

## Yapilan Karar Cercevesi

1. **Pre-reg disiplini:** kod yok / backtest yok. Hipotez -> kod -> backtest
   sirasi (Renaissance/D.E. Shaw kulturu).
2. **Bonferroni:** 5 hipotez x 3 TF = 15 test family -> alpha = 0.00333.
3. **Ortak backtest standartlari:** 3y rolling 13 pencere, 10 sym universe,
   fee 8 bps RT, TF-spesifik slip model (master plan §2.2), shuffle null,
   symbol-out CV, regime split, 4-stress periods.

## En Guclu / En Zayif

- **En guclu:** scalp-04 (funding fade). SEC8 1d kanitli edge + funding native
  veri + 8h cycle 15m bar ile native eslesir.
- **En zayif:** scalp-03 (1m OBI). L2 1/min cozunurluk Cont&Kukanov literatur
  tick-by-tick edge'in %80'ini kaybeder; spoofing trap; maker fill rate %50
  esigi zor. AMA: RED kanitlamak Phase 2'de L2 data feed yatirimini onler.

## Bundle Base Case

1-2 hipotez gate gecer. >=3 PASS anomali -> derinlemesine audit (overfit /
null bug). Tum 5 RED de bilim — Phoenix swing edge'inin intraday'e transfer
sinirini empirik olarak ortaya cikarir.

## Sonraki Adimlar (Researcher Track)

- [ ] Phase 4 lab_scientist backtest sonuclari geldikce her hipotezi gate'e
  karsi degerlendir (PASS / FAIL / BORDERLINE).
- [ ] RED'ler `learning_20260*_scalp_*_red.md` postmortem.
- [ ] PASS'lar Lab tournament adayi.
- [ ] Bundle index `memory/researcher/MEMORY.md` (researcher index) ekle.

## Disiplin Notu

Master plan §3 DAG'inda Phase 2 paralel Phase 1 ile baslayabilir. Bu pre-reg
Phase 2 owner deliverable. Signal Chief lookahead audit (Phase 2 paralel)
sonuclari beklenir, sonra Phase 3 risk/execution recalibration ile birlikte
Phase 4 backtest'e hazirlik.
