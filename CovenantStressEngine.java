// CovenantStressEngine.java
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;

public class CovenantStressEngine {

    private static final String JDBC_URL = "jdbc:sqlite:credit_warehouse.db";
    private static final int SCALE = 2;
    private static final RoundingMode BANKERS_ROUNDING = RoundingMode.HALF_EVEN;

    // Holds one borrower's quarterly record loaded from SQLite
    public static class BorrowerSnapshot {
        public final String ticker;
        public final String companyName;
        public final String sector;
        public final String period;
        public final BigDecimal ebitdaM;
        public final BigDecimal netDebtM;
        public final BigDecimal totalDebtM;
        public final BigDecimal interestExpenseM;
        public final BigDecimal qoqLeverageDrift;
        public final BigDecimal maxLeverageLimit;
        public final BigDecimal minCoverageLimit;
        public final BigDecimal filingSimilarity;
        public final int riskWordDelta;
        public final String addedRiskClauses;

        public BorrowerSnapshot(String ticker, String companyName, String sector, String period,
                                BigDecimal ebitdaM, BigDecimal netDebtM, BigDecimal totalDebtM,
                                BigDecimal interestExpenseM, BigDecimal qoqLeverageDrift,
                                BigDecimal maxLeverageLimit, BigDecimal minCoverageLimit,
                                BigDecimal filingSimilarity, int riskWordDelta, String addedRiskClauses) {
            this.ticker = ticker;
            this.companyName = companyName;
            this.sector = sector;
            this.period = period;
            this.ebitdaM = ebitdaM;
            this.netDebtM = netDebtM;
            this.totalDebtM = totalDebtM;
            this.interestExpenseM = interestExpenseM;
            this.qoqLeverageDrift = qoqLeverageDrift;
            this.maxLeverageLimit = maxLeverageLimit;
            this.minCoverageLimit = minCoverageLimit;
            this.filingSimilarity = filingSimilarity;
            this.riskWordDelta = riskWordDelta;
            this.addedRiskClauses = addedRiskClauses;
        }
    }

    // Object-Oriented Interface for Loan Covenants
    public interface CovenantRule {
        String evaluate(BorrowerSnapshot b);
        boolean isBreached(BorrowerSnapshot b);
    }

    // Rule 1: Maximum Net Debt / EBITDA Leverage Covenant
    public static class MaxNetLeverageRule implements CovenantRule {
        @Override
        public boolean isBreached(BorrowerSnapshot b) {
            BigDecimal actualLeverage = b.netDebtM.divide(b.ebitdaM, SCALE, BANKERS_ROUNDING);
            return actualLeverage.compareTo(b.maxLeverageLimit) > 0;
        }

        @Override
        public String evaluate(BorrowerSnapshot b) {
            BigDecimal actualLeverage = b.netDebtM.divide(b.ebitdaM, SCALE, BANKERS_ROUNDING);
            BigDecimal minRequiredEbitda = b.netDebtM.divide(b.maxLeverageLimit, SCALE, BANKERS_ROUNDING);
            BigDecimal ebitdaHeadroomM = b.ebitdaM.subtract(minRequiredEbitda).setScale(SCALE, BANKERS_ROUNDING);

            String status = isBreached(b) ? "[BREACH - TECHNICAL DEFAULT]" : "[COMPLIANT]";
            return String.format(
                "Net Debt / EBITDA: %sx (Limit: <= %sx) | QoQ Drift: %+.2fx | EBITDA Headroom: $%sM -> %s",
                actualLeverage, b.maxLeverageLimit, b.qoqLeverageDrift, ebitdaHeadroomM, status
            );
        }
    }

    // Rule 2: Minimum EBITDA / Interest Expense Coverage Covenant
    public static class MinInterestCoverageRule implements CovenantRule {
        @Override
        public boolean isBreached(BorrowerSnapshot b) {
            BigDecimal actualCoverage = b.ebitdaM.divide(b.interestExpenseM, SCALE, BANKERS_ROUNDING);
            return actualCoverage.compareTo(b.minCoverageLimit) < 0;
        }

        @Override
        public String evaluate(BorrowerSnapshot b) {
            BigDecimal actualCoverage = b.ebitdaM.divide(b.interestExpenseM, SCALE, BANKERS_ROUNDING);
            String status = isBreached(b) ? "[BREACH - TECHNICAL DEFAULT]" : "[COMPLIANT]";
            return String.format(
                "Interest Coverage: %sx (Limit: >= %sx) -> %s",
                actualCoverage, b.minCoverageLimit, status
            );
        }
    }

    // Downside Stress-Tester (-15% EBITDA Shock & +150 bps Interest Rate Shock)
    public static String runDownsideStressTest(BorrowerSnapshot b) {
        BigDecimal shockedEbitda = b.ebitdaM.multiply(new BigDecimal("0.85")).setScale(SCALE, BANKERS_ROUNDING);
        BigDecimal rateShockAddOn = b.totalDebtM.multiply(new BigDecimal("0.015")).setScale(SCALE, BANKERS_ROUNDING);
        BigDecimal shockedInterest = b.interestExpenseM.add(rateShockAddOn).setScale(SCALE, BANKERS_ROUNDING);

        BigDecimal stressedLeverage = b.netDebtM.divide(shockedEbitda, SCALE, BANKERS_ROUNDING);
        BigDecimal stressedCoverage = shockedEbitda.divide(shockedInterest, SCALE, BANKERS_ROUNDING);

        boolean levFails = stressedLeverage.compareTo(b.maxLeverageLimit) > 0;
        boolean covFails = stressedCoverage.compareTo(b.minCoverageLimit) < 0;

        String verdict = (levFails || covFails)
            ? "FAILS STRESS TEST (Projected Covenant Breach under Downside Case)"
            : "PASSES STRESS TEST (Resilient under -15% EBITDA / +150 bps Shock)";

        return String.format(
            "Stressed EBITDA: $%sM | Stressed Leverage: %sx | Stressed Coverage: %sx -> %s",
            shockedEbitda, stressedLeverage, stressedCoverage, verdict
        );
    }

    public static void main(String[] args) {
        List<CovenantRule> rules = new ArrayList<>();
        rules.add(new MaxNetLeverageRule());
        rules.add(new MinInterestCoverageRule());

        String sql = """
            SELECT 
                v.ticker, v.company_name, v.sector, v.fiscal_period,
                v.ebitda_m, v.net_debt_m, v.total_debt_m, v.interest_expense_m,
                COALESCE(v.qoq_leverage_drift, 0.0) AS qoq_leverage_drift,
                v.max_net_leverage_ratio, v.min_interest_coverage_ratio,
                r.similarity_ratio, r.risk_word_delta, r.added_clauses
            FROM v_credit_covenant_monitor v
            JOIN filing_redlines r 
              ON v.ticker = r.ticker AND v.fiscal_period = r.current_period
            WHERE v.fiscal_period = '2026-Q3'
            ORDER BY (v.net_debt_m / v.ebitda_m) DESC;
        """;

        System.out.println("==========================================================================================");
        System.out.println("   INSTITUTIONAL CREDIT COMMITTEE: COVENANT COMPLIANCE & 10-K REDLINE SURVEILLANCE");
        System.out.println("==========================================================================================");

        try (Connection conn = DriverManager.getConnection(JDBC_URL);
             PreparedStatement stmt = conn.prepareStatement(sql);
             ResultSet rs = stmt.executeQuery()) {

            while (rs.next()) {
                BorrowerSnapshot b = new BorrowerSnapshot(
                    rs.getString("ticker"),
                    rs.getString("company_name"),
                    rs.getString("sector"),
                    rs.getString("fiscal_period"),
                    new BigDecimal(rs.getString("ebitda_m")),
                    new BigDecimal(rs.getString("net_debt_m")),
                    new BigDecimal(rs.getString("total_debt_m")),
                    new BigDecimal(rs.getString("interest_expense_m")),
                    new BigDecimal(rs.getString("qoq_leverage_drift")),
                    new BigDecimal(rs.getString("max_net_leverage_ratio")),
                    new BigDecimal(rs.getString("min_interest_coverage_ratio")),
                    new BigDecimal(rs.getString("similarity_ratio")),
                    rs.getInt("risk_word_delta"),
                    rs.getString("added_clauses")
                );

                System.out.printf("%nBorrowing Entity: %s (%s) | Sector: %s | Period: %s%n",
                        b.companyName, b.ticker, b.sector, b.period);
                System.out.println("------------------------------------------------------------------------------------------");

                for (CovenantRule rule : rules) {
                    System.out.println("  [COVENANT] " + rule.evaluate(b));
                }

                System.out.println("  [DOWNSIDE] " + runDownsideStressTest(b));
                System.out.printf("  [10-K NLP] Text Similarity: %s | Loughran-McDonald Risk Word Surge: %+d%n",
                        b.filingSimilarity, b.riskWordDelta);
                System.out.println("  [REDLINE]  \"" + b.addedRiskClauses + "\"");
            }
            System.out.println("\n==========================================================================================");

        } catch (SQLException e) {
            System.err.println("Database connection error: " + e.getMessage());
        }
    }
}
