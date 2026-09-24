"""Korean market configuration on top of the unmodified v0.5 agent workflow."""

from copy import deepcopy


def apply_korea_profile(base: dict) -> dict:
    """Return an independent Korean profile without mutating upstream defaults."""
    config = deepcopy(base)
    config.update(market="KR", output_language="Korean")
    config["data_vendors"].update({
        "core_stock_apis": "kis",
        "technical_indicators": "kis",
        "fundamental_data": "dart",
        "news_data": "korea",
        "macro_data": "ecos",
    })
    config["tool_vendors"].update({"get_fundamentals": "kis"})
    config["benchmark_map"].update({".KS": "^KS11", ".KQ": "^KQ11"})
    config["global_news_queries"] = ["한국은행 기준금리", "한국 수출 환율", "코스피 코스닥"]
    return config


def get_korea_config(overrides: dict | None = None) -> dict:
    """Use the upstream config contract; explicit overrides always win."""
    from tradingagents.default_config import DEFAULT_CONFIG

    config = apply_korea_profile(DEFAULT_CONFIG)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(deepcopy(value))
        else:
            config[key] = deepcopy(value)
    return config


def normalize_portfolio(portfolio):
    """Match Korean book positions to the same canonical symbols as the analysis."""
    from tradingagents.dataflows.korea_ticker import canonical_yahoo_symbol, get_stock_code

    if portfolio is None:
        return None
    book = portfolio.model_copy(deep=True)
    for position in book.positions:
        if get_stock_code(position.ticker):
            position.ticker = canonical_yahoo_symbol(position.ticker)
    return book


def instrument_context(ticker: str, curr_date: str | None) -> str:
    from tradingagents.agents.utils.agent_utils import build_instrument_context
    from tradingagents.dataflows.korea_ticker import get_instrument_profile

    profile = get_instrument_profile(ticker)
    identity = {"name": profile.get("name"), "exchange": profile.get("market")}
    return build_instrument_context(ticker, "stock", identity, curr_date) + (
        " This is a Korean listed equity. Prices and financial amounts are KRW unless "
        "the source states otherwise; trading dates use Asia/Seoul. Use KIS for prices, "
        "DART for disclosures and statements, Naver for news, and ECOS for Korean macro. "
        "For get_macro_indicators use ECOS aliases (base_rate, usd_krw, cpi, kospi, "
        "m2), not US FRED IDs. Missing or non-vintage data must remain unavailable."
    )
