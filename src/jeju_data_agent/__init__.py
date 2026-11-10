"""제주 데이터 길잡이 — 제주데이터허브·제주빅데이터센터 데이터 분석 AI Agent."""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

PORT = 8501


def _open_when_ready(proc: subprocess.Popen, timeout: float = 120) -> None:
    """서버가 포트를 열면 브라우저를 띄운다(먼저 열면 '연결할 수 없음' 화면이 뜬다)."""
    deadline = time.monotonic() + timeout
    while proc.poll() is None and time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=1).close()
        except OSError:
            time.sleep(0.5)
            continue
        webbrowser.open(f"http://localhost:{PORT}")
        return


def _session():
    from .agent import Session
    from .catalog import load_catalog
    from .config import Settings
    from .datahub import DataHubClient

    settings = Settings.load()
    catalog = load_catalog(settings.data_dir, DataHubClient())
    return Session.create(settings, catalog)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jeju-data-agent", description="제주 데이터 길잡이")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ui", help="웹 화면 실행(기본 http://localhost:8501)")
    p_ask = sub.add_parser("ask", help="질문 하나를 분석하고 결과 폴더를 만든다")
    p_ask.add_argument("question")
    p_search = sub.add_parser("search", help="데이터 카탈로그 검색(LLM 불필요)")
    p_search.add_argument("query")
    sub.add_parser("refresh-catalog", help="제주데이터허브 카탈로그를 새로 받는다")
    args = parser.parse_args(argv)

    if args.cmd == "ui":
        app = Path(__file__).with_name("app.py")
        proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(app), "--server.headless=true",
                                 f"--server.port={PORT}", "--browser.gatherUsageStats=false"])
        try:
            _open_when_ready(proc)
            return proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            return proc.wait()
    if args.cmd == "refresh-catalog":
        from .catalog import load_catalog
        from .config import Settings
        from .datahub import DataHubClient

        cat = load_catalog(Settings.load().data_dir, DataHubClient(), refresh=True)
        print(f"카탈로그 {len(cat.entries):,}건 갱신 완료")
        return 0
    if args.cmd == "search":
        session = _session()
        for entry, score in session.catalog.search(args.query, limit=10):
            print(f"{score:6.1f}  {entry.id:<11} {entry.kind:<9} {entry.title}  [{entry.updated or '-'}]")
        return 0
    if args.cmd == "ask":
        from .report import export

        session = _session()

        def show(step):
            mark = "✓" if step.ok else "✗"
            print(f"  {mark} {step.tool}: {step.summary} ({step.seconds}s)", flush=True)

        answer = session.ask(args.question, on_event=show)
        out = export(answer, session)
        print("\n" + answer.markdown)
        if answer.unverified:
            print("\n⚠️ 근거 표에서 확인되지 않은 수치:", ", ".join(c.text for c in answer.unverified))
        print(f"\n결과 폴더: {out}")
        return 0 if answer.completed else 1
    return 2
