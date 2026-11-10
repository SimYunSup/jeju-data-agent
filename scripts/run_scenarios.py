"""대표 질문 묶음을 실제로 돌려 성공률·소요 시간·수치 검증 결과를 기록한다(결과 설명자료의 근거).

실행: uv run python scripts/run_scenarios.py [출력 JSON 경로]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from jeju_data_agent.agent import Session
from jeju_data_agent.catalog import load_catalog
from jeju_data_agent.config import Settings
from jeju_data_agent.datahub import DataHubClient
from jeju_data_agent.report import export

SCENARIOS = [
    ("농업", "서귀포시 감귤 종류별로 생산량이 어떻게 변해왔어?"),
    ("교통", "제주에서 버스 이용객이 가장 많은 정류소 10곳은 어디야?"),
    ("농업", "제주 노지채소 중 재배 면적이 넓은 작물과 조수입은 어떻게 돼?"),
    ("관광", "외국인 입도객은 어느 나라에서 가장 많이 와?"),
    ("가격", "요즘 깐마늘 도매 가격이 작년보다 올랐어?"),
    ("생활", "제주시와 서귀포시에 전기차 충전소가 각각 몇 곳 있어?"),
    ("안전", "제주에서 교통사고가 자주 나는 지역은 어디야?"),
    ("상권", "애월읍에 카페를 차리면 손님이 많을까?"),
]


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/scenario_results.json")
    settings = Settings.load()
    catalog = load_catalog(settings.data_dir, DataHubClient())
    results = []
    for domain, question in SCENARIOS:
        session = Session.create(settings, catalog)
        t0 = time.time()
        try:
            answer = session.ask(question)
            folder = export(answer, session)
            row = {
                "domain": domain, "question": question, "completed": answer.completed,
                "seconds": round(time.time() - t0, 1),
                "tool_calls": len(answer.trace), "tool_errors": sum(not s.ok for s in answer.trace),
                "datasets": sorted({session.store.tables[h].provenance.title for h in session.store.tables
                                    if h.startswith("D")}),
                "charts": len(answer.charts), "numbers": len(answer.checks),
                "unverified": [c.text for c in answer.unverified],
                "output": str(folder), "answer": answer.markdown,
            }
        except Exception as exc:  # 시나리오 하나가 실패해도 나머지는 계속 잰다
            row = {"domain": domain, "question": question, "completed": False,
                   "seconds": round(time.time() - t0, 1), "error": f"{type(exc).__name__}: {exc}"}
        results.append(row)
        print(json.dumps({k: v for k, v in row.items() if k != "answer"}, ensure_ascii=False), flush=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    access = "FILE + API(프로젝트 키)" if settings.jeju_project_key else "API 키 없이 FILE 데이터만"
    out_path.write_text(json.dumps({"model": settings.llm_model, "data_access": access,
                                    "run_at": time.strftime("%Y-%m-%d %H:%M"),
                                    "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
