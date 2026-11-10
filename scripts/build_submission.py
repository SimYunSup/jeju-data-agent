"""제출물 생성: 시나리오 실측 결과로 기획서 표를 채워 PDF용 HTML을 만들고, 최종 결과물 ZIP을 묶는다.

실행: uv run python scripts/build_submission.py
- docs/scenario_results.json  (scripts/run_scenarios.py 결과)을 읽는다.
- dist/proposal/proposal.html  → 브라우저 인쇄(A4)로 기획서 PDF 생성
- dist/jeju-data-agent-final.zip → 최종 결과물(소스·매뉴얼·명세·결과 설명·예시 결과)
"""

from __future__ import annotations

import html
import json
import shutil
import unicodedata
import zipfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
# 최종 ZIP에 넣는 경로(비밀·캐시·가상환경 제외)
INCLUDE = ["README.md", "pyproject.toml", "uv.lock", "requirements.txt", ".python-version", ".env.example",
           ".streamlit/config.toml", "run.bat", "run.sh", "setup_local_ai.bat", "setup_local_ai.sh",
           "src", "tests", "scripts", "docs"]
EXCLUDE_PARTS = {"__pycache__", ".DS_Store"}


def scenario_rows() -> tuple[list[dict], dict]:
    data = json.loads((ROOT / "docs/scenario_results.json").read_text(encoding="utf-8"))
    return data["results"], {"model": data["model"], "access": data.get("data_access", "")}


def scenario_table(rows: list[dict], meta: dict) -> str:
    done = sum(r.get("completed") for r in rows)
    body = []
    for r in rows:
        unver = len(r.get("unverified", []))
        nums = r.get("numbers", 0)
        check = f"{nums - unver}/{nums}" if nums else "-"
        datasets = "<br>".join(html.escape(d) for d in r.get("datasets", [])) or html.escape(r.get("error", "-"))
        body.append(
            f"<tr><td>{html.escape(r['domain'])}</td><td>{html.escape(r['question'])}</td><td>{datasets}</td>"
            f"<td>{'완료' if r.get('completed') else '미완'}</td><td>{r.get('tool_calls', '-')}"
            f" ({r.get('tool_errors', 0)})</td><td>{check}</td><td>{r.get('charts', 0)}</td><td>{r['seconds']:.0f}초</td></tr>")
    return (f"<h3>대표 질문 {len(rows)}종 실측 — 완주 {done}/{len(rows)} "
            f"(모델 <code>{html.escape(meta['model'])}</code>, {html.escape(meta['access'])})</h3>"
            "<table class='scen'><colgroup><col style='width:6%'><col style='width:25%'><col style='width:31%'>"
            "<col style='width:6%'><col style='width:9%'><col style='width:9%'><col style='width:6%'><col style='width:8%'></colgroup>"
            "<tr><th>분야</th><th>질문</th><th>Agent가 고른 데이터</th><th>결과</th><th>도구(오류)</th>"
            "<th>수치 검증</th><th>차트</th><th>시간</th></tr>" + "".join(body) + "</table>"
            "<p class='note'>도구(오류): 도구 호출 수와 그중 오류 뒤 스스로 고친 횟수. 수치 검증: 답변 집계 숫자(개수 포함) 중 결과 표에서 확인된 개수. "
            "생활(충전소)은 데이터에 시·군 주소 열이 없어 Agent가 지역을 짐작해 세지 않고 답변 불가와 필요한 데이터를 밝힌 사례로, "
            "완주에는 넣었지만 질문에 직접 답하지는 못했습니다. "
            "원자료는 docs/scenario_results.json, 각 답변의 보고서·재현 코드는 docs/examples/(원본 표 제외).</p>")


def build_proposal(rows: list[dict], meta: dict) -> Path:
    out = DIST / "proposal"
    out.mkdir(parents=True, exist_ok=True)
    src = (ROOT / "docs/proposal/proposal.html").read_text(encoding="utf-8")
    done = sum(r.get("completed") for r in rows)
    rate = verified_rate(rows)
    page = (src.replace("{{SCENARIO_TABLE}}", scenario_table(rows, meta))
            .replace("{{SUCCESS}}", f"{done}/{len(rows)}").replace("{{VERIFIED}}", rate)
            .replace("{{LOCAL}}", html.escape(local_summary())))
    (out / "proposal.html").write_text(page, encoding="utf-8")
    for img in (ROOT / "docs/proposal").glob("*.png"):
        shutil.copy2(img, out / img.name)
    # 기획서 '실행 결과' 차트: 감귤(1번)·버스(2번) 시나리오의 첫 차트
    for idx, name in ((0, "chart-citrus.png"), (1, "chart-bus.png")):
        folder = rows[idx].get("output") if idx < len(rows) else None
        charts = sorted(Path(folder).glob("chart*.png")) if folder else []
        if charts:
            shutil.copy2(charts[0], out / name)
    return out / "proposal.html"


def md_table(rows: list[dict], meta: dict) -> str:
    done = sum(r.get("completed") for r in rows)
    lines = [f"모델 `{meta['model']}` · {meta['access']} · 완주 {done}/{len(rows)}", "",
             "| 분야 | 질문 | Agent가 고른 데이터 | 결과 | 도구(오류) | 수치 검증 | 차트 | 시간 |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        nums, unver = r.get("numbers", 0), len(r.get("unverified", []))
        check = f"{nums - unver}/{nums}" if nums else "-"
        data = "<br>".join(r.get("datasets", [])) or r.get("error", "-")
        lines.append(f"| {r['domain']} | {r['question']} | {data} | {'완료' if r.get('completed') else '미완'} | "
                     f"{r.get('tool_calls', '-')} ({r.get('tool_errors', 0)}) | {check} | {r.get('charts', 0)} | {r['seconds']:.0f}초 |")
    return "\n".join(lines)


def verified_rate(rows: list[dict]) -> str:
    nums = sum(r.get("numbers", 0) for r in rows)
    bad = sum(len(r.get("unverified", [])) for r in rows)
    return f"{(nums - bad) / nums * 100:.1f}%" if nums else "-"


def local_summary() -> str:
    """로컬 모델 실측(docs/scenario_results_local.json)이 있으면 한 문장으로 요약."""
    path = ROOT / "docs/scenario_results_local.json"
    if not path.is_file():
        return ""
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data["results"]
    answered = sum(bool(r.get("completed") and r.get("datasets")) for r in rows)
    secs = sorted(r["seconds"] for r in rows)
    return (f"같은 대표 질문 {len(rows)}개를 로컬 {data['model']}로 돌린 결과 데이터를 불러와 답한 질문 {answered}/{len(rows)}, "
            f"답변 수치 확인율 {verified_rate(rows)}, 질문당 중앙값 {secs[len(secs) // 2]:.0f}초였습니다"
            "(Apple Silicon에서 실측, GTX 1060에서는 더 느릴 수 있음).")


def fill_block(marker: str, body: str) -> None:
    doc = ROOT / "docs/결과_설명자료.md"
    text = doc.read_text(encoding="utf-8")
    start, end = f"<!-- {marker}:START -->", f"<!-- {marker}:END -->"
    head, rest = text.split(start, 1)
    tail = rest.split(end, 1)[1]
    doc.write_text(f"{head}{start}\n{body}\n{end}{tail}", encoding="utf-8")


def copy_examples(rows: list[dict]) -> None:
    """시나리오별 결과 폴더를 docs/examples로 복사. 원본 표(D*.csv)는 재배포하지 않는다(analysis.py가 다시 받는다)."""
    dest_root = ROOT / "docs/examples"
    shutil.rmtree(dest_root, ignore_errors=True)
    for i, r in enumerate(rows, 1):
        src = Path(r.get("output", ""))
        if not r.get("completed") or not src.is_dir():
            continue
        dest = dest_root / f"{i:02d}-{r['domain']}"
        dest.mkdir(parents=True)
        for f in src.iterdir():
            if f.suffix == ".csv" and f.name.startswith("D"):
                continue
            shutil.copy2(f, dest / f.name)


MANUAL = "docs/사용자_매뉴얼.md"


def eval_settings() -> dict[str, str]:
    """심사용 AI 설정(.env의 LLM_*)을 매뉴얼 자리표시자 값으로. 레포에는 자리표시자만 남는다."""
    env = dict(line.split("=", 1) for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
               if "=" in line and not line.lstrip().startswith("#"))
    values = {k: env.get(k, "").strip().strip('"') for k in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY")}
    missing = [k for k, v in values.items() if not v]
    if missing:
        raise SystemExit(f".env에 심사용 {missing} 값이 없습니다")
    host = urlparse(values["LLM_BASE_URL"]).hostname or ""
    return {"{{EVAL_" + k + "}}": v for k, v in values.items()} | {"{{EVAL_LLM_HOST}}": host}


def build_zip() -> Path:
    DIST.mkdir(exist_ok=True)
    archive = DIST / "jeju-data-agent-final.zip"
    fills = eval_settings()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in INCLUDE:
            path = ROOT / rel
            files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
            for f in files:
                if EXCLUDE_PARTS.intersection(f.parts) or f.name == ".env":
                    continue
                name = Path("jeju-data-agent") / f.relative_to(ROOT)
                if unicodedata.normalize("NFC", f.relative_to(ROOT).as_posix()) == MANUAL:
                    text = f.read_text(encoding="utf-8")
                    for k, v in fills.items():
                        text = text.replace(k, v)
                    zf.writestr(str(name), text)
                    continue
                zf.write(f, name)
    return archive


def main() -> int:
    rows, meta = scenario_rows()
    fill_block("SCENARIOS", md_table(rows, meta))
    fill_block("LOCAL", local_summary())
    copy_examples(rows)
    print("기획서 HTML:", build_proposal(rows, meta))
    print("최종 ZIP:", build_zip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
