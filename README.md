# Loan Covenant & 10-K Tracker

I built this project to practice connecting Python, SQL, and Java around a corporate finance workflow: tracking commercial loan covenants (Net Debt / EBITDA and Interest Coverage) and checking 10-K text disclosures for new risk language.

Instead of keeping everything in one script, I split the workload across languages based on what each one is used for—Python for data loading and text diffing, SQLite for relational tables and window functions, and Java (`BigDecimal`) for strict compliance math and downside stress testing.

## How It Works

1. **Data Setup & 10-K Text Diffing (`edgar_ingestor_and_redline.py`)**
   Loads a sample portfolio of three middle-market borrowers (across Industrials, Supply Chain/Retail, and Midstream Energy), their loan covenant limits, and quarterly financials (`2026-Q2` and `2026-Q3`) into a local SQLite database (`credit_warehouse.db`). It also compares prior vs. current 10-K risk factor clauses using Python's `difflib` and counts negative financial keywords (based on the Loughran-McDonald dictionary) to spot legal or liquidity warnings.

2. **SQL Schema & Window Views (`schema.sql`)**
   Stores relational tables for `borrowers`, `credit_agreements`, `financial_statements`, and `filing_redlines`. Includes an analytical view (`v_credit_covenant_monitor`) that uses `LAG() OVER` window functions to calculate quarter-over-quarter leverage drift automatically.

3. **Java Compliance & Stress Testing (`CovenantStressEngine.java`)**
   Connects to SQLite via JDBC, checks each borrower against its credit agreement limits using `BigDecimal` (with `HALF_EVEN` rounding to avoid floating-point issues), calculates EBITDA headroom, and runs a downside stress test (-15% EBITDA drop and +150 bps interest rate hike).

4. **Excel, Power BI & HTML Reporting (`export_data.py` & `generate_dashboard.py`)**
   * `export_data.py` exports the SQL view to `credit_surveillance_output.csv` so the table can be opened directly in Microsoft Excel or imported into Power BI.
   * `generate_dashboard.py` generates a clean HTML report (`credit_report.html`) showing covenant status, how much debt paydown (equity cure) is needed to fix a breach, and a 2D sensitivity table across different rate and EBITDA shocks.

## Project Structure

```text
loan-covenant-tracker/
├── schema.sql                        # SQLite tables and window function view
├── edgar_ingestor_and_redline.py     # Populates DB and runs 10-K text diffing
├── CovenantStressEngine.java         # Java JDBC compliance check & stress test
├── export_data.py                    # Exports SQL view to CSV for Excel/Power BI
├── generate_dashboard.py             # Generates static HTML report (credit_report.html)
├── credit_report.html                # Pre-generated HTML summary & sensitivity tables
├── lib/
│   └── sqlite-jdbc-3.46.1.0.jar      # SQLite JDBC driver
└── sample_data/
    └── credit_surveillance_output.csv