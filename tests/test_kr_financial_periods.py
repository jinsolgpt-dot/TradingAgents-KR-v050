import json

import pytest

from tradingagents.dataflows import dart_api


def fact(kind, account, amount, **kwargs):
    return dict(sj_div=kind, account_id=account, account_nm=account,
                thstrm_amount=amount, rcept_no="20260814003894", currency="KRW", **kwargs)


def render(rows, report="11012", kind=None):
    return dart_api._format_financials(rows, "00760971", 2026, report, "CFS", "2026-09-25", kind)


def test_interim_income_preserves_quarter_ytd_and_comparable_prior():
    text = render([fact("CIS", "ifrs-full_ProfitLoss", "-29", thstrm_add_amount="484",
                        frmtrm_q_amount="15", frmtrm_add_amount="386", thstrm_nm="H1")])
    assert '"current_3m": "-29"' in text
    assert '"current_ytd": "484"' in text
    assert '"prior_year_3m": "15"' in text
    assert '"prior_year_ytd": "386"' in text
    assert "ifrs-full_ProfitLoss" in text and "H1" in text


def test_missing_ytd_is_not_invented_and_annual_is_not_quarterly():
    interim = render([fact("IS", "Revenue", "100")])
    assert '"current_ytd": null' in interim
    annual = render([fact("IS", "Revenue", "100", frmtrm_amount="80")], "11011")
    assert '"current_year": "100"' in annual
    assert '"prior_year": "80"' in annual
    assert '"current_3m":' not in annual


def test_cashflow_conflict_uses_verified_document_without_hiding_raw(monkeypatch):
    monkeypatch.setattr(dart_api, "verified_cashflow_profit", lambda *a: {"current": "484", "prior": "386"})
    rows = [fact("CIS", "ifrs-full_ProfitLoss", "-29", thstrm_add_amount="484"),
            fact("CF", "ifrs-full_ProfitLoss", "-29", frmtrm_q_amount="15")]
    text = render(rows, kind="CF")
    assert '"current_ytd": "484"' in text
    assert '"api_current_raw": "-29"' in text
    assert "document_verified" in text
    assert "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260814003894" in text


def test_unverified_cashflow_conflict_is_not_usable_for_arithmetic(monkeypatch):
    monkeypatch.setattr(dart_api, "verified_cashflow_profit", lambda *a: None)
    rows = [fact("CIS", "ifrs-full_ProfitLoss", "-29", thstrm_add_amount="484"),
            fact("CF", "ifrs-full_ProfitLoss", "-29")]
    text = render(rows, kind="CF")
    line = next(json.loads(line) for line in text.splitlines() if line.startswith('{"statement"'))
    assert line["amounts"]["current_ytd"] is None
    assert line["validation"] == "unresolved_period_conflict"


def test_cashflow_matching_ytd_does_not_download_document(monkeypatch):
    def unexpected(*a):
        raise AssertionError("no conflict")
    monkeypatch.setattr(dart_api, "verified_cashflow_profit", unexpected)
    text = render([fact("CIS", "ifrs-full_ProfitLoss", "-29", thstrm_add_amount="484"),
                   fact("CF", "ifrs-full_ProfitLoss", "484", frmtrm_q_amount="386")], kind="CF")
    assert '"current_ytd": "484"' in text


@pytest.mark.parametrize("variant", ["valid", "ambiguous", "wrong_total", "wrong_period", "reversed"])
def test_source_verification_requires_unique_matching_cashflow_table(monkeypatch, variant):
    from tradingagents.dataflows import dart_document as doc

    row = fact("CF", "ifrs-full_ProfitLoss", "-29", thstrm_nm="H1", frmtrm_q_nm="Prior H1")
    row["account_nm"] = "반기순이익(손실)"
    anchors = [fact("CF", "ifrs-full_CashFlowsFromUsedInOperatingActivities", "458"),
               fact("CF", "ifrs-full_CashFlowsFromUsedInInvestingActivities", "293")]
    parser = doc._Tables()
    parser.feed('<TABLE><TR><TH></TH><TH>H1</TH><TH>Prior H1</TH></TR>'
                '<TR><TD>Operating</TD><TD>458</TD><TD>445</TD></TR>'
                '<TR><TD>Investing</TD><TD>293</TD><TD>(60)</TD></TR>'
                '<TR><TD>반기순이익</TD><TD>484</TD><TD>386</TD></TR></TABLE>')
    tables = parser.tables
    if variant == "ambiguous":
        tables = tables * 2
    elif variant == "wrong_total":
        tables[0][1][1] = "459"
    elif variant == "wrong_period":
        tables[0][0][1] = "Q1"
    elif variant == "reversed":
        tables[0][0] = ["", "Prior H1", "H1"]
    monkeypatch.setattr(doc, "_document_tables", lambda receipt: tables)
    result = doc.verified_cashflow_profit(row, anchors)
    assert result == ({"current": "484", "prior": "386"} if variant == "valid" else None)


def test_document_fetch_error_does_not_expose_key(monkeypatch):
    import requests

    from tradingagents.dataflows import dart_document as doc

    monkeypatch.setenv("DART_API_KEY", "SECRET")
    def fail(*args, **kwargs):
        raise requests.ConnectionError("SECRET")
    monkeypatch.setattr(requests, "get", fail)
    doc._document_tables.cache_clear()
    with pytest.raises(RuntimeError) as caught:
        doc._document_tables("20260814003894")
    assert "SECRET" not in str(caught.value)
