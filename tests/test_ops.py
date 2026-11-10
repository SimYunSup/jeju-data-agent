import pandas as pd
import pytest

from jeju_data_agent.datasets import normalize
from jeju_data_agent.ops import OpError, run_pipeline


@pytest.fixture
def prices():
    return normalize(pd.DataFrame({
        "baseDate": ["20240102", "20240103", "20240201", "20240202", "20240301"],
        "cultivar": ["깐마늘", "깐마늘", "깐마늘", "월동무", "깐마늘"],
        "averagePrice": ["10000.00", "6585.50", "7000", "1,200", "8000"],
    }))


def _run(df, steps):
    return run_pipeline(df, steps, "D1", lambda h: df)


def test_exported_code_reproduces_result(prices):
    out, code = _run(prices, [
        {"op": "filter", "column": "cultivar", "value": "깐마늘"},
        {"op": "resample", "date_column": "baseDate", "freq": "M", "agg": {"averagePrice": "mean"}},
        {"op": "pct_change", "column": "averagePrice", "name": "증감률"},
    ])
    assert list(out["averagePrice"].round(2)) == [8292.75, 7000.0, 8000.0]
    ns = {"pd": pd, "D1": prices}
    exec(code, ns)
    pd.testing.assert_frame_equal(ns["df"].reset_index(drop=True), out)


def test_date_between_filter_uses_real_dates(prices):
    out, code = _run(prices, [{"op": "filter", "column": "baseDate", "cmp": "between",
                               "value": ["2024-02-01", "2024-02-28"]}])
    assert len(out) == 2
    ns = {"pd": pd, "D1": prices}
    exec(code, ns)
    assert len(ns["df"]) == 2


def test_unknown_column_error_lists_available_columns(prices):
    with pytest.raises(OpError) as exc:
        _run(prices, [{"op": "groupby", "by": ["품종"], "agg": {"averagePrice": "mean"}}])
    assert "cultivar" in str(exc.value)


def test_share_sums_to_100(prices):
    out, _ = _run(prices, [
        {"op": "groupby", "by": ["cultivar"], "agg": {"averagePrice": "sum"}},
        {"op": "share", "column": "averagePrice", "name": "비중"},
    ])
    assert out["비중"].sum() == pytest.approx(100.0)


def test_normalize_converts_numbers_but_keeps_codes_as_text():
    df = normalize(pd.DataFrame({"정류소ID": ["0012", "0345"], "이용자수": ["1,234", "56"]}))
    assert df["정류소ID"].tolist() == ["0012", "0345"]
    assert df["이용자수"].tolist() == [1234, 56]


def test_normalize_treats_statistics_dash_as_missing_not_text():
    df = normalize(pd.DataFrame({"재배면적": ["1,200", "-", "35"]}))
    assert df["재배면적"].sum() == 1235
    assert df["재배면적"].isna().sum() == 1


def test_normalize_parses_year_month_api_columns():
    df = normalize(pd.DataFrame({"dtYearMonth": ["202301", "202302"], "visitorCnt": ["1007", "628"]}))
    assert df["dtYearMonth"].dt.month.tolist() == [1, 2]
    assert df["visitorCnt"].sum() == 1635


def test_month_over_month_skips_missing_months_instead_of_comparing_june():
    # 실측 오답: 7~11월이 빠진 표에서 12월 '전월 대비'가 6월과 비교됐다.
    df = pd.DataFrame({"월": pd.to_datetime(["2025-05-01", "2025-06-01", "2025-11-01", "2025-12-01"]),
                       "가격": [100.0, 200.0, 175.0, 667.7]})
    df = df.drop(index=2)
    out, code = run_pipeline(df, [{"op": "pct_change", "column": "가격", "name": "전월대비"}], "R1", lambda h: None)
    assert out["전월대비"].round(1).tolist()[1] == 100.0
    assert pd.isna(out["전월대비"].iloc[2])
    assert "period_pct_change" in code


def test_ratio_named_column_must_be_a_ratio():
    df = pd.DataFrame({"2024": [10.0], "2023": [5.0]})
    with pytest.raises(OpError, match="비율"):
        run_pipeline(df, [{"op": "derive", "name": "증감률", "left": "2024", "operator": "-", "right": "2023"}],
                     "R1", lambda h: None)
