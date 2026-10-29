import sqlite3
import os

DB_PATH = "credit_warehouse.db"
OUTPUT_FILE = "credit_report.html"

# Negative financial terms to bold in the 10-K text notes
RISK_TERMS = [
    "subpoena", "litigation", "noncompliance", "default",
    "waiver", "forbearance", "adverse", "inflation"
]

def mark_keywords(text):
    if not text:
        return "No major changes noted."
    for word in RISK_TERMS:
        text = text.replace(word, f"<mark>{word}</mark>")
        text = text.replace(word.capitalize(), f"<mark>{word.capitalize()}</mark>")
    return text

def load_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM v_credit_covenant_monitor ORDER BY ticker, fiscal_period")
    rows = [dict(r) for r in cur.fetchall()]

    # Group by ticker so we only display the most recent quarter (2026-Q3) in the summary
    grouped = {}
    for r in rows:
        t = r["ticker"]
        grouped.setdefault(t, []).append(r)

    # Grab 10-K redline notes if present
    redlines = {}
    try:
        cur.execute("""
            SELECT b.company_name, r.*
            FROM filing_redlines r
            JOIN borrowers b ON r.borrower_id = b.id
        """)
        for r in cur.fetchall():
            d = dict(r)
            redlines[d["company_name"]] = d
    except Exception:
        pass

    conn.close()

    results = []
    for ticker, periods in grouped.items():
        curr = periods[-1]
        prev = periods[-2] if len(periods) > 1 else None

        ebitda = float(curr["ebitda_m"])
        net_debt = float(curr["net_debt_m"])
        interest = float(curr["interest_expense_m"])
        total_debt = float(curr["total_debt_m"])

        max_lev = float(curr.get("max_net_leverage_ratio", 3.50))
        min_cov = float(curr.get("min_interest_coverage_ratio", 2.50))

        net_lev = net_debt / ebitda
        prev_lev = (float(prev["net_debt_m"]) / float(prev["ebitda_m"])) if prev else net_lev
        qoq_change = net_lev - prev_lev
        int_cov = ebitda / interest

        # Positive = unused debt room, Negative = debt paydown (equity cure) required
        max_allowed_debt = ebitda * max_lev
        debt_headroom = max_allowed_debt - net_debt

        breach = (net_lev > max_lev) or (int_cov < min_cov)

        comp_name = curr["company_name"]
        rl = redlines.get(comp_name, {})
        sim_score = rl.get("similarity_score") or rl.get("similarity_ratio") or 0.0
        risk_count = rl.get("risk_word_delta") or rl.get("loughran_mcdonald_delta") or 0
        clause = (
            rl.get("redline_diff_summary")
            or rl.get("redline_summary")
            or rl.get("extracted_clause")
            or "No major changes noted."
        )

        results.append({
            "ticker": ticker,
            "name": comp_name,
            "sector": curr["sector"],
            "period": curr["fiscal_period"],
            "ebitda": ebitda,
            "net_debt": net_debt,
            "total_debt": total_debt,
            "interest": interest,
            "net_lev": net_lev,
            "qoq_change": qoq_change,
            "int_cov": int_cov,
            "max_lev": max_lev,
            "min_cov": min_cov,
            "debt_headroom": debt_headroom,
            "breach": breach,
            "sim_score": float(sim_score),
            "risk_count": int(risk_count),
            "clause": clause
        })

    return results

def make_stress_grid(c):
    ebitda_drops = [0.0, -0.10, -0.15, -0.20]
    rate_hikes_bps = [0, 100, 150, 200]

    rows_html = ""
    for drop in ebitda_drops:
        s_ebitda = c["ebitda"] * (1.0 + drop)
        row_cells = f"<td><b>{int(drop * 100)}% EBITDA</b></td>"

        for bps in rate_hikes_bps:
            extra_int = c["total_debt"] * (bps / 10000.0)
            s_int = c["interest"] + extra_int
            s_lev = c["net_debt"] / s_ebitda
            s_cov = s_ebitda / s_int

            failed = (s_lev > c["max_lev"]) or (s_cov < c["min_cov"])
            cls = "fail-cell" if failed else "pass-cell"
            row_cells += f"<td class='{cls}'>{s_lev:.2f}x lev<br><small>{s_cov:.2f}x cov</small></td>"

        rows_html += f"<tr>{row_cells}</tr>"

    return f"""
    <table class="grid-table">
        <tr>
            <th>Shock Scenario</th>
            <th>+0 bps</th>
            <th>+100 bps</th>
            <th>+150 bps</th>
            <th>+200 bps</th>
        </tr>
        {rows_html}
    </table>
    """

def build_report(data):
    total_debt = sum(d["total_debt"] for d in data)
    breaches = sum(1 for d in data if d["breach"])
    total_cure = sum(abs(d["debt_headroom"]) for d in data if d["debt_headroom"] < 0)

    table_rows = ""
    company_sections = ""

    for d in data:
        status_text = "<span class='status-breach'>BREACH</span>" if d["breach"] else "<span class='status-ok'>OK</span>"
        sign = "+" if d["qoq_change"] > 0 else ""

        if d["debt_headroom"] < 0:
            headroom_str = f"<span class='text-red'>-${abs(d['debt_headroom']):.2f}M cure needed</span>"
        else:
            headroom_str = f"+${d['debt_headroom']:.2f}M capacity"

        table_rows += f"""
        <tr>
            <td><b>{d['name']}</b> ({d['ticker']})</td>
            <td>{d['sector']}</td>
            <td>${d['ebitda']:.1f}M</td>
            <td>${d['net_debt']:.1f}M</td>
            <td><b>{d['net_lev']:.2f}x</b> (<= {d['max_lev']:.2f}x)</td>
            <td>{sign}{d['qoq_change']:.2f}x</td>
            <td><b>{d['int_cov']:.2f}x</b> (>= {d['min_cov']:.2f}x)</td>
            <td>{headroom_str}</td>
            <td>{status_text}</td>
        </tr>
        """

        company_sections += f"""
        <div class="box">
            <h3>{d['name']} ({d['ticker']}) - {d['period']}</h3>
            <div class="two-col">
                <div>
                    <p><b>Downside Sensitivity Table (Leverage & Coverage):</b></p>
                    {make_stress_grid(d)}
                </div>
                <div>
                    <p><b>10-K Risk Factor Diff Notes:</b></p>
                    <p class="meta">Similarity vs Prior Filing: {d['sim_score']:.3f} | New Risk Words: +{d['risk_count']}</p>
                    <div class="quote-box">
                        "{mark_keywords(d['clause'])}"
                    </div>
                </div>
            </div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Credit Covenant Report - Q3 2026</title>
<style>
    body {{
        font-family: Arial, Helvetica, sans-serif;
        background-color: #f4f5f7;
        color: #1c1e21;
        margin: 24px;
    }}
    h1 {{ font-size: 22px; margin-bottom: 4px; }}
    .subtitle {{ color: #555; font-size: 13px; margin-top: 0; margin-bottom: 20px; }}
    .summary-bar {{
        display: flex;
        gap: 16px;
        margin-bottom: 20px;
    }}
    .stat-box {{
        background: #fff;
        border: 1px solid #d1d5db;
        padding: 12px 18px;
        border-radius: 4px;
        min-width: 180px;
    }}
    .stat-label {{ font-size: 12px; color: #666; }}
    .stat-val {{ font-size: 20px; font-weight: bold; margin-top: 4px; }}
    table.data-table {{
        width: 100%;
        border-collapse: collapse;
        background: #fff;
        border: 1px solid #d1d5db;
        margin-bottom: 24px;
        font-size: 13px;
    }}
    .data-table th {{
        background: #e5e7eb;
        text-align: left;
        padding: 9px 10px;
        border-bottom: 1px solid #d1d5db;
    }}
    .data-table td {{
        padding: 9px 10px;
        border-bottom: 1px solid #e5e7eb;
    }}
    .status-breach {{ color: #b91c1c; font-weight: bold; }}
    .status-ok {{ color: #15803d; font-weight: bold; }}
    .text-red {{ color: #b91c1c; font-weight: bold; }}
    .box {{
        background: #fff;
        border: 1px solid #d1d5db;
        padding: 16px;
        margin-bottom: 16px;
        border-radius: 4px;
    }}
    .box h3 {{ margin-top: 0; margin-bottom: 10px; font-size: 16px; border-bottom: 1px solid #eee; padding-bottom: 6px; }}
    .two-col {{
        display: grid;
        grid-template-columns: 1.2fr 1fr;
        gap: 20px;
    }}
    .grid-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 12px;
        text-align: center;
    }}
    .grid-table th, .grid-table td {{
        border: 1px solid #d1d5db;
        padding: 6px;
    }}
    .grid-table th {{ background: #f3f4f6; }}
    .fail-cell {{ background: #fee2e2; color: #991b1b; }}
    .pass-cell {{ background: #dcfce7; color: #166534; }}
    .meta {{ font-size: 12px; color: #555; margin: 4px 0 8px 0; }}
    .quote-box {{
        background: #f9fafb;
        border-left: 3px solid #6b7280;
        padding: 10px;
        font-size: 13px;
        line-height: 1.45;
    }}
    mark {{
        background-color: #fef08a;
        padding: 0 2px;
    }}
</style>
</head>
<body>
    <h1>Corporate Credit & Covenant Summary (2026-Q3)</h1>
    <p class="subtitle">Generated from SQLite view (v_credit_covenant_monitor) and 10-K text diff table</p>

    <div class="summary-bar">
        <div class="stat-box">
            <div class="stat-label">Total Tracked Debt</div>
            <div class="stat-val">${total_debt:,.1f}M</div>
        </div>
        <div class="stat-box">
            <div class="stat-label">Borrowers in Breach</div>
            <div class="stat-val" style="color:#b91c1c;">{breaches} / {len(data)}</div>
        </div>
        <div class="stat-box">
            <div class="stat-label">Total Debt Paydown Needed</div>
            <div class="stat-val">${total_cure:,.2f}M</div>
        </div>
    </div>

    <table class="data-table">
        <tr>
            <th>Borrower</th>
            <th>Sector</th>
            <th>EBITDA</th>
            <th>Net Debt</th>
            <th>Net Leverage</th>
            <th>QoQ Drift</th>
            <th>Int. Coverage</th>
            <th>Headroom / Cure</th>
            <th>Status</th>
        </tr>
        {table_rows}
    </table>

    {company_sections}
</body>
</html>
"""

if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print("Database file not found. Run edgar_ingestor_and_redline.py first.")
    else:
        rows = load_data()
        html = build_report(rows)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(html)
        print("Done. Saved report to", OUTPUT_FILE)