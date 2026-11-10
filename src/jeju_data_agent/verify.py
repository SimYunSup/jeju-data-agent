"""답변 속 숫자가 실제 분석 결과에서 나온 값인지 대조한다(환각 수치 차단).

LLM이 쓴 답변의 숫자를 뽑아, 이번 세션에서 불러오거나 계산한 표의 모든 숫자 값과 비교한다.
표에 없는 숫자는 '검증 안 됨'으로 표시해 사용자가 바로 알 수 있게 한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

# 1,234.5 / 12.3% / 3.6만 / 1.2억 같은 표기를 잡는다.
# 365-22(노선번호)·2019.1.1(날짜)처럼 다른 숫자와 붙은 코드는 값이 아니므로 앞뒤 경계에서 걸러낸다.
_NUM = re.compile(r"(?<![\w.\-])(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)(?![\d]|[-.]\d)(\s*)(%p|%|만|억|천)?")
_TABLE_UNITS = (1.0, 1e3, 1e4, 1e6)  # 표 열의 단위: 그대로·천·만·백만
_SCALE = {"만": 1e4, "억": 1e8, "천": 1e3}
# 한글 자릿수를 섞은 한 개의 수: 5억 9,706만 / 1억 2,300만 4,000 / 40만 4,233 / 1만 244.1
_END = r"(?![\d,.]|\s*[만억%])"
_COMPOUND = re.compile(
    r"(?<![\w.])(?:(\d[\d,]*)\s*억\s*(\d[\d,]*)\s*만(?:\s*(\d[\d,]*(?:\.\d+)?)" + _END + r")?"
    r"|(\d[\d,]*)\s*(억|만)\s*(\d[\d,]*(?:\.\d+)?)" + _END + ")")
# 날짜·연도·순위처럼 계산값이 아닌 숫자 문맥(뒤에 붙는 단어). '228곳', '303개', '1,234건'은 집계값이므로 검증한다.
_NON_VALUE_SUFFIX = re.compile(r"^\s*(년|개월|월|일|위|가지|단계|번째|시|분|호|차|주|분기|세|대|명의?\s*사용자|쪽|페이지)")


@dataclass
class Check:
    text: str
    value: float
    verified: bool


def _compound(answer: str) -> tuple[list[tuple[str, float, str]], str]:
    """한글 자릿수 혼합 표기를 하나의 값으로 읽고, 그 부분을 지운 텍스트를 돌려준다."""
    found = []

    def take(m: re.Match) -> str:
        def n(s: str | None) -> float:
            return float(s.replace(",", "")) if s else 0.0
        if m.group(1):  # N억 M만 [K]
            value = n(m.group(1)) * 1e8 + n(m.group(2)) * 1e4 + n(m.group(3))
            unit = "" if m.group(3) else "만"  # 만 단위까지만 적었으면 만 단위로 반올림 비교
        else:  # N만 K / N억 K
            value = n(m.group(4)) * _SCALE[m.group(5)] + n(m.group(6))
            unit = ""
        found.append((m.group(0).strip(), value, unit))
        return " " * len(m.group(0))

    return found, _COMPOUND.sub(take, answer)


def extract_numbers(answer: str) -> list[tuple[str, float, str]]:
    found, answer = _compound(answer)
    for m in _NUM.finditer(answer):
        raw, unit = m.group(1), m.group(3) or ""
        tail = answer[m.end():m.end() + 8]
        if not unit and _NON_VALUE_SUFFIX.match(tail):
            continue
        value = float(raw.replace(",", ""))
        if not unit and value.is_integer() and abs(value) <= 12:
            continue  # 작은 정수(3곳, 5위 등)는 서술용이 대부분
        if not unit and 1900 <= value <= 2100 and value.is_integer():
            continue  # 연도
        if not unit and re.fullmatch(r"\d{8}", raw):
            continue  # YYYYMMDD
        found.append((m.group(0).strip(), value * _SCALE.get(unit, 1.0), unit))
    return found


def table_numbers(frames: list[pd.DataFrame]) -> np.ndarray:
    parts = []
    for df in frames:
        for col in df.columns:
            s = df[col]
            if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
                parts.append(pd.unique(s.dropna().to_numpy(dtype=float)))
        parts.append(np.array([float(len(df))]))
    if not parts:
        return np.array([])
    values = np.unique(np.concatenate(parts))
    return values[np.isfinite(values)]


def numbers_in_text(text: str) -> list[float]:
    """도구가 보여준 메타데이터(파일 크기·전체 건수 등)에서 숫자를 모은다."""
    return [float(m.group(1).replace(",", "")) for m in _NUM.finditer(text)]


def _decimals(text: str) -> int:
    core = re.sub(r"[^\d.]", "", text)
    return len(core.split(".")[1]) if "." in core else 0


def _matches(target: float, text: str, unit: str, candidates: np.ndarray) -> bool:
    if candidates.size == 0:
        return False
    dec = _decimals(text)
    if unit in _SCALE:
        # 3.6만 → 36,000: 표시 자릿수만큼 반올림해 같으면 일치.
        # 표가 천원·만원·백만원 단위 열(예: 조수입(백만원) 106,434 → 1,064억)일 수 있어 그 배율도 함께 본다.
        scale = _SCALE[unit]
        want = round(target / scale, dec)
        return any(bool(np.any(np.round(candidates * table_unit / scale, dec) == want))
                   for table_unit in _TABLE_UNITS)
    if np.any(np.round(candidates, dec) == round(target, dec)):
        return True
    if abs(target) >= 100:  # 큰 수를 반올림해 적은 경우(예: 1,234,567 → 1,235,000)
        nz = candidates[candidates != 0]
        return bool(np.any(np.abs(nz - target) / np.abs(nz) <= 0.005))
    return False


def verify(answer: str, frames: list[pd.DataFrame], observed: list[float] | None = None) -> list[Check]:
    candidates = table_numbers(frames)
    if observed:
        candidates = np.concatenate([candidates, np.array(observed, dtype=float)])
    # 부호는 '–33.6%(감소)'처럼 글로 표현되는 경우가 많아 크기로 대조한다.
    candidates = np.unique(np.abs(candidates))
    return [Check(text, value, _matches(abs(value), text, unit, candidates))
            for text, value, unit in extract_numbers(answer)]
