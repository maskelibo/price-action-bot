WITH incident AS (
    SELECT candidate_H_pseudo_oos
    FROM read_json_auto(
        'reports/research/crypto_15m_v18_primary_red_incident_2026-07-11.json'
    )
)
SELECT
    'C1_VSA_ONLY' AS candidate,
    candidate_H_pseudo_oos.C1_VSA_ONLY.closed_trades AS closed_trades,
    candidate_H_pseudo_oos.C1_VSA_ONLY.trimmed_mean_monthly_pct AS trimmed_mean_monthly_pct,
    candidate_H_pseudo_oos.C1_VSA_ONLY.median_monthly_pct AS median_monthly_pct,
    candidate_H_pseudo_oos.C1_VSA_ONLY.bootstrap_90pct_lower_bound_pct AS bootstrap_90pct_lower_bound_pct,
    candidate_H_pseudo_oos.C1_VSA_ONLY.negative_months AS negative_months,
    candidate_H_pseudo_oos.C1_VSA_ONLY.worst_month_pct AS worst_month_pct,
    candidate_H_pseudo_oos.C1_VSA_ONLY.max_mtm_drawdown_pct AS max_mtm_drawdown_pct
FROM incident
UNION ALL
SELECT
    'C2_GRIMES_ONLY',
    candidate_H_pseudo_oos.C2_GRIMES_ONLY.closed_trades,
    candidate_H_pseudo_oos.C2_GRIMES_ONLY.trimmed_mean_monthly_pct,
    candidate_H_pseudo_oos.C2_GRIMES_ONLY.median_monthly_pct,
    candidate_H_pseudo_oos.C2_GRIMES_ONLY.bootstrap_90pct_lower_bound_pct,
    candidate_H_pseudo_oos.C2_GRIMES_ONLY.negative_months,
    candidate_H_pseudo_oos.C2_GRIMES_ONLY.worst_month_pct,
    candidate_H_pseudo_oos.C2_GRIMES_ONLY.max_mtm_drawdown_pct
FROM incident
UNION ALL
SELECT
    'C3_DUAL_HTF50',
    candidate_H_pseudo_oos.C3_DUAL_HTF50.closed_trades,
    candidate_H_pseudo_oos.C3_DUAL_HTF50.trimmed_mean_monthly_pct,
    candidate_H_pseudo_oos.C3_DUAL_HTF50.median_monthly_pct,
    candidate_H_pseudo_oos.C3_DUAL_HTF50.bootstrap_90pct_lower_bound_pct,
    candidate_H_pseudo_oos.C3_DUAL_HTF50.negative_months,
    candidate_H_pseudo_oos.C3_DUAL_HTF50.worst_month_pct,
    candidate_H_pseudo_oos.C3_DUAL_HTF50.max_mtm_drawdown_pct
FROM incident
UNION ALL
SELECT
    'C4_VSA_HTF50',
    candidate_H_pseudo_oos.C4_VSA_HTF50.closed_trades,
    candidate_H_pseudo_oos.C4_VSA_HTF50.trimmed_mean_monthly_pct,
    candidate_H_pseudo_oos.C4_VSA_HTF50.median_monthly_pct,
    candidate_H_pseudo_oos.C4_VSA_HTF50.bootstrap_90pct_lower_bound_pct,
    candidate_H_pseudo_oos.C4_VSA_HTF50.negative_months,
    candidate_H_pseudo_oos.C4_VSA_HTF50.worst_month_pct,
    candidate_H_pseudo_oos.C4_VSA_HTF50.max_mtm_drawdown_pct
FROM incident;
