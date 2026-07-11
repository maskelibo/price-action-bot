# Crypto 15m v15p2 — adil baseline raporu

## Karar

**BASELINE_MEASURED_NO_DEPLOYMENT**

Bu çıktı yalnızca ölçülmüş `FAIR_LIVE_POLICY_PROXY` baseline'ıdır; kazanan ilanı, holdout, paper veya canlı deployment yetkisi vermez.

## Senaryo özeti

| Senaryo | Tam getiri | Tam DD | H-pencere trim/ay | Negatif ay | Kötü ay | Kapalı episode | Partial fill | Turnover | Maliyet | Funding | Terminal açık |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B | -79.69% | 79.71% | -2.03% | 33 | -5.67% | 6228 | 4050 | 540.28x | 6593.10 USDT | 7.22 USDT | 5 |
| C2 | -94.14% | 94.14% | -3.71% | 36 | -9.08% | 5806 | 3763 | 542.74x | 8066.01 USDT | 9.64 USDT | 4 |
| H | -98.27% | 98.27% | -5.39% | 36 | -12.31% | 5485 | 3550 | 572.74x | 2909.28 USDT | 3.03 USDT | 2 |

## Ham sinyal karar kanıtı

- Ham strateji emisyonu (özellik geçmişi dahil): `117777`
- Değerlendirme aralığı ham emisyonu: `114046`
- Uygun geçmiş intenti: `15751`
- Reddedilen emisyon: `102026`
- Motora verilen değerlendirme intenti: `14106`
- Karar nedenleri: `accepted=15751, decision_stop_distance_below_minimum=102026`
- Karar ledger SHA-256: `6beb8120af46267d32fc671ed41b9628f7148c722b3327bee476ae129510e5e0`
- Kabul edilen karar satırları değerlendirme intentleriyle eksiksiz ve sıralı olarak uzlaştırıldı.

## H pseudo-OOS istikrarı

- Ortalama ay: `-5.62%`
- Medyan ay: `-5.01%`
- %10 simetrik trimli ay: `-5.39%`
- Negatif ay: `36/36`
- `< -%1` ay: `36/36`
- En kötü ay: `-12.31%`
- Tam dönem 15m MTM DD: `98.27%`

## Altı kesintisiz H dilimi

| Fold | Dönem | Getiri | DD | Negatif ay |
|---:|:---|---:|---:|---:|
| 1 | 2023-06–2023-12 | -22.76% | 22.88% | 6 |
| 2 | 2023-12–2024-06 | -37.94% | 38.03% | 6 |
| 3 | 2024-06–2024-12 | -30.18% | 30.18% | 6 |
| 4 | 2024-12–2025-06 | -37.34% | 37.35% | 6 |
| 5 | 2025-06–2025-12 | -25.25% | 25.50% | 6 |
| 6 | 2025-12–2026-06 | -21.64% | 21.87% | 6 |

## Ham önkayıt sınırları (12/12)

- `funding_snapshot_not_rebuilt_under_v3_vendor_lineage`
- `four_symbols_retain_two_official_vendor_gap_windows_without_synthetic_rows`
- `static_survivor_primary_universe`
- `no_historical_tick_lot_or_margin_tier_replay`
- `no_historical_order_book_queue_or_submission_latency`
- `no_point_in_time_FNG_snapshot`
- `no_exchange_state_stale_or_rate_limit_path`
- `next_open_is_a_research_execution_proxy_not_a_fill_claim`
- `deployed_VSA_confirmation_close_plus_minus_2ATR_fallback_is_preserved_not_corrected`
- `inert_YAML_exit_engine_differs_from_live_wrapper_30_30_40_authority`
- `no_historical_availableBalance_or_exchange_margin_state`
- `no_exact_historical_L1_rounding_trailing_or_time_stop_mark_sampling`
- `replay_time_stop_is_unconditional_after_30_bars_but_live_rechecks_1R_mark`
- `historical_pseudo_OOS_is_not_genuine_prospective_evidence`

## Ayrıntılı zorunlu açıklamalar

- `funding_snapshot_not_rebuilt_under_v3_vendor_lineage`: Funding uses the independently frozen v1 snapshot; it was not rebuilt or vendor-checksum-audited by the V3 market-data process.
- `official_vendor_gaps_preserved`: SOL, ZEC, NEAR, and FIL retain two official vendor gap windows; no synthetic, interpolated, resampled, or forward-filled bars were added.
- `repaired_scanner_not_running_pid_history`: Replay identity includes the repaired completed-window scanner, exact-correlation/journal, and protective-stop risk sources; it is not an exact historical replay of the already-running pre-repair PID image.
- `fng_missing_fail_open_proxy`: Point-in-time Fear & Greed is absent, so F&G-dependent gates allow rather than reject; the direction of this bias is unknown.
- `deployed_vsa_stop_fallback`: VSA preserves the deployed confirmation-close plus/minus 2 ATR fallback instead of claiming a repaired structural stop.
- `inert_yaml_exit_authority_drift`: The YAML exit_engine block is inert for the deployed wrapper; the replay follows the wrapper's authoritative 30/30/40 partial-exit path.
- `next_open_execution_proxy`: Next-bar open plus fixed costs is a research proxy, not an exchange fill claim.
- `l1_queue_latency_unavailable`: Historical L1, order queue, post-only fallback, and submission latency are absent.
- `rounding_and_margin_tiers_unavailable`: Historical tick/lot rounding, minimum-notional changes, and margin tiers are absent.
- `available_balance_proxy`: Historical exchange availableBalance is absent; wallet and margin availability are modelled by the preregistered portfolio proxy.
- `trail_and_time_stop_proxy`: Trailing-stop and runner time-stop decisions use completed bars, not the live intrabar mark sampling path.

## Kanıt

- Raw payload SHA-256: `82d93b0a9e647e93922ffcb6628e74024fff6992f12bb588f74708afad555a56`
- Market snapshot SHA-256: `50e5b240e6babeb3b7ceadc0ae007ededc0ae589cba931e3603d233cec693eb8`
- Funding snapshot SHA-256: `35be9ebae8f9468a6bae819054008cb4c2338ae0eb923910584dea1adc0c6b96`
- B/C2/H finansal kimlikleri ve terminal tahakkukları yeniden hesaplanıp geçti.
- Aylık baseline her ay başlangıcından kesin olarak önceki son 15m NAV'dır; ay/fold sermaye reseti yoktur.
