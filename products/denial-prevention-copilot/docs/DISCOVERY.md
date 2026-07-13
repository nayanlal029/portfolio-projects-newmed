# Discovery: the SQL trail that led to the Denial Prevention Co-Pilot

*This document is the reasoning, not just the result.* Before proposing
any product, I profiled six months of claims for Lakeview Specialty
Partners (synthetic 8-practice group, 6,000 claims, Jan-Jun 2026) in the
NewMed claims warehouse. Each section below is one product question, the
SQL that answers it, the actual result, and what it implied for the
build/no-build decision.

> Data is synthetic (see `data/generate_claims.py`). Codes (CPT, ICD-10,
> CARC) are real industry vocabulary; payer names other than
> Medicare/Medicaid are fictional.

## Q1. How big is the problem?

**Product question:** Is denial volume material enough to justify a product?

```sql
SELECT
    COUNT(*)                                            AS total_claims,
    -- boolean expressions sum as 1/0 in SQLite, so SUM(status='denied')
    -- is a conditional count of denied claims
    SUM(status = 'denied')                              AS denied_claims,
    -- multiply by 100.0 (not 100) to force float division, then round
    ROUND(100.0 * SUM(status = 'denied') / COUNT(*), 1) AS denial_rate_pct,
    -- CASE WHEN gives a conditional sum: charge dollars on denied claims only
    ROUND(SUM(CASE WHEN status = 'denied' THEN charge_amount ELSE 0 END))
                                                        AS denied_charges_usd,
    -- rework_cost is zero on paid claims, so a plain SUM is safe here
    ROUND(SUM(rework_cost))                             AS rework_cost_usd,
    -- NULLIF guards the division: if there were zero denials the rate
    -- returns NULL instead of crashing (NULL-safe division)
    ROUND(100.0 * SUM(final_outcome = 'written_off')
              / NULLIF(SUM(status = 'denied'), 0), 1)   AS pct_denials_written_off
FROM claims;
```

| total_claims | denied_claims | denial_rate_pct | denied_charges_usd | rework_cost_usd | pct_denials_written_off |
|---|---|---|---|---|---|
| 6000 | 923 | 15.4 | 829757.0 | 72869.0 | 45.5 |

## Q2. Where do denials concentrate?

**Product question:** Is this a uniform problem or a payer-specific one?

```sql
SELECT
    c.payer,
    p.timely_filing_days,                    -- payer rule, for context
    COUNT(*)                                 AS claims,
    SUM(c.status = 'denied')                 AS denied,
    ROUND(100.0 * SUM(c.status = 'denied') / COUNT(*), 1) AS denial_rate_pct,
    ROUND(SUM(CASE WHEN c.status = 'denied' THEN c.charge_amount ELSE 0 END))
                                             AS denied_charges_usd
FROM claims c
JOIN payers p ON p.payer = c.payer
GROUP BY c.payer
ORDER BY denial_rate_pct DESC;               -- worst payer first
```

| payer | timely_filing_days | claims | denied | denial_rate_pct | denied_charges_usd |
|---|---|---|---|---|---|
| Medicaid | 95 | 903 | 292 | 32.3 | 252874.0 |
| UnityHealth | 90 | 1092 | 177 | 16.2 | 174105.0 |
| BlueShield Plus | 180 | 1493 | 196 | 13.1 | 168381.0 |
| SunCoast Health | 120 | 721 | 85 | 11.8 | 70943.0 |
| Medicare | 365 | 1791 | 173 | 9.7 | 163455.0 |

## Q3. Why are claims denied?

**Product question:** What share of denial reasons are knowable BEFORE submission?

```sql
SELECT
    c.denial_code                            AS carc,
    d.category,
    d.description,
    d.preventable_presubmission              AS preventable,
    COUNT(*)                                 AS denials,
    -- scalar subquery gives the denominator (all denials) so each row
    -- reads as "share of total denials", not share of its own group
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM claims WHERE status = 'denied'), 1)
                                             AS pct_of_denials,
    ROUND(SUM(c.charge_amount))              AS charges_usd,
    ROUND(AVG(c.rework_cost), 2)             AS avg_rework_cost_usd
FROM claims c
JOIN denial_codes d ON d.carc = c.denial_code
WHERE c.status = 'denied'                    -- reason mix only exists on denials
GROUP BY c.denial_code
ORDER BY denials DESC;
```

| carc | category | description | preventable | denials | pct_of_denials | charges_usd | avg_rework_cost_usd |
|---|---|---|---|---|---|---|---|
| CO-27 | Eligibility | Expenses incurred after coverage terminated | 1 | 372 | 40.3 | 287044.0 | 78.13 |
| CO-197 | Prior authorization | Precertification/authorization absent | 1 | 177 | 19.2 | 233637.0 | 84.5 |
| CO-11 | Coding / diagnosis | Diagnosis inconsistent with procedure | 0 | 88 | 9.5 | 70369.0 | 76.53 |
| CO-16 | Missing information | Claim lacks information needed for adjudication | 1 | 83 | 9.0 | 62421.0 | 77.36 |
| CO-50 | Medical necessity | Non-covered: not deemed medically necessary | 0 | 66 | 7.2 | 52842.0 | 75.22 |
| CO-4 | Coding / modifier | Procedure code inconsistent with modifier | 1 | 64 | 6.9 | 75748.0 | 79.81 |
| CO-29 | Timely filing | Time limit for filing has expired | 1 | 43 | 4.7 | 26121.0 | 76.67 |
| CO-18 | Duplicate | Exact duplicate claim/service | 0 | 30 | 3.3 | 21576.0 | 77.47 |

## Q4. The headline aggregate: the preventable share

**Product question:** The single number that justifies the build.

```sql
SELECT
    -- preventable_presubmission is 1/0, so AVG-style math works via SUM/COUNT
    ROUND(100.0 * SUM(d.preventable_presubmission) / COUNT(*), 1)
                                             AS preventable_pct_of_denials,
    ROUND(SUM(CASE WHEN d.preventable_presubmission = 1 THEN c.charge_amount END))
                                             AS preventable_charges_usd,
    ROUND(SUM(CASE WHEN d.preventable_presubmission = 1 THEN c.rework_cost END))
                                             AS preventable_rework_usd
FROM claims c
JOIN denial_codes d ON d.carc = c.denial_code
WHERE c.status = 'denied';
```

| preventable_pct_of_denials | preventable_charges_usd | preventable_rework_usd |
|---|---|---|
| 80.1 | 684971.0 | 58846.0 |

## Q5. Monthly trend

**Product question:** Is this getting better on its own? (If yes, no product needed.)

```sql
SELECT
    strftime('%Y-%m', service_date)          AS month,
    COUNT(*)                                 AS claims,
    ROUND(100.0 * SUM(status = 'denied') / COUNT(*), 1) AS denial_rate_pct,
    ROUND(SUM(CASE WHEN status = 'denied' THEN charge_amount ELSE 0 END))
                                             AS denied_charges_usd
FROM claims
GROUP BY month
ORDER BY month;
```

| month | claims | denial_rate_pct | denied_charges_usd |
|---|---|---|---|
| 2026-01 | 1049 | 12.6 | 116102.0 |
| 2026-02 | 944 | 16.1 | 137239.0 |
| 2026-03 | 1005 | 15.6 | 141575.0 |
| 2026-04 | 994 | 15.8 | 132428.0 |
| 2026-05 | 1036 | 16.7 | 169184.0 |
| 2026-06 | 972 | 15.6 | 133231.0 |

## Q6. Cash-flow impact

**Product question:** Denials do not just cost rework labour; they stall cash.

```sql
SELECT
    final_outcome,
    COUNT(*)                                 AS claims,
    ROUND(AVG(days_to_payment), 1)           AS avg_days_to_payment
FROM claims
WHERE days_to_payment IS NOT NULL            -- written-off claims never pay;
                                             -- excluding them avoids a NULL avg
GROUP BY final_outcome
ORDER BY avg_days_to_payment;
```

| final_outcome | claims | avg_days_to_payment |
|---|---|---|
| paid_first_pass | 5077 | 29.3 |
| recovered_after_rework | 503 | 96.3 |

## Q7. Top denial reason per payer (window function)

**Product question:** Payer-specific patterns are the moat argument.

```sql
WITH payer_reason AS (
    -- first aggregate denials to (payer, category) grain...
    SELECT
        c.payer,
        d.category,
        COUNT(*) AS denials,
        -- ...then rank categories within each payer partition;
        -- RANK() restarts at 1 for every payer
        RANK() OVER (PARTITION BY c.payer ORDER BY COUNT(*) DESC) AS rnk
    FROM claims c
    JOIN denial_codes d ON d.carc = c.denial_code
    WHERE c.status = 'denied'
    GROUP BY c.payer, d.category
)
SELECT payer, category AS top_denial_category, denials
FROM payer_reason
WHERE rnk = 1                                -- keep only each payer's #1 reason
ORDER BY denials DESC;
```

| payer | top_denial_category | denials |
|---|---|---|
| Medicaid | Eligibility | 177 |
| BlueShield Plus | Eligibility | 82 |
| Medicare | Eligibility | 53 |
| UnityHealth | Prior authorization | 52 |
| SunCoast Health | Eligibility | 23 |

## Q8. Fact-pattern audit

**Product question:** Is the risk signal visible at submission time? (Feasibility check.)

```sql
SELECT 'Prior auth required but missing' AS gap,
       COUNT(*) AS claims,
       ROUND(100.0 * SUM(status='denied') / COUNT(*), 1) AS denial_rate_pct
FROM claims WHERE prior_auth_required = 1 AND prior_auth_obtained = 0
UNION ALL
SELECT 'Eligibility unverified or stale >60d',
       COUNT(*),
       ROUND(100.0 * SUM(status='denied') / COUNT(*), 1)
FROM claims WHERE eligibility_verified = 0 OR elig_stale_days > 60
UNION ALL
SELECT 'Required modifier missing',
       COUNT(*),
       ROUND(100.0 * SUM(status='denied') / COUNT(*), 1)
FROM claims WHERE modifier_required = 1 AND modifier_present = 0
UNION ALL
SELECT 'Submitted past timely-filing limit',
       COUNT(*),
       ROUND(100.0 * SUM(c.status='denied') / COUNT(*), 1)
FROM claims c JOIN payers p ON p.payer = c.payer
WHERE c.days_to_submit > p.timely_filing_days
UNION ALL
SELECT 'No gap present (clean fact pattern)',
       COUNT(*),
       ROUND(100.0 * SUM(status='denied') / COUNT(*), 1)
FROM claims
WHERE NOT (prior_auth_required = 1 AND prior_auth_obtained = 0)
  AND eligibility_verified = 1 AND elig_stale_days <= 60
  AND NOT (modifier_required = 1 AND modifier_present = 0)
  AND has_missing_fields = 0;
```

| gap | claims | denial_rate_pct |
|---|---|---|
| Prior auth required but missing | 291 | 68.0 |
| Eligibility unverified or stale >60d | 936 | 46.5 |
| Required modifier missing | 159 | 49.1 |
| Submitted past timely-filing limit | 56 | 92.9 |
| No gap present (clean fact pattern) | 4456 | 4.8 |

## The decision

- **15.4% denial rate** against an industry norm of 10-15%: ~$829,757 of charges denied in six months, ~$72,869 spent on rework, and 45.5% of denials never recovered at all.
- **80.1% of denials are preventable at submission time** (eligibility, prior auth, modifiers, missing info, timely filing), worth ~$684,971 in charges.
- Denials concentrate by payer AND the dominant reason differs per payer (Q2, Q7). Generic claim-scrubber rules underfit; a model that learns payer-specific patterns has a structural edge.
- The signal is visible **before** submission (Q8): claims with a known gap deny at 5-10x the clean-claim rate. A pre-submission risk score is feasible with data the platform already holds.

**Decision: build a pre-submission Denial Prevention Co-Pilot.** Score every claim at claim-scrubbing time, flag high-risk claims with the predicted denial reason and a one-click fix, keep the biller in the loop, and feed every override back into the model.
