-- schema.sql
PRAGMA foreign_keys = ON;

DROP VIEW IF EXISTS v_credit_covenant_monitor;
DROP TABLE IF EXISTS filing_redlines;
DROP TABLE IF EXISTS quarterly_financials;
DROP TABLE IF EXISTS credit_agreements;
DROP TABLE IF EXISTS companies;

-- 1. Borrower Master Table
CREATE TABLE companies (
    ticker TEXT PRIMARY KEY,
    cik TEXT NOT NULL,
    company_name TEXT NOT NULL,
    sector TEXT NOT NULL
);

-- 2. Commercial Loan & Debt Covenant Limits
CREATE TABLE credit_agreements (
    ticker TEXT PRIMARY KEY,
    facility_size_millions NUMERIC NOT NULL,
    max_net_leverage_ratio NUMERIC NOT NULL,
    min_interest_coverage_ratio NUMERIC NOT NULL,
    floating_spread_bps INTEGER NOT NULL,
    FOREIGN KEY (ticker) REFERENCES companies(ticker)
);

-- 3. Quarterly Financial Statements (in $ Millions)
CREATE TABLE quarterly_financials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    fiscal_period TEXT NOT NULL,
    revenue_m NUMERIC NOT NULL,
    operating_income_m NUMERIC NOT NULL,
    depreciation_amortization_m NUMERIC NOT NULL,
    interest_expense_m NUMERIC NOT NULL,
    total_debt_m NUMERIC NOT NULL,
    cash_and_equivalents_m NUMERIC NOT NULL,
    UNIQUE(ticker, fiscal_period),
    FOREIGN KEY (ticker) REFERENCES companies(ticker)
);

-- 4. SEC 10-K / 10-Q Semantic Redline Audit Log
CREATE TABLE filing_redlines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    prior_period TEXT NOT NULL,
    current_period TEXT NOT NULL,
    section_name TEXT NOT NULL,
    similarity_ratio NUMERIC NOT NULL,
    risk_word_delta INTEGER NOT NULL,
    added_clauses TEXT NOT NULL,
    FOREIGN KEY (ticker) REFERENCES companies(ticker)
);

-- 5. Analytical View: Computes EBITDA, Net Leverage, Coverage & QoQ Drift
CREATE VIEW v_credit_covenant_monitor AS
WITH base_metrics AS (
    SELECT 
        q.ticker,
        c.company_name,
        c.sector,
        q.fiscal_period,
        q.revenue_m,
        (q.operating_income_m + q.depreciation_amortization_m) AS ebitda_m,
        (q.total_debt_m - q.cash_and_equivalents_m) AS net_debt_m,
        q.interest_expense_m,
        q.total_debt_m,
        ca.facility_size_millions,
        ca.max_net_leverage_ratio,
        ca.min_interest_coverage_ratio
    FROM quarterly_financials q
    JOIN companies c ON q.ticker = c.ticker
    JOIN credit_agreements ca ON q.ticker = ca.ticker
)
SELECT 
    ticker,
    company_name,
    sector,
    fiscal_period,
    ROUND(ebitda_m, 2) AS ebitda_m,
    ROUND(net_debt_m, 2) AS net_debt_m,
    ROUND(interest_expense_m, 2) AS interest_expense_m,
    ROUND(total_debt_m, 2) AS total_debt_m,
    ROUND(net_debt_m / NULLIF(ebitda_m, 0), 2) AS net_leverage_ratio,
    ROUND(
        (net_debt_m / NULLIF(ebitda_m, 0)) - 
        LAG(net_debt_m / NULLIF(ebitda_m, 0)) OVER (PARTITION BY ticker ORDER BY fiscal_period), 
        2
    ) AS qoq_leverage_drift,
    ROUND(ebitda_m / NULLIF(interest_expense_m, 0), 2) AS interest_coverage_ratio,
    max_net_leverage_ratio,
    min_interest_coverage_ratio
FROM base_metrics;