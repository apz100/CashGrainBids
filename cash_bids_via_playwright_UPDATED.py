"""Compatibility entry point for the CashGrainBids daily collector.

Keep this filename because it is referenced by the scheduled-task runner and
older documentation. Implementation modules now live in ``cashgrainbids``.
"""

from cashgrainbids.config import AGRICHARTS_TARGETS as TARGETS
from cashgrainbids.config import OUTPUT_DIR
from cashgrainbids.pipeline import main
from cashgrainbids.processing import (
    add_basis_change_column,
    add_mt_cash_price,
    filter_eastern_ontario_locations,
    normalize_agricharts_basis,
    normalize_change_value,
    normalize_futures_price,
    norm_full_month,
    norm_short_month,
    sort_output_rows,
)
from cashgrainbids.web_collectors import (
    scrape_agricharts as scrape_one,
    scrape_greenfield_johnstown,
    scrape_great_lakes_embrun,
    scrape_ingredion_cardinal_cey_dent,
)

__all__ = [
    "TARGETS", "OUTPUT_DIR", "main", "add_basis_change_column", "add_mt_cash_price",
    "filter_eastern_ontario_locations", "normalize_agricharts_basis", "normalize_change_value",
    "normalize_futures_price", "norm_full_month", "norm_short_month", "sort_output_rows",
    "scrape_one", "scrape_greenfield_johnstown", "scrape_great_lakes_embrun",
    "scrape_ingredion_cardinal_cey_dent",
]


if __name__ == "__main__":
    raise SystemExit(main())
