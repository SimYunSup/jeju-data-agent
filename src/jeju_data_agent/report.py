"""답변을 결과 폴더(보고서·근거 표·차트·재현 코드·출처)로 내보낸다."""

from __future__ import annotations

import json
import shutil
import time
import zipfile
from pathlib import Path

from .agent import Answer, Session

RAW_CSV_MAX_ROWS = 100_000

SCRIPT_HEADER = '''"""제주 데이터 길잡이가 만든 분석을 그대로 다시 실행하는 스크립트.

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
'''


def _lineage(session: Session, handles: list[str]) -> list[str]:
    """결과 표를 만드는 데 필요한 모든 표를 생성 순서대로."""
    order: list[str] = []

    def visit(h: str) -> None:
        if h in order or h not in session.store.tables:
            return
        detail = session.store.tables[h].provenance.detail
        for parent in [detail.get("from"), *[s.get("right") for s in detail.get("steps", []) if s.get("op") == "merge"]]:
            if parent:
                visit(parent)
        order.append(h)

    for h in handles:
        visit(h)
    return order


def build_script(session: Session, handles: list[str]) -> str:
    parts = [SCRIPT_HEADER]
    for h in _lineage(session, handles):
        parts.append(f"\n# --- {h} ---\n{session.store.tables[h].code}\n")
    for h in handles:
        parts.append(f"print({h!r}); print({h}.head(30).to_string())\n")
    return "".join(parts)


def _report_md(answer: Answer, session: Session, chart_names: list[str]) -> str:
    lines = [f"# {answer.question}", "", answer.markdown.strip(), ""]
    if chart_names:
        lines += ["## 차트", *[f"![{c}]({c})" for c in chart_names], ""]
    if answer.limitations:
        lines += ["## 한계", *[f"- {x}" for x in answer.limitations], ""]
    lines += ["## 데이터 출처"]
    seen = set()
    for h in _lineage(session, answer.used_tables):
        p = session.store.tables[h].provenance
        if p.method == "DERIVED" or p.entry_id in seen:
            continue
        seen.add(p.entry_id)
        params = p.detail.get("params") or {}
        extra = p.detail.get("file") or ", ".join(f"{k}={v}" for k, v in params.items())
        parts = [p.method, extra, f"{p.rows:,}행", f"불러온 시각 {p.loaded_at}"]
        lines.append(f"- {p.title} — {', '.join(x for x in parts if x)} ({p.source_url})")
    lines += ["", "## 수치 검증"]
    if not answer.checks:
        lines.append("- 답변에 검증할 수치가 없습니다.")
    for c in answer.checks:
        lines.append(f"- {'✅' if c.verified else '⚠️ 근거 표에서 찾지 못함'} {c.text}")
    lines += ["", f"_생성: 제주 데이터 길잡이, {time.strftime('%Y-%m-%d %H:%M')}_", ""]
    return "\n".join(lines)


def export(answer: Answer, session: Session) -> Path:
    assert session.run_dir is not None
    out = session.run_dir / f"answer{len(session.answers)}"
    out.mkdir(parents=True, exist_ok=True)
    chart_names = []
    for c in answer.charts:
        dest = out / c.path.name
        shutil.copy2(c.path, dest)
        chart_names.append(dest.name)
    handles = answer.used_tables or [h for h in session.store.tables if h.startswith("R")][-3:]
    for h in _lineage(session, handles):
        df = session.store.tables[h].df
        # 원본 표가 크면(예: 1,580만 행) CSV로 복제하지 않는다. analysis.py가 원본을 다시 받아 재현한다.
        if h.startswith("D") and len(df) > RAW_CSV_MAX_ROWS:
            continue
        df.to_csv(out / f"{h}.csv", index=False, encoding="utf-8-sig")
    (out / "report.md").write_text(_report_md(answer, session, chart_names), encoding="utf-8")
    (out / "analysis.py").write_text(build_script(session, handles), encoding="utf-8")
    (out / "provenance.json").write_text(json.dumps({
        "question": answer.question,
        "tables": {h: session.store.tables[h].provenance.as_dict() for h in _lineage(session, handles)},
        "trace": [vars(t) for t in answer.trace],
        "checks": [vars(c) for c in answer.checks],
    }, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    answer.output_dir = out
    return out


def zip_dir(path: Path) -> Path:
    archive = path.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(path.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(path.parent))
    return archive
