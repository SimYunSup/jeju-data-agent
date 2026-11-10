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
# 출처: 제주 채소류 재배 현황 (https://jejudatahub.net/data/view/data/981)
_raw, _info = hub_file(CLIENT, 981, '제주채소류재배현황.csv', CACHE)
D1 = parse_bytes(_raw, _info['fileName'])
D1 = normalize(D1)

# --- R1 ---
# 2020-21 시즌 제주 노지채소 작물별 재배면적·조수입 순위와 비중
df = D1.copy()
df = df[df['채소구분대분류'] == '노지채소']
df = df[df['연산'] == '20-21']
df = df.sort_values(['면적(ha)'], ascending=False)
df['면적비중(%)'] = df['면적(ha)'] / df['면적(ha)'].sum() * 100
df['조수입비중(%)'] = df['조수입(백만원)'] / df['조수입(백만원)'].sum() * 100
R1 = df

# --- R2 ---
# 노지채소 전체 면적·조수입 합계를 시즌별로 확인
df = D1.copy()
df = df[df['채소구분대분류'] == '노지채소']
g = df.groupby(['연산'], dropna=False)
df = pd.concat([g['면적(ha)'].sum().rename('면적(ha)'), g['조수입(백만원)'].sum().rename('조수입(백만원)')], axis=1).reset_index()
R2 = df

# --- R3 ---
# 작물별 ha당 조수입 계산 및 조수입 순 정렬
df = R1.copy()
df['ha당조수입(백만원)'] = df['조수입(백만원)'] / df['면적(ha)']
df = df.sort_values(['조수입(백만원)'], ascending=False)
R3 = df
print('R1'); print(R1.head(30).to_string())
print('R2'); print(R2.head(30).to_string())
print('R3'); print(R3.head(30).to_string())
