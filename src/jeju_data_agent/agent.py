"""질문 → (데이터 검색 → 확인 → 적재 → 분석 → 차트 → 답변) 을 스스로 수행하는 AI Agent.

LLM은 OpenAI 호환 Chat Completions + 도구 호출만 사용하므로 OpenAI·Gemini(OpenAI 호환)·
Ollama·vLLM 등 어느 서버든 LLM_BASE_URL/LLM_MODEL만 바꿔 쓸 수 있다.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from openai import OpenAI

from . import charts
from .catalog import Catalog
from .config import Settings
from .datahub import DataHubClient
from .datasets import DatasetStore, LoadError, Provenance, Table, preview_records, profile
from .ops import OPS_DOC, OpError, run_pipeline
from .verify import Check, numbers_in_text, verify

TOOL_RESULT_LIMIT = 7000
REVISION_STEPS = 4  # 수치 검증 실패 뒤 스스로 고칠 때 더 쓰는 단계
KEEP_RECENT_TOOL_RESULTS = 4  # 모델에 원문 그대로 보내는 최근 도구 결과 수
OLD_TOOL_RESULT_CHARS = 600   # 그보다 오래된 결과는 앞부분만

PROMPT_FILE = Path(__file__).with_name("resources") / "system_prompt.md"


def system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8").replace("{today}", time.strftime("%Y-%m-%d")) + "\n" + OPS_DOC


TOOLS = [
    {"type": "function", "function": {
        "name": "search_datasets",
        "description": "제주데이터허브·제주빅데이터센터 데이터 카탈로그를 한국어 키워드로 검색한다.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "검색어(예: '버스 정류소 이용', '농산물 도매 가격')"},
            "loadable_only": {"type": "boolean", "description": "true면 바로 불러올 수 있는 API/FILE/센터 데이터만"},
        }, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "inspect_dataset",
        "description": "데이터 상세: 설명, 기간, 파일 목록, API 요청 변수, 미리보기 행.",
        "parameters": {"type": "object", "properties": {
            "dataset_id": {"type": "string", "description": "search 결과의 id(예: hub:583)"}},
            "required": ["dataset_id"]}}},
    {"type": "function", "function": {
        "name": "load_dataset",
        "description": "데이터를 표로 불러와 핸들(D1…)을 돌려준다. API는 api_params 필요, FILE은 file_name 선택.",
        "parameters": {"type": "object", "properties": {
            "dataset_id": {"type": "string"},
            "file_name": {"type": "string", "description": "FILE 데이터가 여러 개일 때 고를 파일명"},
            "api_params": {"type": "object", "description": "API 요청 변수(예: {\"startDate\":\"20240101\",\"endDate\":\"20241231\"})",
                           "additionalProperties": {"type": "string"}},
        }, "required": ["dataset_id"]}}},
    {"type": "function", "function": {
        "name": "analyze",
        "description": "표 핸들에 분석 단계를 차례로 적용해 새 결과 표(R1…)를 만든다.",
        "parameters": {"type": "object", "properties": {
            "table": {"type": "string", "description": "입력 표 핸들(D1, R1 등)"},
            "steps": {"type": "array", "items": {"type": "object"}, "description": "연산 단계 목록"},
            "purpose": {"type": "string", "description": "이 분석으로 알아내려는 것(한 문장)"},
        }, "required": ["table", "steps", "purpose"]}}},
    {"type": "function", "function": {
        "name": "make_chart",
        "description": "결과 표로 차트를 만든다.",
        "parameters": {"type": "object", "properties": {
            "table": {"type": "string"},
            "kind": {"type": "string", "enum": sorted(charts.KINDS)},
            "x": {"type": "string"},
            "y": {"type": "array", "items": {"type": "string"}},
            "title": {"type": "string"},
        }, "required": ["table", "kind", "x", "y", "title"]}}},
    {"type": "function", "function": {
        "name": "finish",
        "description": "최종 답변을 낸다. 답에 쓴 숫자는 모두 결과 표에 있어야 한다.",
        "parameters": {"type": "object", "properties": {
            "answer_markdown": {"type": "string", "description": "도민에게 보여줄 답변(마크다운)"},
            "used_tables": {"type": "array", "items": {"type": "string"}, "description": "근거가 된 표 핸들"},
            "limitations": {"type": "array", "items": {"type": "string"}, "description": "데이터·분석의 한계"},
            "follow_up_questions": {"type": "array", "items": {"type": "string"}},
        }, "required": ["answer_markdown", "used_tables", "limitations"]}}},
]
FINISH_ONLY = [t for t in TOOLS if t["function"]["name"] == "finish"]


@dataclass
class TraceStep:
    tool: str
    args: dict[str, Any]
    ok: bool
    summary: str
    seconds: float


@dataclass
class Chart:
    table: str
    title: str
    path: Path


@dataclass
class Answer:
    question: str
    markdown: str
    limitations: list[str]
    follow_ups: list[str]
    used_tables: list[str]
    charts: list[Chart]
    checks: list[Check]
    trace: list[TraceStep]
    completed: bool
    output_dir: Path | None = None

    @property
    def unverified(self) -> list[Check]:
        return [c for c in self.checks if not c.verified]


def compact_history(history: list[dict[str, Any]], keep_recent: int = KEEP_RECENT_TOOL_RESULTS) -> list[dict[str, Any]]:
    """오래된 도구 결과는 앞부분만 남겨 모델에 보낸다(원본 history는 그대로).

    도구 결과가 쌓이면 소형 로컬 모델(컨텍스트 8~16K)이 넘치기 쉽다. 최근 결과는 그대로 두고,
    오래된 결과는 표 핸들·행 수가 담긴 앞부분만 남겨도 이후 판단에 충분하다.
    """
    tool_idx = [i for i, m in enumerate(history) if m.get("role") == "tool"]
    old = set(tool_idx[:-keep_recent]) if keep_recent else set(tool_idx)
    out = []
    for i, m in enumerate(history):
        if i in old and len(m["content"]) > OLD_TOOL_RESULT_CHARS:
            m = {**m, "content": m["content"][:OLD_TOOL_RESULT_CHARS] + "… (이전 결과 요약)"}
        out.append(m)
    return out


def _json(obj: Any, limit: int = TOOL_RESULT_LIMIT) -> str:
    text = json.dumps(obj, ensure_ascii=False, default=str)
    if len(text) > limit:
        text = text[:limit] + f"… (잘림, 전체 {len(text)}자)"
    return text


@dataclass
class Session:
    settings: Settings
    catalog: Catalog
    client: DataHubClient
    store: DatasetStore
    llm: OpenAI | None
    charts: list[Chart] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    answers: list[Answer] = field(default_factory=list)
    run_dir: Path | None = None

    @classmethod
    def create(cls, settings: Settings, catalog: Catalog) -> "Session":
        client = DataHubClient(settings.jeju_project_key)
        store = DatasetStore(catalog, client, settings.data_dir / "cache", settings.center_data_dir)
        llm = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key) if settings.llm_ready else None
        # 같은 초에 여러 실행(화면 탭 2개, 동시 명령)이 시작돼도 결과 폴더가 섞이지 않게 임의 꼬리를 붙인다.
        run_dir = settings.output_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
        return cls(settings, catalog, client, store, llm, run_dir=run_dir)

    # --- 도구 구현 ----------------------------------------------------------
    def t_search(self, query: str, loadable_only: bool = True) -> dict:
        kinds = {"API", "FILE", "CENTER"} if loadable_only else None
        hits = self.catalog.search(query, limit=8, kinds=kinds)
        return {"query": query, "results": [e.card() for e, _ in hits]}

    def t_inspect(self, dataset_id: str) -> dict:
        return self.store.inspect(dataset_id)

    def t_load(self, dataset_id: str, file_name: str | None = None, api_params: dict | None = None) -> dict:
        table = self.store.load(dataset_id, file_name=file_name, api_params=api_params)
        out = {
            "table": table.handle, "rows": len(table.df), "source": table.provenance.title,
            "columns": profile(table.df), "preview": preview_records(table.df, 8),
        }
        p = table.provenance
        if p.total_rows and p.total_rows > p.rows:
            out["warning"] = f"서버 전체 {p.total_rows}건 중 {p.rows}건만 불러왔습니다. 기간을 좁히세요."
        if p.detail.get("skipped_rows"):
            out["warning"] = (f"원본 파일에서 칸 수가 맞지 않는 깨진 행 {p.detail['skipped_rows']}개를 건너뛰었습니다. "
                              "답변의 한계에 적으세요.")
        return out

    def t_analyze(self, table: str, steps: list[dict], purpose: str) -> dict:
        src = self.store.get(table)
        df, code = run_pipeline(src.df, steps, table, lambda h: self.store.get(h).df)
        handle = self.store.new_handle("R")
        prov = Provenance(src.provenance.entry_id, src.provenance.title, src.provenance.source_url, "DERIVED",
                          {"from": table, "purpose": purpose, "steps": steps}, rows=len(df))
        self.store.tables[handle] = Table(handle, df, prov, f"# {purpose}\n{code}\n{handle} = df")
        return {"table": handle, "rows": len(df), "columns": list(df.columns),
                "result": preview_records(df, 30), "truncated": len(df) > 30}

    def t_chart(self, table: str, kind: str, x: str, y: list[str], title: str) -> dict:
        t = self.store.get(table)
        assert self.run_dir is not None
        path = self.run_dir / f"chart{len(self.charts) + 1}.png"
        charts.render(t.df, kind, x, y, title, path)
        self.charts.append(Chart(table, title, path))
        return {"chart": path.name, "title": title}

    def dispatch(self, name: str, args: dict) -> dict:
        fn: Callable[..., dict] = {
            "search_datasets": self.t_search, "inspect_dataset": self.t_inspect, "load_dataset": self.t_load,
            "analyze": self.t_analyze, "make_chart": self.t_chart,
        }[name]
        return fn(**args)

    def _check(self, markdown: str, question: str) -> list[Check]:
        """답변 숫자를 이번 세션의 모든 표와 도구가 보여준 메타데이터(파일 크기·전체 건수 등)에 대조."""
        frames = [t.df for t in self.store.tables.values()]
        # 오류 결과(검증 실패 안내 등)는 답변 숫자를 되풀이하므로 관측값에서 뺀다.
        observed = [n for m in self.history if m.get("role") == "tool" and not m["content"].startswith('{"error"')
                    for n in numbers_in_text(m["content"])]
        # 질문에 나온 숫자(예: '상위 20곳', '2025년')는 계산값이 아니라 조건이다.
        return verify(markdown, frames, observed + numbers_in_text(question))

    # --- 에이전트 루프 -------------------------------------------------------
    def ask(self, question: str, on_event: Callable[[TraceStep], None] | None = None) -> Answer:
        if self.llm is None:
            raise RuntimeError("LLM이 설정되지 않았습니다(.env의 LLM_BASE_URL·LLM_MODEL).")
        if not self.history:
            self.history.append({"role": "system", "content": system_prompt()})
        self.history.append({"role": "user", "content": question})
        trace: list[TraceStep] = []
        charts_before = len(self.charts)
        final: dict[str, Any] | None = None
        budget, step, revised = self.settings.max_steps, 0, False

        while step < budget:
            remaining = budget - step - 1
            step += 1
            if remaining == 0:
                # 일부 모델은 특정 함수 강제(tool_choice)를 지원하지 않는다 → finish 도구만 남기고 명시적으로 요청.
                self.history.append({"role": "user", "content": (
                    "(단계 한도) 더 분석하지 말고 지금까지 만든 결과 표로 finish를 호출해 답하세요.")})
            resp = self.llm.chat.completions.create(
                model=self.settings.llm_model,
                messages=compact_history(self.history),
                tools=FINISH_ONLY if remaining == 0 else TOOLS,
            )
            msg = resp.choices[0].message
            calls = msg.tool_calls or []
            parsed: list[dict | json.JSONDecodeError] = []
            dumped = []
            for c in calls:
                d = c.model_dump(exclude_none=True)
                try:
                    parsed.append(json.loads(c.function.arguments or "{}"))
                except json.JSONDecodeError as exc:
                    parsed.append(exc)
                    # 깨진 인자를 그대로 남기면 다음 요청 전체가 400으로 거부된다 → 빈 객체로 바꿔 기록.
                    d["function"]["arguments"] = "{}"
                dumped.append(d)
            self.history.append({
                "role": "assistant", "content": msg.content or "",
                **({"tool_calls": dumped} if calls else {}),
            })
            if not calls:
                text = (msg.content or "").strip()
                if text and len(text) > 80:
                    # 도구 없이 바로 답한 경우: finish와 같은 수치 검증·1회 자기 수정을 거친다.
                    bad = [c.text for c in self._check(text, question) if not c.verified]
                    if bad and not revised:
                        revised, budget = True, budget + REVISION_STEPS
                        self.history.append({"role": "user", "content": (
                            "(수치 검증) 다음 수치가 결과 표에서 확인되지 않습니다: " + ", ".join(bad)
                            + ". 차이·합계·비율이면 analyze로 계산해 표에 남기고, 아니면 빼서 finish로 답하세요.")})
                        ts = TraceStep("finish", {}, False, "수치 검증 실패 → 스스로 수정: " + ", ".join(bad)[:150], 0.0)
                        trace.append(ts)
                        if on_event:
                            on_event(ts)
                        continue
                    final = {"answer_markdown": text, "used_tables": [], "limitations": []}
                    break
                # 소형 모델은 도구 결과를 받은 뒤 빈 응답으로 멈추곤 한다 → 다음 행동을 명시적으로 요구.
                self.history.append({"role": "user", "content": (
                    "(진행 안내) 아직 최종 답이 없습니다. 분석이 더 필요하면 analyze/make_chart를, "
                    "충분하면 finish를 호출하세요. 지금 불러온 표: "
                    + ", ".join(f"{h}({len(t.df)}행: {', '.join(map(str, list(t.df.columns)[:12]))})"
                                for h, t in self.store.tables.items()))})
                continue
            for call, args in zip(calls, parsed):
                name = call.function.name
                if isinstance(args, json.JSONDecodeError):
                    result, ok = {"error": f"인자 JSON 오류({args}). 올바른 JSON으로 다시 호출하세요."}, False
                    trace.append(TraceStep(name, {}, False, result["error"][:200], 0.0))
                else:
                    if name == "finish":
                        bad = [c.text for c in self._check(args.get("answer_markdown", ""), question) if not c.verified]
                        if bad and not revised:
                            # 근거 없는 숫자가 있으면 한 번은 스스로 고치게 한다(계산으로 확인하거나 빼거나).
                            revised, budget = True, budget + REVISION_STEPS
                            result, ok = {"error": "답변의 다음 수치가 결과 표에서 확인되지 않습니다: " + ", ".join(bad),
                                          "안내": "차이·합계·비율이면 analyze(derive/groupby)로 계산해 표에 남긴 뒤, "
                                                  "아니면 그 숫자를 빼고 finish를 다시 호출하세요."}, False
                            ts = TraceStep("finish", {}, False, "수치 검증 실패 → 스스로 수정: " + ", ".join(bad)[:150], 0.0)
                            trace.append(ts)
                            if on_event:
                                on_event(ts)
                        else:
                            final = args
                            result, ok = {"ok": True}, True
                    else:
                        t0 = time.time()
                        try:
                            result, ok = self.dispatch(name, args), True
                        except (LoadError, OpError, charts.ChartError, KeyError, TypeError, ValueError) as exc:
                            result, ok = {"error": str(exc)}, False
                        except Exception as exc:  # 네트워크 등 예기치 못한 오류도 모델이 대응하게 돌려준다
                            result, ok = {"error": f"{type(exc).__name__}: {exc}"}, False
                        ts = TraceStep(name, args, ok, _summary(name, result), round(time.time() - t0, 2))
                        trace.append(ts)
                        if on_event:
                            on_event(ts)
                if 0 < remaining <= 3 and name != "finish":
                    result = {**result, "_남은_단계": f"{remaining}회 — 핵심 결과가 나왔으면 바로 finish 하세요"}
                self.history.append({"role": "tool", "tool_call_id": call.id, "content": _json(result)})
            if final is not None:
                break

        completed = final is not None
        final = final or {"answer_markdown": "분석 단계 한도 안에 답을 완성하지 못했습니다. 질문을 더 구체적으로 해 주세요.",
                          "used_tables": [], "limitations": []}
        used = [h for h in final.get("used_tables") or [] if h in self.store.tables]
        answer = Answer(
            question=question,
            markdown=final.get("answer_markdown", ""),
            limitations=list(final.get("limitations") or []),
            follow_ups=list(final.get("follow_up_questions") or []),
            used_tables=used,
            charts=self.charts[charts_before:],
            checks=self._check(final.get("answer_markdown", ""), question),
            trace=trace,
            completed=completed,
        )
        self.answers.append(answer)
        return answer


def _summary(name: str, result: dict) -> str:
    if "error" in result:
        return "오류: " + str(result["error"])[:200]
    if name == "search_datasets":
        return f"'{result['query']}' → " + ", ".join(r["title"][:24] for r in result["results"][:4])
    if name == "inspect_dataset":
        return f"{result.get('title')} ({result.get('kind')}, {result.get('period') or '기간 정보 없음'})"
    if name == "load_dataset":
        return f"{result['table']}: {result['source']} {result['rows']:,}행"
    if name == "analyze":
        return f"{result['table']}: {result['rows']:,}행 × {len(result['columns'])}열"
    if name == "make_chart":
        return f"차트 '{result['title']}'"
    return ""
