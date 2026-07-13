-- ============================================================================
-- NewMed Denial Prevention Co-Pilot :: Discovery queries
-- ============================================================================
-- These are the queries I ran against the claims warehouse (data/newmed.db)
-- to decide whether a denial-prevention product was worth building at all.
-- Each query answers one product question. The runner (run_discovery.py)
-- executes them and writes results into docs/DISCOVERY.md and the app.
--
-- Dialect: SQLite. Tables: claims (one row per claim with pre-submission
-- facts and the adjudication outcome), payers (rules per payer),
-- denial_codes (CARC code reference with a preventability flag).
-- ============================================================================

-- Q1 :: How big is the problem? (headline KPIs)
-- Product question: is denial volume material enough to justify a product?
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

-- Q2 :: Where do denials concentrate? (by payer)
-- Product question: is this a uniform problem or a payer-specific one?
-- If payer-specific, a model that learns payer-level rules has an edge.
SELECT
    c.payer,
    p.timely_filing_days,                    -- payer rule, for context
    COUNT(*)                                 AS claims,
    SUM(c.status = 'denied')                 AS denied,
    ROUND(100.0 * SUM(c.status = 'denied') / COUNT(*), 1) AS denial_rate_pct,
    ROUND(SUM(CASE WHEN c.status = 'denied' THEN c.charge_amount ELSE 0 END))
                                             AS denied_charges_usd
FROM claims c
-- join brings in each payer's filing rule; payer is the natural key
JOIN payers p ON p.payer = c.payer
GROUP BY c.payer
ORDER BY denial_rate_pct DESC;               -- worst payer first

-- Q3 :: WHY are claims denied? (CARC reason mix + preventability)
-- Product question: what share of denials could a PRE-submission check catch?
-- This is the query that decided the product. Reasons flagged
-- preventable_presubmission are knowable from the claim record BEFORE the
-- claim is sent (eligibility, prior auth, modifier, missing info, timely
-- filing). Reasons like medical necessity are only knowable post-adjudication.
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

-- Q4 :: The headline aggregate: the preventable share
-- Product question: the single number that justifies the build.
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

-- Q5 :: Monthly trend: is this getting better on its own?
-- Product question: if the trend were improving, a memo beats a product.
-- Bucketing by SERVICE date, not submission date, so backlog claims do not
-- smear into later months (a classic date-bucketing trap in claims data).
SELECT
    strftime('%Y-%m', service_date)          AS month,
    COUNT(*)                                 AS claims,
    ROUND(100.0 * SUM(status = 'denied') / COUNT(*), 1) AS denial_rate_pct,
    ROUND(SUM(CASE WHEN status = 'denied' THEN charge_amount ELSE 0 END))
                                             AS denied_charges_usd
FROM claims
GROUP BY month
ORDER BY month;

-- Q6 :: Cash-flow impact: days to payment, clean vs denied-then-recovered
-- Product question: denials do not just cost rework labour, they stall cash.
SELECT
    final_outcome,
    COUNT(*)                                 AS claims,
    ROUND(AVG(days_to_payment), 1)           AS avg_days_to_payment
FROM claims
WHERE days_to_payment IS NOT NULL            -- written-off claims never pay;
                                             -- excluding them avoids a NULL avg
GROUP BY final_outcome
ORDER BY avg_days_to_payment;

-- Q7 :: Top denial reason PER payer (window function)
-- Product question: payer-specific patterns are the moat. Each payer denies
-- for different dominant reasons, so a per-payer model beats generic rules.
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

-- Q8 :: Fact-pattern audit: is the risk signal visible BEFORE submission?
-- Product question: feasibility. If claims with a known gap deny at many
-- times the clean-claim rate, a pre-submission risk score can work.
-- Each SELECT isolates one gap pattern; UNION ALL stacks them into one table.
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
-- the control group: claims with NO known gap at submission time.
-- Their denial rate is the noise floor the model cannot beat.
SELECT 'No gap present (clean fact pattern)',
       COUNT(*),
       ROUND(100.0 * SUM(status='denied') / COUNT(*), 1)
FROM claims
WHERE NOT (prior_auth_required = 1 AND prior_auth_obtained = 0)
  AND eligibility_verified = 1 AND elig_stale_days <= 60
  AND NOT (modifier_required = 1 AND modifier_present = 0)
  AND has_missing_fields = 0;
