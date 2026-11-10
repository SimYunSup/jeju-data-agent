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
# 출처: 농산물 품종별 일일 거래 통계 (https://jejudatahub.net/data/view/data/1361)
rows, total = CLIENT.call_api('13t6aat1at6166111Dtt1taa1ta1661t', {'startDate': '20240101', 'endDate': '20251031', 'cultivar': '깐마늘'}, 20000)
D1 = pd.DataFrame(rows)
D1 = normalize(D1)

# --- R1 ---
# 깐마늘 월별 평균 도매가격 및 거래 규모 확인(2024 vs 2025)
df = D1.copy()
df['년'] = df['baseDate'].dt.year
df['월'] = df['baseDate'].dt.month
g = df.groupby(['년', '월'], dropna=False)
df = pd.concat([g['averagePrice'].mean().rename('averagePrice'), g['transactionVolume'].sum().rename('transactionVolume'), g['transactionAmount'].sum().rename('transactionAmount'), g['baseDate'].count().rename('baseDate')], axis=1).reset_index()
df = df.rename(columns={'averagePrice': '평균도매가격(원/kg)', 'transactionVolume': '거래량합계(톤)', 'transactionAmount': '거래금액합계(백만원)', 'baseDate': '거래일수'})
R1 = df

# --- R2 ---
# 2025년 1~10월 vs 2024년 동기 평균 도매가격 비교 및 증감률
df = R1.copy()
df = df[df['월'] <= 10.0]
g = df.groupby(['년'], dropna=False)
df = pd.concat([g['평균도매가격(원/kg)'].mean().rename('평균도매가격(원/kg)'), g['거래량합계(톤)'].sum().rename('거래량합계(톤)'), g['거래금액합계(백만원)'].sum().rename('거래금액합계(백만원)')], axis=1).reset_index()
df['전년대비증감률(%)'] = df['평균도매가격(원/kg)'].pct_change(periods=1) * 100
R2 = df

# --- R3 ---
# 2024년과 2025년 같은 달끼리 월별 가격 비교 및 차이·증감률
df = R1.copy()
df = df[df['월'].isin([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])]
df = df.pivot_table(index='월', columns='년', values='평균도매가격(원/kg)', aggfunc='mean').reset_index()
df.columns = [str(c) for c in df.columns]
df = df.rename(columns={'2024': '2024년(원/kg)', '2025': '2025년(원/kg)'})
df['차이(원/kg)'] = df['2025년(원/kg)'] - df['2024년(원/kg)']
df['증감률(%)'] = df['차이(원/kg)'] / df['2024년(원/kg)'] * 100
R3 = df
print('D1'); print(D1.head(30).to_string())
print('R1'); print(R1.head(30).to_string())
print('R2'); print(R2.head(30).to_string())
print('R3'); print(R3.head(30).to_string())
