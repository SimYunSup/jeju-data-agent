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
# 출처: 교통사고 다발지역 정보 (https://jejudatahub.net/data/view/data/863)
rows, total = CLIENT.call_api('36333aD6tba8aa1D6D1aaab8D1aa6ba8', {}, 20000)
D1 = pd.DataFrame(rows)
D1 = normalize(D1)

# --- R1 ---
# 제주시/서귀포시 6개 다발지점 구역별 사고 규모 확인
df = D1.copy()
g = df.groupby(['sidoSigungu'], dropna=False)
df = pd.concat([g['occurrenceCount'].sum().rename('occurrenceCount'), g['deathInjuryCount'].sum().rename('deathInjuryCount'), g['seriouslyInjuryCount'].sum().rename('seriouslyInjuryCount'), g.size().rename('건수')], axis=1).reset_index()
df = df.sort_values(['occurrenceCount'], ascending=False)
R1 = df

# --- R3 ---
# 제주시 권역 합계
df = D1.copy()
df = df[df['sidoSigungu'].astype(str).str.contains('제주시', regex=False)]
df['권역'] = df['occurrenceCount'] * 0.0
g = df.groupby(['권역'], dropna=False)
df = pd.concat([g['occurrenceCount'].sum().rename('occurrenceCount'), g['deathInjuryCount'].sum().rename('deathInjuryCount'), g['deathCount'].sum().rename('deathCount'), g['seriouslyInjuryCount'].sum().rename('seriouslyInjuryCount'), g.size().rename('건수')], axis=1).reset_index()
R3 = df

# --- R4 ---
# 서귀포시 권역 합계
df = D1.copy()
df = df[df['sidoSigungu'].astype(str).str.contains('서귀포시', regex=False)]
df['권역'] = df['occurrenceCount'] * 0.0
g = df.groupby(['권역'], dropna=False)
df = pd.concat([g['occurrenceCount'].sum().rename('occurrenceCount'), g['deathInjuryCount'].sum().rename('deathInjuryCount'), g['deathCount'].sum().rename('deathCount'), g['seriouslyInjuryCount'].sum().rename('seriouslyInjuryCount'), g.size().rename('건수')], axis=1).reset_index()
R4 = df

# --- R5 ---
# 사고 건수 상위 6개 지점 + 중상자 많은 지점 확인
df = D1.copy()
g = df.groupby(['occurrencePlace'], dropna=False)
df = pd.concat([g['occurrenceCount'].sum().rename('occurrenceCount'), g['deathInjuryCount'].sum().rename('deathInjuryCount'), g['deathCount'].sum().rename('deathCount'), g['seriouslyInjuryCount'].sum().rename('seriouslyInjuryCount'), g.size().rename('건수')], axis=1).reset_index()
df = df.sort_values(['occurrenceCount'], ascending=False)
df = df.head(6)
R5 = df
print('R1'); print(R1.head(30).to_string())
print('R3'); print(R3.head(30).to_string())
print('R4'); print(R4.head(30).to_string())
print('R5'); print(R5.head(30).to_string())
