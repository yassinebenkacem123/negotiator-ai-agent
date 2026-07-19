"""SRP: Decision Making.

Takes all itemized quotes and applies the math defined in config.py — median
comparison, red-flag threshold, ranking order. Change the negotiation
aggressiveness or red-flag cutoff in config.py, not here.
"""

import statistics

from app.config import settings
from app.models.quote import Quote, RankedCompany, Report


def rank_quotes(job_spec_id: str, quotes: list[Quote]) -> Report:
    priced = [q for q in quotes if q.total is not None]
    if not priced:
        return Report(job_spec_id=job_spec_id, ranked_companies=[], summary="No quotes collected yet.")

    prices = [q.total for q in priced]
    median = statistics.median(prices)

    ranked: list[RankedCompany] = []
    for quote in priced:
        is_low_outlier = quote.total < median * (1 - settings.red_flag_below_median_pct)
        red_flag = None
        if is_low_outlier and not quote.negotiation_successful:
            pct_below = round((1 - quote.total / median) * 100)
            red_flag = (
                f"{pct_below}% below the median quote (${median:,.0f}) with no confirmed negotiation "
                f"behind it — treat as a warning sign, not a bargain, per FMCSA guidance."
            )
        quote.red_flag = red_flag
        ranked.append(
            RankedCompany(
                company_id=quote.company_id,
                company=quote.company,
                total=quote.total,
                final_price=quote.total,
                fees=quote.fees,
                differentiators=quote.differentiators,
                red_flag=red_flag,
                transcript_url=quote.transcript_url,
                recording_url=quote.recording_url,
                rank=0,  # assigned after sort
                recommended=False,  # assigned after sort
            )
        )

    # Non-flagged first (sorted by price), flagged outliers listed last for transparency
    clean = sorted([c for c in ranked if not c.red_flag], key=lambda c: c.total)
    flagged = sorted([c for c in ranked if c.red_flag], key=lambda c: c.total)
    ordered = clean + flagged
    for i, company in enumerate(ordered, start=1):
        company.rank = i

    top = clean[0] if clean else ordered[0]
    top.recommended = True
    summary = (
        f"{top.company} is the recommended pick at ${top.total:,.0f}. "
        f"{len(flagged)} quote(s) flagged as suspiciously low and excluded from the top pick."
    )

    return Report(job_spec_id=job_spec_id, ranked_companies=ordered, summary=summary)
