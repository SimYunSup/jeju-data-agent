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
# 출처: 이용자 유형별 버스정류소 이용 인원 현황 (https://jejudatahub.net/data/view/data/743)
_raw, _info = hub_file(CLIENT, 743, '이용자유형별버스정류소이용인원현황.csv', CACHE)
D1 = parse_bytes(_raw, _info['fileName'])
D1 = normalize(D1)

# --- R3 ---
# 2025년 1~10월 정류소별 이용 인원과 전체 대비 비중 상위 10곳
df = D1.copy()
df = df[df['base_date'].between(*[pd.Timestamp('2025-01-01'), pd.Timestamp('2025-10-25')])]
g = df.groupby(['station_name'], dropna=False)
df = pd.concat([g['user_count'].sum().rename('user_count')], axis=1).reset_index()
df['비중(%)'] = df['user_count'] / df['user_count'].sum() * 100
df = df.sort_values(['user_count'], ascending=False)
df = df.head(10)
R3 = df

# --- R4 ---
# 2024년 한 해 정류소별 이용 인원 상위 10곳(순위 안정성 확인)
df = D1.copy()
df = df[df['base_date'].between(*[pd.Timestamp('2024-01-01'), pd.Timestamp('2024-12-31')])]
g = df.groupby(['station_name'], dropna=False)
df = pd.concat([g['user_count'].sum().rename('user_count')], axis=1).reset_index()
df = df.sort_values(['user_count'], ascending=False)
df = df.head(10)
R4 = df

# --- R2 ---
# 전체 정류소 수와 총 이용 인원(2025년 1~10월) 파악
df = D1.copy()
df = df[df['base_date'].between(*[pd.Timestamp('2025-01-01'), pd.Timestamp('2025-10-25')])]
g = df.groupby(['station_name'], dropna=False)
df = pd.concat([g['user_count'].sum().rename('user_count')], axis=1).reset_index()
df = df[['user_count']].describe().T.reset_index()
R2 = df

# --- R8 ---
# 상위 10곳 이용 인원 합계와 전체 정류소 이용 인원 합계 비교
df = D1.copy()
df = df[df['base_date'].between(*[pd.Timestamp('2025-01-01'), pd.Timestamp('2025-10-25')])]
g = df.groupby(['station_name'], dropna=False)
df = pd.concat([g['user_count'].sum().rename('user_count')], axis=1).reset_index()
df = df.sort_values(['user_count'], ascending=False)
df = df.head(10)
df['구분'] = df['user_count'] * 0.0
g = df.groupby(['구분'], dropna=False)
df = pd.concat([g['user_count'].sum().rename('user_count')], axis=1).reset_index()
R8 = df

# --- R10 ---
# 상위10 합계 대비 전체 합계 비중 계산
df = R8.copy()
df = df.rename(columns={'user_count': '상위10_합계'})
df['상위10비중(%)'] = df['상위10_합계'] / 18059576.0 * 100
R10 = df
print('R3'); print(R3.head(30).to_string())
print('R4'); print(R4.head(30).to_string())
print('R2'); print(R2.head(30).to_string())
print('R10'); print(R10.head(30).to_string())
