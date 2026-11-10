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
# 출처: 전기자동차 충전소 정보 (https://jejudatahub.net/data/view/data/862)
rows, total = CLIENT.call_api('atDab6t8218btaa122b26DDtbatD86t1', {}, 20000)
D1 = pd.DataFrame(rows)
D1 = normalize(D1)

# --- R1 ---
# 충전소 데이터의 좌표 범위와 전체 건수 확인, 시군구 구분 가능성 점검
df = D1.copy()
df = df[['latitude', 'longitude', 'chargerCount', 'quickChargerCount']].describe().T.reset_index()
R1 = df
print('D1'); print(D1.head(30).to_string())
print('R1'); print(R1.head(30).to_string())
