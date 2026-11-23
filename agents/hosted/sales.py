"""Sales calculations shared by the hosted and standalone Kernel Panic demos."""

import csv
from collections import defaultdict
from pathlib import Path

SALES = list(csv.DictReader((Path(__file__).parent / "data" / "whisker-sales-2026.csv").open()))
GROUP_COLUMNS = {"month": "month", "category": "category", "product": "product_name"}


def summarize_sales(group_by: str = "category", month: str | None = None) -> str:
    rows = [row for row in SALES if not month or row["month"] == month]
    if not rows:
        return "No sales data for that filter."
    column = GROUP_COLUMNS.get(group_by, "category")
    totals: dict[str, list[float]] = defaultdict(lambda: [0, 0.0, 0])
    for row in rows:
        total = totals[row[column]]
        total[0] += int(row["units_sold"])
        total[1] += float(row["revenue_usd"])
        total[2] += int(row["returns"])
    return "\n".join(
        f"{key}: units={int(units)}, revenue=${revenue:,.2f}, returns={int(returns)}"
        for key, (units, revenue, returns) in sorted(totals.items())
    )
