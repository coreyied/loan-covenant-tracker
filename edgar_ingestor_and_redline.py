# edgar_ingestor_and_redline.py
import sqlite3
import urllib.request
import json
import difflib
import re
from pathlib import Path

DB_PATH = "credit_warehouse.db"
SCHEMA_PATH = "schema.sql"

# Institutional risk words from the Loughran-McDonald Financial Dictionary
LOUGHRAN_MCDONALD_RISK_WORDS = {
    "default", "covenant", "noncompliance", "breach", "litigation", "subpoena",
    "restatement", "impairment", "insolvency", "bankruptcy", "going", "concern",
    "liquidity", "forbearance", "waiver", "delinquent", "adverse", "contingency",
    "penalty", "termination", "underinvestigation", "material", "weakness", "refinance"
}


def init_database(conn: sqlite3.Connection) -> None:
    """Reads schema.sql and builds the tables and views inside credit_warehouse.db."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    print("[SQL] Initialized relational schema and v_credit_covenant_monitor window view.")


def fetch_live_sec_xbrl_sample(cik: str = "0000320193") -> dict:
    """Connects to the live SEC EDGAR API using urllib.request."""
    cik_padded = cik.zfill(10)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "UniversityCreditResearchEngine credit-engine@example.edu",
            "Accept-Encoding": "identity"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
            entity_name = data.get("entityName", "Unknown")
            print(f"[SEC EDGAR API] Verified live connection for {entity_name} (CIK: {cik_padded})")
            return data
    except Exception as e:
        print(f"[SEC EDGAR API] Offline or rate-limited ({e}). Proceeding with local dataset.")
        return {}


def tokenize_words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", text.lower())


def count_loughran_mcdonald_hits(text: str) -> int:
    words = tokenize_words(text)
    return sum(1 for w in words if w in LOUGHRAN_MCDONALD_RISK_WORDS)


def run_10k_semantic_redline(prior_text: str, current_text: str) -> tuple[float, int, str]:
    """Compares consecutive 10-K/10-Q paragraphs to isolate newly added legal risk clauses."""
    prior_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", prior_text.strip()) if s.strip()]
    curr_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", current_text.strip()) if s.strip()]

    overall_similarity = round(difflib.SequenceMatcher(None, prior_text, current_text).ratio(), 3)
    risk_delta = count_loughran_mcdonald_hits(current_text) - count_loughran_mcdonald_hits(prior_text)

    added_or_altered = []
    for curr_s in curr_sentences:
        best_match = max(
            (difflib.SequenceMatcher(None, prior_s, curr_s).ratio() for prior_s in prior_sentences),
            default=0.0
        )
        if best_match < 0.75:
            added_or_altered.append(curr_s)

    redline_summary = " | ".join(added_or_altered) if added_or_altered else "No material clause changes detected."
    return overall_similarity, risk_delta, redline_summary


def seed_and_analyze_borrowers(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()

    companies = [
        ("APEX", "0001045810", "Apex Precision Manufacturing Corp.", "Industrials"),
        ("VanguardMid", "0001122334", "Vanguard Midstream Energy Partners", "Energy & Midstream"),
        ("KestrelRet", "0001556677", "Kestrel Omnichannel Logistics Inc.", "Supply Chain & Retail")
    ]
    cursor.executemany("INSERT INTO companies VALUES (?, ?, ?, ?)", companies)

    covenants = [
        ("APEX", 250.0, 3.50, 3.00, 225),
        ("VanguardMid", 500.0, 4.00, 2.50, 275),
        ("KestrelRet", 175.0, 3.25, 2.75, 300)
    ]
    cursor.executemany("INSERT INTO credit_agreements VALUES (?, ?, ?, ?, ?)", covenants)

    financials = [
        ("APEX", "2026-Q2", 820.0, 145.0, 35.0, 28.0, 450.0, 60.0),
        ("APEX", "2026-Q3", 845.0, 152.0, 36.0, 27.5, 440.0, 65.0),
        ("VanguardMid", "2026-Q2", 1200.0, 210.0, 70.0, 82.0, 1050.0, 90.0),
        ("VanguardMid", "2026-Q3", 1140.0, 178.0, 72.0, 94.0, 1080.0, 65.0),
        ("KestrelRet", "2026-Q2", 610.0, 68.0, 22.0, 26.0, 295.0, 35.0),
        ("KestrelRet", "2026-Q3", 560.0, 44.0, 22.0, 31.0, 325.0, 20.0)
    ]
    cursor.executemany(
        """INSERT INTO quarterly_financials 
           (ticker, fiscal_period, revenue_m, operating_income_m, depreciation_amortization_m, 
            interest_expense_m, total_debt_m, cash_and_equivalents_m) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        financials
    )

    filings = [
        (
            "APEX", "2026-Q2", "2026-Q3", "Item 1A - Risk Factors",
            "Supply chain operations remain stable across North American plants. We maintain sufficient liquidity under our revolving credit facility.",
            "Supply chain operations remain stable across North American plants. We maintain sufficient liquidity under our revolving credit facility."
        ),
        (
            "VanguardMid", "2026-Q2", "2026-Q3", "Item 1A - Risk Factors",
            "Our gathering pipelines are subject to seasonal throughput volume shifts. We expect capital expenditures to be funded from operating cash flows.",
            "Our gathering pipelines are subject to seasonal throughput volume shifts. Higher borrowing costs and delayed customer completions may tighten liquidity and reduce our financial covenant cushion in upcoming quarters."
        ),
        (
            "KestrelRet", "2026-Q2", "2026-Q3", "Item 7 - Liquidity & Debt Footnote",
            "The Company was in compliance with all financial ratios under its Senior Secured Credit Agreement as of quarter end.",
            "Due to adverse freight cost inflation and a formal subpoena regarding vendor billing litigation, the Company anticipates potential noncompliance and technical default under its maximum leverage covenant and has initiated waiver and forbearance discussions with lenders."
        )
    ]

    for ticker, p_per, c_per, sec_name, p_txt, c_txt in filings:
        sim_ratio, risk_delta, added_clauses = run_10k_semantic_redline(p_txt, c_txt)
        cursor.execute(
            """INSERT INTO filing_redlines 
               (ticker, prior_period, current_period, section_name, similarity_ratio, risk_word_delta, added_clauses)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ticker, p_per, c_per, sec_name, sim_ratio, risk_delta, added_clauses)
        )

    conn.commit()
    print("[PYTHON] Populated quarterly financials and completed SEC 10-K/10-Q semantic redline analysis.")


if __name__ == "__main__":
    if not Path(SCHEMA_PATH).exists():
        raise FileNotFoundError(f"Missing {SCHEMA_PATH} in current directory.")

    connection = sqlite3.connect(DB_PATH)
    init_database(connection)
    fetch_live_sec_xbrl_sample("0000320193")
    seed_and_analyze_borrowers(connection)
    connection.close()
    print(f"[READY] Database '{DB_PATH}' is created and ready for Java.")