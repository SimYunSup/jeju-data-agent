"""제주 데이터 길잡이가 만든 분석을 그대로 다시 실행하는 스크립트.

실행: uv run python analysis.py   (원본을 제주데이터허브에서 다시 받는다. API 데이터는 .env의 JEJU_DATAHUB_PROJECT_KEY 필요)
"""
import pandas as pd
from jeju_data_agent.config import Settings
from jeju_data_agent.datahub import DataHubClient
from jeju_data_agent.datasets import hub_file, normalize, parse_bytes

SETTINGS = Settings.load()
PROJECT_KEY = SETTINGS.jeju_project_key
CLIENT = DataHubClient(PROJECT_KEY)
CACHE = SETTINGS.data_dir / "cache"  # 이미 받은 원본이 있으면 재사용, 없으면 데이터허브에서 받는다

# --- D1 ---
# 출처: 국가별 입도객 현황 (https://jejudatahub.net/data/view/data/582)
rows, total = CLIENT.call_api('tbata552bat15Daa585t52D5a5t818t2', {' startDate': '202108', ' endDate': '202507', 'startDate': '202108', 'endDate': '202507'}, 20000)
D1 = pd.DataFrame(rows)
D1 = normalize(D1)

# --- R1 ---
# 2021-08~2025-07 전체 기간 국가별 입도객 누적 순위와 비중
df = D1.copy()
g = df.groupby(['nationality'], dropna=False)
df = pd.concat([g['visitorCnt'].sum().rename('visitorCnt')], axis=1).reset_index()
df = df.sort_values(['visitorCnt'], ascending=False)
df['visitorCnt_비중(%)'] = df['visitorCnt'] / df['visitorCnt'].sum() * 100
R1 = df

# --- R2 ---
# 최근 12개월(2024-08~2025-07) 국가별 입도객 순위와 비중
df = D1.copy()
df = df[df['dtYearMonth'] >= pd.Timestamp('2024-08-01')]
g = df.groupby(['nationality'], dropna=False)
df = pd.concat([g['visitorCnt'].sum().rename('visitorCnt')], axis=1).reset_index()
df = df.sort_values(['visitorCnt'], ascending=False)
df['visitorCnt_비중(%)'] = df['visitorCnt'] / df['visitorCnt'].sum() * 100
R2 = df

# --- R3 ---
# 월별 추이(상위 3개국)로 최근 흐름 확인
df = D1.copy()
df = df[df['nationality'].isin(['중국', '대만', '일본'])]
g = df.groupby([*['nationality'], pd.Grouper(key='dtYearMonth', freq='ME')])
df = pd.concat([g['visitorCnt'].sum()], axis=1).reset_index()
R3 = df
print('R1'); print(R1.head(30).to_string())
print('R2'); print(R2.head(30).to_string())
print('R3'); print(R3.head(30).to_string())
