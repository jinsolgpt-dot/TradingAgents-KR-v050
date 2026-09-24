"""Compose Naver articles and DART filings without changing upstream news tools."""

from . import dart_api, naver_news
from .errors import VendorError


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    sections = []
    failures = []
    for source, fetch in (("Naver", naver_news.get_news_naver), ("DART", dart_api.get_dart_events)):
        try:
            sections.append(f"## {source}\n{fetch(ticker, start_date, end_date)}")
        except (VendorError, RuntimeError):
            failures.append(source)
    if not sections:
        raise VendorError("Korean news sources unavailable; check Naver/DART configuration.")
    if failures:
        sections.append("DATA_UNAVAILABLE: " + ", ".join(failures))
    return "\n\n".join(sections)


def get_insider_transactions(ticker: str, curr_date: str | None = None) -> str:
    return (
        f"DATA_UNAVAILABLE: Korean insider transactions for {ticker} as of {curr_date}. "
        "DART general disclosures are included in get_news, but must not be treated "
        "as a complete insider transaction dataset."
    )
