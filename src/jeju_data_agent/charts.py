"""matplotlib 차트(한글 글꼴 자동 선택, 화면 없는 서버에서도 동작)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402

KINDS = {"line", "bar", "barh", "pie", "scatter"}
_KOREAN_FONTS = ["Malgun Gothic", "AppleGothic", "Apple SD Gothic Neo", "NanumGothic", "Noto Sans CJK KR", "Noto Sans KR"]


def _setup_font() -> str | None:
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in _KOREAN_FONTS:
        if name in available:
            plt.rcParams["font.family"] = name
            plt.rcParams["axes.unicode_minus"] = False
            return name
    return None


FONT = _setup_font()


class ChartError(ValueError):
    pass


def render(df: pd.DataFrame, kind: str, x: str, y: list[str], title: str, path: Path, max_points: int = 40) -> Path:
    if kind not in KINDS:
        raise ChartError(f"kind는 {sorted(KINDS)} 중 하나")
    missing = [c for c in [x, *y] if c not in df.columns]
    if missing:
        raise ChartError(f"없는 열: {missing}. 사용 가능한 열: {list(df.columns)}")
    if not y:
        raise ChartError("y 열을 하나 이상 지정하세요")
    data = df[[x, *y]].dropna(subset=y)
    if kind in {"bar", "barh", "pie"} and len(data) > max_points:
        data = data.head(max_points)
    if data.empty:
        raise ChartError("그릴 데이터가 없습니다(필터 결과가 비었는지 확인)")

    fig, ax = plt.subplots(figsize=(9, 5), dpi=120)
    if kind == "line":
        for col in y:
            ax.plot(data[x], data[col], marker="o" if len(data) <= 40 else None, markersize=3, label=col)
    elif kind == "bar":
        data.plot.bar(x=x, y=y, ax=ax, legend=len(y) > 1)
    elif kind == "barh":
        data.iloc[::-1].plot.barh(x=x, y=y, ax=ax, legend=len(y) > 1)
    elif kind == "pie":
        ax.pie(data[y[0]], labels=data[x].astype(str), autopct="%1.1f%%", startangle=90, counterclock=False)
        ax.axis("equal")
    elif kind == "scatter":
        ax.scatter(data[x], data[y[0]], s=14)
        ax.set_xlabel(x)
        ax.set_ylabel(y[0])
    ax.set_title(title)
    if kind in {"line", "bar"}:
        ax.set_xlabel(x)
        if len(y) == 1:
            ax.set_ylabel(y[0])
        if kind == "line" and len(y) > 1:
            ax.legend()
        ax.tick_params(axis="x", labelrotation=45 if kind == "bar" else 30)
    if kind != "pie":
        ax.grid(alpha=0.3)
        try:  # 큰 수가 1e6 지수표기로 바뀌지 않게(도민 가독성)
            ax.ticklabel_format(axis="x" if kind == "barh" else "y", style="plain", useOffset=False)
        except AttributeError:
            pass  # 범주·날짜 축은 지수표기 대상이 아니다
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path
