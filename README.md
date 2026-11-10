# 🍊 제주 데이터 길잡이 (Jeju Data Navigator)

제주빅데이터센터를 찾은 도민이 **평소 말투로 질문하면**, AI Agent가 제주데이터허브(1,259종)와
제주빅데이터센터(70종) 데이터 목록에서 알맞은 데이터를 **스스로 찾아 → 불러오고 → 분석하고 → 차트와
쉬운 설명으로 답하는** 서비스입니다. 답에 쓴 모든 숫자는 실제 계산 결과와 자동 대조되고,
분석은 그대로 다시 실행할 수 있는 파이썬 코드로 함께 저장됩니다.

```mermaid
flowchart LR
  Q[도민 질문] --> S[데이터 찾기<br/>카탈로그 1,329종 검색]
  S --> I[데이터 살펴보기<br/>열·기간·요청 변수]
  I --> L[불러오기<br/>FILE·API·센터 파일]
  L --> A[분석<br/>선언형 연산 → pandas]
  A --> C[차트]
  A --> F[답변]
  C --> F
  F --> V[수치 자동 검증]
  V --> O[보고서·근거 표·재현 코드]
```

## 빠른 시작

| 환경 | 실행 |
|---|---|
| Windows(센터 PC) | `run.bat` 더블클릭 → 처음 한 번 `.env` 설정 → 브라우저 `http://localhost:8501` |
| macOS/Linux | `./run.sh` |
| 명령줄 | `uv run jeju-data-agent ask "서귀포시 감귤 생산량 추이 알려줘"` |

필요한 것: 인터넷 연결, AI 모델 하나(`.env`의 `LLM_*`).
제주데이터허브 **파일 데이터 670여 종은 키 없이** 바로 분석합니다.
API 데이터(93종)는 본인 프로젝트 키(`JEJU_DATAHUB_PROJECT_KEY`)가 있으면 함께 씁니다.

## 심사·평가용 실행 방법

| 방법 | 준비 | `.env` |
|---|---|---|
| A. 평가용 AI 키(권장) | 제출 ZIP의 [사용자 매뉴얼](docs/사용자_매뉴얼.md) 3장 「심사·평가용 AI 설정」의 세 줄을 붙여 넣기. 개발·실측과 같은 모델이며 평가 후 폐기 | `LLM_BASE_URL`·`LLM_MODEL`·`LLM_API_KEY` |
| B. 다른 AI 키 | OpenAI 호환 Chat Completions + 도구 호출을 지원하는 아무 제공사 | 예시는 `.env.example` |
| C. 로컬 AI(키 없음) | 센터 PC 사양(GTX 1060 6GB·RAM 32GB)에서 `setup_local_ai.bat` 더블클릭 → Ollama 설치·컨텍스트 16K·`qwen3.5:4b` 내려받기·`.env` 설정까지 자동 | 스크립트가 채움 |

C는 인터넷 AI 없이 돌아가지만 4B 모델이라 데이터 선택·설명 품질과 속도가 A보다 낮습니다(실측: [결과 설명자료](docs/결과_설명자료.md) 4장).
어느 방법이든 계산은 분석 엔진이 하고 답변 숫자는 자동 검증되므로, 모델이 달라도 표의 숫자는 같습니다.

자세한 설치·사용법: [docs/사용자_매뉴얼.md](docs/사용자_매뉴얼.md)

## 구성

| 경로 | 역할 |
|---|---|
| `src/jeju_data_agent/agent.py` | 도구 호출 Agent 루프(검색→확인→적재→분석→차트→답변), 도구 정의 |
| `src/jeju_data_agent/resources/system_prompt.md` | Agent 지시문(Prompt) |
| `src/jeju_data_agent/catalog.py` | 데이터허브·센터 카탈로그 수집, 한국어 2-gram BM25 검색 |
| `src/jeju_data_agent/datahub.py` | 제주데이터허브 메타데이터·파일·API(프로젝트 키) 클라이언트 |
| `src/jeju_data_agent/datasets.py` | 데이터 적재·형 변환·출처 기록·센터 로컬 파일 |
| `src/jeju_data_agent/ops.py` | 선언형 분석 연산 15종 + 동일 결과 pandas 코드 생성 |
| `src/jeju_data_agent/verify.py` | 답변 속 수치 ↔ 계산 결과 자동 대조 |
| `src/jeju_data_agent/report.py` | 답변별 보고서·근거 표(CSV)·차트·재현 코드·출처(JSON) 내보내기 |
| `src/jeju_data_agent/app.py` | Streamlit 웹 화면 |
| `src/jeju_data_agent/resources/catalog_snapshot.json` | 오프라인용 카탈로그 스냅샷(공개 메타데이터) |
| `tests/` | 분석 엔진·수치 검증 단위 테스트(`uv run pytest`) |
| `docs/` | 사용자 매뉴얼, 데이터 활용 명세, 결과 설명자료 |

## 사용 모델·외부 서비스

- AI 모델: OpenAI 호환 Chat Completions + 도구 호출. 개발·검증은 `deepseek-ai/deepseek-v4.1-flash-1017`(Deploy API)로 했고,
  모델 서버는 `.env`만 바꾸면 OpenAI·Gemini·로컬 Ollama 등으로 교체됩니다.
- 데이터: 제주데이터허브(jejudatahub.net) 공개 메타데이터·첨부 파일·API, 제주빅데이터센터 방문 데이터(센터 PC).
- 오픈소스: pandas, matplotlib, Streamlit, httpx, openai-python, openpyxl (전체 목록·버전은 `uv.lock`).
- 생성형 AI 활용 범위: 코드 작성 보조에 AI 코딩 도구를 사용했습니다. 실행 시 분석 판단·설명 생성에 위 AI 모델을 사용합니다.
