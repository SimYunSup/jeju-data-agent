"""선언형 분석 파이프라인.

LLM은 임의 코드를 실행하지 않고, 아래 연산을 JSON 단계로만 지시한다. 엔진은 각 단계를 pandas로
결정적으로 실행하고 같은 결과를 다시 만드는 pandas 코드를 함께 남긴다(재현성·감사 가능성).
"""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

AGG_FUNCS = {"sum", "mean", "count", "median", "min", "max", "nunique", "std"}
COMPARE = {"==", "!=", ">", ">=", "<", "<=", "in", "not_in", "contains", "between"}
FREQ = {"D": "D", "W": "W", "M": "ME", "Q": "QE", "Y": "YE"}
DATE_PARTS = {"year", "month", "quarter", "weekday", "day", "hour"}


class OpError(ValueError):
    pass


def _need(df: pd.DataFrame, *cols: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise OpError(f"없는 열: {missing}. 사용 가능한 열: {list(df.columns)}")


def _cols(value: Any) -> list[str]:
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def _coerce(series: pd.Series, value: Any) -> Any:
    if pd.api.types.is_datetime64_any_dtype(series):
        if isinstance(value, list):
            return [pd.Timestamp(v) for v in value]
        return pd.Timestamp(value)
    if pd.api.types.is_numeric_dtype(series):
        if isinstance(value, list):
            return [float(v) for v in value]
        return float(value)
    if isinstance(value, list):
        return [str(v) for v in value]
    return str(value)


def _value_code(v: Any, series: pd.Series) -> str:
    if pd.api.types.is_datetime64_any_dtype(series):
        if isinstance(v, list):
            return "[" + ", ".join(f"pd.Timestamp({str(x.date())!r})" for x in v) + "]"
        return f"pd.Timestamp({str(v.date())!r})"
    return repr(v)


def op_filter(df, step, ctx):
    col, cmp = step["column"], step.get("cmp", "==")
    _need(df, col)
    if cmp not in COMPARE:
        raise OpError(f"filter의 cmp는 {sorted(COMPARE)} 중 하나")
    s = df[col]
    if cmp == "contains":
        v = str(step["value"])
        return df[s.astype(str).str.contains(v, regex=False)], f"df = df[df[{col!r}].astype(str).str.contains({v!r}, regex=False)]"
    v = _coerce(s, step["value"])
    vc = _value_code(v, s)
    if cmp in ("in", "not_in"):
        v = v if isinstance(v, list) else [v]
        vc = _value_code(v, s)
        mask = s.isin(v)
        if cmp == "not_in":
            return df[~mask], f"df = df[~df[{col!r}].isin({vc})]"
        return df[mask], f"df = df[df[{col!r}].isin({vc})]"
    if cmp == "between":
        lo, hi = v
        return df[s.between(lo, hi)], f"df = df[df[{col!r}].between(*{vc})]"
    ops: dict[str, Callable] = {"==": s.__eq__, "!=": s.__ne__, ">": s.__gt__, ">=": s.__ge__, "<": s.__lt__, "<=": s.__le__}
    return df[ops[cmp](v)], f"df = df[df[{col!r}] {cmp} {vc}]"


def op_select(df, step, ctx):
    cols = _cols(step["columns"])
    _need(df, *cols)
    return df[cols], f"df = df[{cols!r}]"


def op_rename(df, step, ctx):
    mapping = dict(step["mapping"])
    _need(df, *mapping)
    return df.rename(columns=mapping), f"df = df.rename(columns={mapping!r})"


def op_derive(df, step, ctx):
    name = step["name"]
    if "part" in step:
        col, part = step["column"], step["part"]
        _need(df, col)
        if part not in DATE_PARTS:
            raise OpError(f"part는 {sorted(DATE_PARTS)} 중 하나")
        if not pd.api.types.is_datetime64_any_dtype(df[col]):
            raise OpError(f"{col}은 날짜 열이 아닙니다(dtype={df[col].dtype})")
        out = df.assign(**{name: getattr(df[col].dt, part)})
        return out, f"df[{name!r}] = df[{col!r}].dt.{part}"
    if "sum_of" in step:
        cols = _cols(step["sum_of"])
        _need(df, *cols)
        return df.assign(**{name: df[cols].sum(axis=1)}), f"df[{name!r}] = df[{cols!r}].sum(axis=1)"
    left, operator, right = step["left"], step["operator"], step["right"]
    if operator not in {"+", "-", "*", "/"}:
        raise OpError("operator는 + - * / 중 하나")
    if any(k in name for k in ("률", "율", "%", "비중")) and "%p" not in name and operator != "/":
        # 실측 오류: '증감률' 이름으로 '-' 연산을 해 증감 인원이 비율처럼 보고됐다.
        raise OpError(f"'{name}'은 비율 이름인데 '{operator}' 연산입니다. 비율은 operator '/'와 percent:true, "
                      "증감률은 pct_change를 쓰고, 차이라면 이름을 '증감' 등으로 바꾸세요.")
    _need(df, left)
    if not pd.api.types.is_numeric_dtype(df[left]):
        raise OpError(f"{left}은(는) 숫자 열이 아닙니다(dtype={df[left].dtype}). 숫자가 아닌 값이 섞였는지 profile을 확인하세요.")
    if isinstance(right, str):
        _need(df, right)
        r, rc = df[right], f"df[{right!r}]"
    else:
        r, rc = float(right), repr(float(right))
    l = df[left]
    result = {"+": l + r, "-": l - r, "*": l * r, "/": l / r}[operator]
    if operator == "/" and step.get("percent"):
        result = result * 100
        return df.assign(**{name: result}), f"df[{name!r}] = df[{left!r}] / {rc} * 100"
    return df.assign(**{name: result}), f"df[{name!r}] = df[{left!r}] {operator} {rc}"


def _agg_spec(df, agg: dict[str, str]):
    for col, func in agg.items():
        if func not in AGG_FUNCS:
            raise OpError(f"집계 함수는 {sorted(AGG_FUNCS)} 중 하나")
        if col != "*":
            _need(df, col)
    return agg


def op_groupby(df, step, ctx):
    by = _cols(step.get("by"))
    if not by:
        raise OpError("by에 묶을 열을 1개 이상 넣으세요(전체 합계는 describe 또는 derive/sum_of를 쓰세요)")
    _need(df, *by)
    agg = _agg_spec(df, step.get("agg") or {"*": "count"})
    g = df.groupby(by, dropna=False)
    parts, code = [], []
    for col, func in agg.items():
        if col == "*":
            parts.append(g.size().rename("건수"))
            code.append("g.size().rename('건수')")
        else:
            name = f"{col}_{func}" if step.get("suffix") else col
            parts.append(getattr(g[col], func)().rename(name))
            code.append(f"g[{col!r}].{func}().rename({name!r})")
    out = pd.concat(parts, axis=1).reset_index()
    return out, f"g = df.groupby({by!r}, dropna=False)\ndf = pd.concat([{', '.join(code)}], axis=1).reset_index()"


def op_resample(df, step, ctx):
    col, freq = step["date_column"], step.get("freq", "M")
    _need(df, col)
    if freq not in FREQ:
        raise OpError(f"freq는 {sorted(FREQ)} 중 하나(D=일, W=주, M=월, Q=분기, Y=연)")
    if not pd.api.types.is_datetime64_any_dtype(df[col]):
        raise OpError(f"{col}은 날짜 열이 아닙니다")
    agg = _agg_spec(df, step.get("agg") or {"*": "count"})
    by = _cols(step.get("by"))
    _need(df, *by)
    grouper = pd.Grouper(key=col, freq=FREQ[freq])
    g = df.groupby([*by, grouper])
    parts, code = [], []
    for c, func in agg.items():
        if c == "*":
            parts.append(g.size().rename("건수"))
            code.append("g.size().rename('건수')")
        else:
            parts.append(getattr(g[c], func)())
            code.append(f"g[{c!r}].{func}()")
    out = pd.concat(parts, axis=1).reset_index()
    return out, (f"g = df.groupby([*{by!r}, pd.Grouper(key={col!r}, freq={FREQ[freq]!r})])\n"
                 f"df = pd.concat([{', '.join(code)}], axis=1).reset_index()")


def op_pivot(df, step, ctx):
    index, columns, values = step["index"], step["columns"], step["values"]
    func = step.get("agg", "sum")
    _need(df, index, columns, values)
    if func not in AGG_FUNCS:
        raise OpError(f"집계 함수는 {sorted(AGG_FUNCS)} 중 하나")
    out = df.pivot_table(index=index, columns=columns, values=values, aggfunc=func).reset_index()
    out.columns = [str(c) for c in out.columns]
    return out, (f"df = df.pivot_table(index={index!r}, columns={columns!r}, values={values!r}, aggfunc={func!r}).reset_index()\n"
                 "df.columns = [str(c) for c in df.columns]")


def op_sort(df, step, ctx):
    by = _cols(step["by"])
    _need(df, *by)
    asc = bool(step.get("ascending", False))
    return df.sort_values(by, ascending=asc), f"df = df.sort_values({by!r}, ascending={asc})"


def op_head(df, step, ctx):
    n = int(step.get("n", 10))
    return df.head(n), f"df = df.head({n})"


def op_share(df, step, ctx):
    col = step["column"]
    _need(df, col)
    name = step.get("name", f"{col}_비중(%)")
    return df.assign(**{name: df[col] / df[col].sum() * 100}), f"df[{name!r}] = df[{col!r}] / df[{col!r}].sum() * 100"


def _infer_period(dates: pd.Series) -> str:
    """날짜 간격으로 기간 단위를 추정한다(월 자료에 빠진 달이 있어도 최소 간격은 한 달)."""
    gaps = dates.dropna().drop_duplicates().sort_values().diff().dropna().dt.days
    gap = gaps[gaps > 0].min() if len(gaps) else 1
    for days, freq in ((365, "Y"), (89, "Q"), (28, "M"), (7, "W")):
        if gap >= days:
            return freq
    return "D"


def period_pct_change(df: pd.DataFrame, column: str, date_column: str, freq: str, periods: int = 1,
                      by: list[str] | None = None) -> pd.Series:
    """바로 앞 기간(같은 그룹)의 값 대비 증감률(%). 앞 기간 행이 없으면 건너뛰지 않고 빈 값으로 둔다."""
    by = list(by or [])
    period = df[date_column].dt.to_period(freq)
    keys = df[by].assign(_p=period.to_numpy())
    prev = keys.assign(_p=(period + periods).to_numpy(), _v=df[column].to_numpy())
    base = keys.merge(prev, on=[*by, "_p"], how="left")["_v"].to_numpy()
    return pd.Series((df[column].to_numpy() / base - 1) * 100, index=df.index)


def op_pct_change(df, step, ctx):
    col = step["column"]
    _need(df, col)
    periods = int(step.get("periods", 1))
    name = step.get("name", f"{col}_증감률(%)")
    by = _cols(step.get("by"))
    _need(df, *by)
    date = step.get("date_column")
    if date is None:
        dates = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
        date = dates[0] if len(dates) == 1 else None
    if date is not None:
        _need(df, date)
        if not pd.api.types.is_datetime64_any_dtype(df[date]):
            raise OpError(f"{date}은 날짜 열이 아닙니다(dtype={df[date].dtype})")
        freq = step.get("freq") or _infer_period(df[date])
        if freq not in FREQ:
            raise OpError(f"freq는 {sorted(FREQ)} 중 하나")
        period = df[date].dt.to_period(freq)
        if not df[by].assign(_p=period.to_numpy()).duplicated().any():
            # 날짜 기준 비교: 중간 기간이 빠진 행(예: 6월 다음 12월)을 '전월'로 오인하지 않는다.
            series = period_pct_change(df, col, date, freq, periods, by)
            return df.assign(**{name: series}), (
                "from jeju_data_agent.ops import period_pct_change\n"
                f"df[{name!r}] = period_pct_change(df, {col!r}, {date!r}, {freq!r}, {periods}, {by!r})")
    if by:
        series = df.groupby(by)[col].pct_change(periods=periods) * 100
        return df.assign(**{name: series}), f"df[{name!r}] = df.groupby({by!r})[{col!r}].pct_change(periods={periods}) * 100"
    return df.assign(**{name: df[col].pct_change(periods=periods) * 100}), f"df[{name!r}] = df[{col!r}].pct_change(periods={periods}) * 100"


def op_rolling(df, step, ctx):
    col, window = step["column"], int(step["window"])
    _need(df, col)
    name = step.get("name", f"{col}_{window}이동평균")
    return df.assign(**{name: df[col].rolling(window, min_periods=1).mean()}), f"df[{name!r}] = df[{col!r}].rolling({window}, min_periods=1).mean()"


def op_merge(df, step, ctx):
    right_handle = step["right"]
    right = ctx["resolve"](right_handle)
    how = step.get("how", "inner")
    if how not in {"inner", "left", "right", "outer"}:
        raise OpError("how는 inner/left/right/outer")
    if "on" in step:
        on = _cols(step["on"])
        _need(df, *on)
        _need(right, *on)
        return df.merge(right, on=on, how=how), f"df = df.merge({right_handle}, on={on!r}, how={how!r})"
    lo, ro = _cols(step["left_on"]), _cols(step["right_on"])
    _need(df, *lo)
    _need(right, *ro)
    return (df.merge(right, left_on=lo, right_on=ro, how=how),
            f"df = df.merge({right_handle}, left_on={lo!r}, right_on={ro!r}, how={how!r})")


def op_corr(df, step, ctx):
    a, b = _cols(step["columns"])[:2]
    _need(df, a, b)
    r = float(df[a].corr(df[b]))
    out = pd.DataFrame([{"x": a, "y": b, "상관계수": round(r, 4), "n": int(df[[a, b]].dropna().shape[0])}])
    return out, f"r = df[{a!r}].corr(df[{b!r}])  # 피어슨 상관계수"


def op_describe(df, step, ctx):
    cols = _cols(step.get("columns")) or [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    _need(df, *cols)
    out = df[cols].describe().T.reset_index().rename(columns={"index": "열"})
    return out, f"df = df[{cols!r}].describe().T.reset_index()"


OPS: dict[str, Callable] = {
    "filter": op_filter, "select": op_select, "rename": op_rename, "derive": op_derive,
    "groupby": op_groupby, "resample": op_resample, "pivot": op_pivot, "sort": op_sort,
    "head": op_head, "share": op_share, "pct_change": op_pct_change, "rolling": op_rolling,
    "merge": op_merge, "corr": op_corr, "describe": op_describe,
}

OPS_DOC = """연산(steps 배열, 위에서 아래로 실행. 각 단계는 {"op": 연산명, ...}):
- filter {column, cmp: == != > >= < <= in not_in contains between, value}  (between은 [최소,최대], 날짜는 'YYYY-MM-DD')
- select {columns:[...]} / rename {mapping:{기존:새}}
- derive {name, left, operator:+ - * /, right: 열이름|숫자, percent?:true}  또는 {name, sum_of:[열...]}(가로 합계)  또는 {name, column, part: year|month|quarter|weekday|day|hour}
- groupby {by:[...], agg:{열: sum|mean|count|median|min|max|nunique|std, "*": count}}
- resample {date_column, freq: D|W|M|Q|Y, agg:{...}, by?:[...]}  (날짜 열을 기간 단위로 집계)
- pivot {index, columns, values, agg}
- sort {by, ascending:false} / head {n}
- share {column, name?}  (전체 대비 비중 %)
- pct_change {column, periods?:1, by?:[...], date_column?, freq?: D|W|M|Q|Y, name?}  (증감률 %. 날짜 열이 있으면 바로 앞 기간과 비교하고, 앞 기간 자료가 없으면 빈 값)
- rolling {column, window, name?}  (이동평균)
- merge {right: 표핸들, on | left_on+right_on, how: inner|left|right|outer}
- corr {columns:[a,b]}  (피어슨 상관계수)
- describe {columns?:[...]}  (기술통계)"""


def run_pipeline(df: pd.DataFrame, steps: list[dict], source: str, resolve: Callable[[str], pd.DataFrame]) -> tuple[pd.DataFrame, str]:
    code = [f"df = {source}.copy()"]
    ctx = {"resolve": resolve}
    for i, step in enumerate(steps, 1):
        name = step.get("op")
        if name not in OPS:
            raise OpError(f"{i}단계: 알 수 없는 연산 {name!r}. 가능한 연산: {sorted(OPS)}")
        try:
            df, line = OPS[name](df, step, ctx)
        except OpError as exc:
            raise OpError(f"{i}단계({name}): {exc}") from exc
        except KeyError as exc:
            raise OpError(f"{i}단계({name}): 필수 항목 {exc} 누락") from exc
        code.append(line)
    return df.reset_index(drop=True), "\n".join(code)
