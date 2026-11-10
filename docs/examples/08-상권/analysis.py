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
# 출처: 제주특별자치도_주제3_상권분석을 위한 유동인구에 따른 카드 매출액 변화 데이터 활용_매쉬업결과 (https://jejudatahub.net/data/view/data/748)
_raw, _info = hub_file(CLIENT, 748, '제주특별자치도_주제3_상권분석을 위한 유동인구에 따른 카드 매출액 변화 데이터 활용_매쉬업결과_20(수정).csv', CACHE)
D1 = parse_bytes(_raw, _info['fileName'])
D1 = normalize(D1)

# --- R1 ---
# 2020년 읍면동별 카페(비알콜 음료점업) 카드매출 합계 순위 확인
df = D1.copy()
df = df[df['업종명'] == '비알콜 음료점업']
g = df.groupby(['읍면동명'], dropna=False)
df = pd.concat([g['이용금액'].sum().rename('이용금액'), g['이용자수'].sum().rename('이용자수')], axis=1).reset_index()
df = df.sort_values(['이용금액'], ascending=False)
R1 = df

# --- R2 ---
# 애월읍 카페 매출의 2020년 월별 추이와 유동인구 확인
df = D1.copy()
df = df[df['읍면동명'] == '애월읍']
df = df[df['업종명'] == '비알콜 음료점업']
g = df.groupby(['년월'], dropna=False)
df = pd.concat([g['이용금액'].sum().rename('이용금액'), g['이용자수'].sum().rename('이용자수'), g['방문인구'].mean().rename('방문인구'), g['거주인구'].mean().rename('거주인구')], axis=1).reset_index()
df = df.sort_values(['년월'], ascending=True)
R2 = df

# --- R4 ---
# 제주 전체 카페 매출에서 애월읍이 차지하는 비중
df = R1.copy()
df['전체대비비중'] = df['이용금액'] / df['이용금액'].sum() * 100
R4 = df

# --- D3 ---
# 출처: 제주특별자치도_주제1_제주 예비창업자를 위한 업종별 카드 매출과 매장수 데이터 활용_매쉬업 결과 (https://jejudatahub.net/data/view/data/746)
_raw, _info = hub_file(CLIENT, 746, '제주특별자치도_주제1_제주 예비창업자를 위한 업종별 카드 매출과 매장수 데이터 활용_매쉬업결과_21.csv', CACHE)
D3 = parse_bytes(_raw, _info['fileName'])
D3 = normalize(D3)

# --- R5 ---
# 2021년 1~5월 애월읍 카페 매출의 도민 vs 관광객 구성과 매장수 확인
df = D3.copy()
df = df[df['업종명'] == '비알콜 음료점업']
df = df[df['읍면동명'] == '애월읍']
g = df.groupby(['관광구분'], dropna=False)
df = pd.concat([g['매장수'].mean().rename('매장수'), g['이용금액'].sum().rename('이용금액')], axis=1).reset_index()
df['매출비중'] = df['이용금액'] / df['이용금액'].sum() * 100
R5 = df

# --- R6 ---
# 2021년 1~5월 읍면 지역 중 카페 매출 순위에서 애월읍 위치 확인
df = D3.copy()
df = df[df['업종명'] == '비알콜 음료점업']
g = df.groupby(['읍면동명'], dropna=False)
df = pd.concat([g['이용금액'].sum().rename('이용금액')], axis=1).reset_index()
df = df.sort_values(['이용금액'], ascending=False)
R6 = df

# --- R8 ---
# 2021년 1~5월 애월읍 카페 매출의 월별 추이 (계절성 확인)
df = D3.copy()
df = df[df['업종명'] == '비알콜 음료점업']
df = df[df['읍면동명'] == '애월읍']
g = df.groupby(['년월'], dropna=False)
df = pd.concat([g['이용금액'].sum().rename('이용금액')], axis=1).reset_index()
df = df.sort_values(['년월'], ascending=True)
R8 = df

# --- R12 ---
# 2021년 5월 매출이 1월의 몇 배인지 계산
df = R8.copy()
df['1월대비배수'] = df['이용금액'] / 40321560.0
R12 = df

# --- R9 ---
# 읍면동별 카페 이용자 1인당 결제액 비교에서 애월읍 위치 확인
df = R1.copy()
df['이용자1인당결제액'] = df['이용금액'] / df['이용자수']
df = df.sort_values(['이용자1인당결제액'], ascending=False)
df = df.head(10)
R9 = df
print('R1'); print(R1.head(30).to_string())
print('R2'); print(R2.head(30).to_string())
print('R4'); print(R4.head(30).to_string())
print('R5'); print(R5.head(30).to_string())
print('R6'); print(R6.head(30).to_string())
print('R8'); print(R8.head(30).to_string())
print('R12'); print(R12.head(30).to_string())
print('R9'); print(R9.head(30).to_string())
