import pandas as pd

from jeju_data_agent.verify import verify


def _status(answer, df):
    return {c.text: c.verified for c in verify(answer, [df])}


def test_rounded_and_scaled_values_match_table():
    df = pd.DataFrame({"품종": ["깐마늘"], "평균가격": [8292.75], "비중": [23.456], "이용자": [36210]})
    got = _status("평균 8,292.8원이고 비중은 23.5%, 이용자는 약 3.6만 명입니다.", df)
    assert got == {"8,292.8": True, "23.5%": True, "3.6만": True}


def test_compound_korean_numerals_read_as_one_value():
    df = pd.DataFrame({"생산량": [404233.0], "면적": [10244.1]})
    got = _status("2022년 40만 4,233톤, 면적은 1만 244.1ha였습니다.", df)
    assert got == {"40만 4,233": True, "1만 244.1": True}


def test_eok_answer_matches_million_won_column():
    df = pd.DataFrame({"조수입(백만원)": [106434]})
    assert _status("월동무 조수입은 약 1,064억 원입니다.", df) == {"1,064억": True}


def test_eok_man_compound_rounds_at_man():
    df = pd.DataFrame({"매출": [597_063_120]})
    assert _status("카드매출 5억 9,706만 원", df) == {"5억 9,706만": True}


def test_invented_number_is_flagged():
    df = pd.DataFrame({"이용자": [36210]})
    got = _status("이용자는 41,000명으로 늘었습니다.", df)
    assert got == {"41,000": False}


def test_route_numbers_and_dotted_dates_are_not_values():
    df = pd.DataFrame({"승차": [401438]})
    got = _status("365-22번 노선은 2019.1.1~2025.10.19 기간 401,438명이 탔습니다.", df)
    assert got == {"401,438": True}


def test_years_dates_and_ranks_are_not_checked():
    df = pd.DataFrame({"x": [1.0]})
    assert verify("2024년 3월 기준 1위 정류소, 20240102 자료", [df]) == []


def test_counts_with_place_units_are_checked_but_question_numbers_are_not():
    df = pd.DataFrame({"업종": ["카페"], "점포수": [228]})
    got = {c.text: c.verified for c in verify("상위 20곳 중 카페는 228곳, 약국은 303개입니다.", [df], [20.0])}
    assert got == {"20": True, "228": True, "303": False}
