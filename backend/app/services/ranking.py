"""SRP: Decision Making.

Takes all itemized quotes and applies the math defined in config.py — median
comparison, red-flag threshold, ranking order. Change the negotiation
aggressiveness or red-flag cutoff in config.py, not here.
"""

import statistics

from app.config import settings
from app.models.quote import Quote, RankedCompany, Report


def _final_price(quote: Quote) -> float | None:
    return quote.negotiated_price if quote.negotiated_price is not None else quote.initial_price


def rank_quotes(job_spec_id: str, quotes: list[Quote]) -> Report:
    priced = [q for q in quotes if _final_price(q) is not None]
    if not priced:
        return Report(job_spec_id=job_spec_id, ranked_companies=[], summary="No quotes collected yet.")

    prices = [_final_price(q) for q in priced]
    median = statistics.median(prices)

    ranked: list[RankedCompany] = []
    for quote in priced:
        price = _final_price(quote)
        red_flag = price < median * (1 - settings.red_flag_below_median_pct) and not quote.negotiation_successful
        quote.red_flag = red_flag
        ranked.append(
            RankedCompany(
                company_id=quote.company_id,
                final_price=price,
                rank=0,  # assigned after sort
                differentiators=quote.differentiators,
                red_flag=red_flag,
            )
        )

    # Non-flagged first (sorted by price), flagged outliers listed last for transparency
    clean = sorted([c for c in ranked if not c.red_flag], key=lambda c: c.final_price)
    flagged = sorted([c for c in ranked if c.red_flag], key=lambda c: c.final_price)
    ordered = clean + flagged
    for i, company in enumerate(ordered, start=1):
        company.rank = i

    top = clean[0] if clean else ordered[0]
    summary = (
        f"Recommended: company {top.company_id} at ${top.final_price:,.0f}. "
        f"{len(flagged)} quote(s) flagged as suspiciously low and excluded from the top pick."
    )

    return Report(job_spec_id=job_spec_id, ranked_companies=ordered, summary=summary)
