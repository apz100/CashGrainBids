# North Gower Grains Reporting Roadmap

This file stores reporting ideas and design decisions so they can be resumed without reconstructing the discussion.

## Priority 1: Elevator Basis Market Position

The first redesigned PDF should resemble the existing NGG reference reports as closely as practical:

- North Gower Grains logo/title, report date, market timestamp, and futures/FX quote dates
- Short market commentary and a clear separation between elevator bids and commercial/direct-ship bids
- Separate sections for corn, soybeans, SRW wheat, HRW wheat, and HRS wheat
- Old-crop and new-crop delivery groupings
- Delivery month, futures month/price, CAD basis, CAD cash price, CAD/MT price, basis change, source/location, and NGG rank
- NGG's own bid highlighted; strongest competing elevator bids visually emphasized
- Daily CAD and USD basis movement
- Missing, stale, and data-quality warnings
- Appendix with source dates, FX source/rate type, and optional raw records

## Priority 2: Commercial Buyer and Direct-Ship Report

Keep these out of elevator rankings and analyze them separately:

- Processors: Greenfield and Ingredion
- Exporters: Richardson and Bunge
- Direct-ship competitors: MacEwen, Andersons, BroadGrain, and Prescott
- Great Lakes Grain Embrun as an elevator currently; add its direct-to-port quote separately when available
- CAD and USD basis where the required cash and futures data exist

## Priority 3: Daily Market Movement

Include a compact comparison of:

- Company/location
- Commodity and delivery
- Previous/current CAD basis and CAD basis change
- Previous/current USD basis and USD basis change
- Quote dates and source/rate type

## Priority 4: Opportunity Summary

Automatically identify:

- Highest elevator bid by delivery
- Highest direct-ship bid by delivery
- NGG bids above or below competitors
- Buyers gaining or losing basis
- Unusually large basis movements
- Missing or stale quotes
- Old-crop versus new-crop opportunities

## Future Automated Reports

- Daily Elevator Basis Market Position
- Daily Direct-Ship Buyer Comparison
- Weekly Basis Change Report
- NGG Competitiveness Report
- Buyer Premium/Discount Report
- Forward Sales Opportunity Report
- Missing/Stale Data Report
- Historical Basis Percentile Report
- PDF report plus detailed Excel workbook

## Implementation Notes

- Preserve the existing scraping, email collection, FX, and historical CSV pipeline.
- Keep calculations independent from presentation formatting.
- Use configurable source/location classifications.
- Preserve unrounded values for calculations and round only for display.
- Validate each PDF by rendering it and visually checking page breaks, tables, colors, and legibility.
