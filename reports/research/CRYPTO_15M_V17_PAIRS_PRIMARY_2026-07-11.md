# Crypto 15m v17 pairs — primary sonuç raporu

## Karar

**RED_NO_HOLDOUT**

Hiçbir hücre ön-LOSO primary mutlak kapılarını geçmedi; gerçek LOSO ve holdout çalıştırılmadı.

Tam hard-gate sonucu hiçbir hücre için başarılı sayılmadı: primary raw kanıtta bulunmayan LOSO/holdout metrikleri fail-closed başarısızdır.

## Hücre özeti

| Sıra | Hücre | Ön-LOSO | H trim/ay | H medyan | H negatif | H kötü ay | H DD | C2 trim/ay | B edge/cost | H kapalı+terminal | Aktif ay | Turnover |
|---:|---|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | DP1_EG_90D_Z2P5 | FAIL | 0.00% | 0.00% | 0 | 0.00% | 0.00% | 0.00% | N/A | 0+0 | 0 | 0.00x |
| 2 | DP2_EG_180D_Z2P5 | FAIL | 0.00% | 0.00% | 0 | 0.00% | 0.00% | 0.00% | N/A | 0+0 | 0 | 0.00x |
| 3 | DP3_EG_180D_Z3_STRICT | FAIL | 0.00% | 0.00% | 0 | 0.00% | 0.00% | 0.00% | N/A | 0+0 | 0 | 0.00x |

## Başarısız kapılar

- `DP1_EG_90D_Z2P5`: `sample.minimum_closed_pair_episodes`, `sample.minimum_high_spread_entries`, `sample.minimum_low_spread_entries`, `sample.minimum_active_months`, `H_return.trimmed_mean_monthly_pct_min`, `H_return.median_monthly_pct_min`, `H_return.block_bootstrap_90pct_lower_bound_pct_min`, `C2_return.trimmed_mean_monthly_pct_min`, `C2_return.median_monthly_pct_min`, `C2_return.total_return_must_be_positive`, `walk_forward.positive_folds_min`, `walk_forward.oos_to_is_trimmed_return_ratio_min`, `walk_forward.oos_to_is_drawdown_ratio_max`, `economic_edge.B_closed_pair_price_pnl_before_execution_and_funding_must_be_positive`, `economic_edge.B_pre_cost_price_pnl_over_execution_cost_min`, `economic_edge.median_entry_expected_edge_over_stressed_cost_min`, `concentration.best_month_positive_pnl_share_max`, `concentration.best_3_month_positive_pnl_share_max`, `concentration.top_5pct_pair_episodes_positive_pnl_share_max`, `concentration.net_after_top_5pct_pair_episodes_removed_must_be_positive`, `direction.high_spread_C2_net_must_be_positive`, `direction.low_spread_C2_net_must_be_positive`, `multiple_testing.holm_fwer_adjusted_p_max`, `multiple_testing.deflated_sharpe_min`, `multiple_testing.probability_backtest_overfit_max`, `multiple_testing.cumulative_program_holm_adjusted_p_max`, `multiple_testing.cumulative_program_deflated_sharpe_min`
- `DP2_EG_180D_Z2P5`: `sample.minimum_closed_pair_episodes`, `sample.minimum_high_spread_entries`, `sample.minimum_low_spread_entries`, `sample.minimum_active_months`, `H_return.trimmed_mean_monthly_pct_min`, `H_return.median_monthly_pct_min`, `H_return.block_bootstrap_90pct_lower_bound_pct_min`, `C2_return.trimmed_mean_monthly_pct_min`, `C2_return.median_monthly_pct_min`, `C2_return.total_return_must_be_positive`, `walk_forward.positive_folds_min`, `walk_forward.oos_to_is_trimmed_return_ratio_min`, `walk_forward.oos_to_is_drawdown_ratio_max`, `economic_edge.B_closed_pair_price_pnl_before_execution_and_funding_must_be_positive`, `economic_edge.B_pre_cost_price_pnl_over_execution_cost_min`, `economic_edge.median_entry_expected_edge_over_stressed_cost_min`, `concentration.best_month_positive_pnl_share_max`, `concentration.best_3_month_positive_pnl_share_max`, `concentration.top_5pct_pair_episodes_positive_pnl_share_max`, `concentration.net_after_top_5pct_pair_episodes_removed_must_be_positive`, `direction.high_spread_C2_net_must_be_positive`, `direction.low_spread_C2_net_must_be_positive`, `multiple_testing.holm_fwer_adjusted_p_max`, `multiple_testing.deflated_sharpe_min`, `multiple_testing.probability_backtest_overfit_max`, `multiple_testing.cumulative_program_holm_adjusted_p_max`, `multiple_testing.cumulative_program_deflated_sharpe_min`
- `DP3_EG_180D_Z3_STRICT`: `sample.minimum_closed_pair_episodes`, `sample.minimum_high_spread_entries`, `sample.minimum_low_spread_entries`, `sample.minimum_active_months`, `H_return.trimmed_mean_monthly_pct_min`, `H_return.median_monthly_pct_min`, `H_return.block_bootstrap_90pct_lower_bound_pct_min`, `C2_return.trimmed_mean_monthly_pct_min`, `C2_return.median_monthly_pct_min`, `C2_return.total_return_must_be_positive`, `walk_forward.positive_folds_min`, `walk_forward.oos_to_is_trimmed_return_ratio_min`, `walk_forward.oos_to_is_drawdown_ratio_max`, `economic_edge.B_closed_pair_price_pnl_before_execution_and_funding_must_be_positive`, `economic_edge.B_pre_cost_price_pnl_over_execution_cost_min`, `economic_edge.median_entry_expected_edge_over_stressed_cost_min`, `concentration.best_month_positive_pnl_share_max`, `concentration.best_3_month_positive_pnl_share_max`, `concentration.top_5pct_pair_episodes_positive_pnl_share_max`, `concentration.net_after_top_5pct_pair_episodes_removed_must_be_positive`, `direction.high_spread_C2_net_must_be_positive`, `direction.low_spread_C2_net_must_be_positive`, `multiple_testing.holm_fwer_adjusted_p_max`, `multiple_testing.deflated_sharpe_min`, `multiple_testing.probability_backtest_overfit_max`, `multiple_testing.cumulative_program_holm_adjusted_p_max`, `multiple_testing.cumulative_program_deflated_sharpe_min`

## Kanıt ve sınırlar

- V17 raw JSON SHA-256: `73e92a02131985a8a24c195c54c165b6775decef0ea41e24b6b34991edf4d82a`
- V16 raw JSON SHA-256: `9ebbe8620a7fb5b46eb958ce593e7e772a50f2380f54fc7b857f9cd488063d8e`
- Prereg SHA-256: `52d6b0e433e4145e17c588be88d3f82bc7ecb91e281fab12fd5450db12b6cc52`
- Market snapshot SHA-256: `071768300daea9170d29bd5e35cc94795b8a500614d6e5ac4b127e459416652d`
- Funding snapshot SHA-256: `35be9ebae8f9468a6bae819054008cb4c2338ae0eb923910584dea1adc0c6b96`
- Pseudo-OOS tam olarak Haziran 2023–Mayıs 2026, 36 aydır.
- Turnover paydası H penceresindeki her 15m NAV gözleminin aritmetik ortalamasıdır.
- Rapor snapshot açmadı, backtest veya holdout/LOSO çalıştırmadı ve deployment yetkisi vermedi.
