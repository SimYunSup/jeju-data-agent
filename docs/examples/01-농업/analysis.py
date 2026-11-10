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
# 출처: 서귀포시 감귤 종류별 면적 및 생산량 추이(연간) (https://jejudatahub.net/data/view/data/1294)
_raw, _info = hub_file(CLIENT, 1294, '제주특별자치도 서귀포시_감귤 생산 정보_20240513.csv', CACHE)
D1 = parse_bytes(_raw, _info['fileName'])
D1 = normalize(D1)

# --- R1 ---
# 서귀포시 전체 감귤 종류별 연도별 생산량 합계 추이
df = D1.copy()
df = df[df['구분'] == '생산량']
g = df.groupby(['연도'], dropna=False)
df = pd.concat([g['노지온주(극조생)'].sum().rename('노지온주(극조생)'), g['노지온주(조생)'].sum().rename('노지온주(조생)'), g['노지온주(보통)'].sum().rename('노지온주(보통)'), g['하우스감귤(조기출하)'].sum().rename('하우스감귤(조기출하)'), g['비가림(월동)감귤'].sum().rename('비가림(월동)감귤'), g['만감류(시설)'].sum().rename('만감류(시설)'), g['만감류(노지)'].sum().rename('만감류(노지)'), g['읍면동'].nunique().rename('읍면동')], axis=1).reset_index()
df = df.rename(columns={'읍면동': '읍면동수'})
R1 = df

# --- R2 ---
# 종류별 2012년 대비 2022년 생산량 증감률(10년)
df = R1.copy()
df['극조생_증감률'] = df['노지온주(극조생)'].pct_change(periods=10) * 100
df['조생_증감률'] = df['노지온주(조생)'].pct_change(periods=10) * 100
df['보통_증감률'] = df['노지온주(보통)'].pct_change(periods=10) * 100
df['하우스_증감률'] = df['하우스감귤(조기출하)'].pct_change(periods=10) * 100
df['비가림_증감률'] = df['비가림(월동)감귤'].pct_change(periods=10) * 100
df['만감시설_증감률'] = df['만감류(시설)'].pct_change(periods=10) * 100
df['만감노지_증감률'] = df['만감류(노지)'].pct_change(periods=10) * 100
df = df[df['연도'] == 2022.0]
R2 = df

# --- R3 ---
# 연도별 전체 생산량과 종류별 비중 변화
df = R1.copy()
df['합계'] = df[['노지온주(극조생)', '노지온주(조생)', '노지온주(보통)', '하우스감귤(조기출하)', '비가림(월동)감귤', '만감류(시설)', '만감류(노지)']].sum(axis=1)
df['조생비중'] = df['노지온주(조생)'] / df['합계'] * 100
df['만감시설비중'] = df['만감류(시설)'] / df['합계'] * 100
df['극조생비중'] = df['노지온주(극조생)'] / df['합계'] * 100
df['비가림비중'] = df['비가림(월동)감귤'] / df['합계'] * 100
df = df[['연도', '합계', '조생비중', '극조생비중', '비가림비중', '만감시설비중']]
R3 = df
print('R1'); print(R1.head(30).to_string())
print('R2'); print(R2.head(30).to_string())
print('R3'); print(R3.head(30).to_string())
