# NGG pricing decision layer

The daily pipeline preserves the existing bid fields and appends decision-support
columns for North Gower quotes. It does not change published bids automatically.

## Configuration

Edit cashgrainbids/config.py:

- NGG_US_BASIS_CEILINGS: keyed by (commodity, current|next); leave as None
  until NGG approves the maximum USD basis.
- NGG_COMPETITOR_PREMIUMS: USD/bu premium over the selected competitor
  benchmark. A value of 0.0 means no deliberate premium.
- NGG_BENCHMARK_METHOD: average_competitor, second_best_competitor,
  best_competitor, selected_competitor, or average_kars_lansdowne.
- NGG_SELECTED_COMPETITOR: used when the method is selected_competitor.

## Matching safeguards

NGG rows are identified by a North Gower location. Competitors are limited to
Kars, Lansdowne, and Vankleek Hill. A competitor is comparable only when its
commodity, delivery period, delivery end, and futures reference match the NGG
row. Standardized futures references are preferred when available.

## Formulas

With CADUSD expressed as USD per CAD:

FX Neutral CAD Basis = (Futures Today + Previous NGG US Basis) / CADUSD Today - Futures Today
FX/Futures Adjustment = FX Neutral CAD Basis - Previous NGG CAD Basis
CAD Basis at USD Ceiling = (Futures + Maximum Allowed US Basis) / CADUSD - Futures
Competitive US Basis Target = Competitor Benchmark US Basis + Allowed Premium
Competitive CAD Basis = (Futures + Competitive US Basis Target) / CADUSD - Futures
Recommended Max CAD Basis = min(CAD Basis at USD Ceiling, Competitive CAD Basis)
Current CAD Basis vs Recommended = Current NGG CAD Basis - Recommended Max CAD Basis

The sensitivity column is the exact change in CAD basis for a +0.01 change in
CADUSD at the current futures and USD-basis levels.
