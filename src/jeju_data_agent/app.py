"""제주 데이터 길잡이 웹 화면(Streamlit). 실행: run.bat / run.sh 또는 `uv run jeju-data-agent ui`."""

from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from jeju_data_agent.agent import Answer, Session
from jeju_data_agent.catalog import load_catalog
from jeju_data_agent.config import Settings
from jeju_data_agent.datahub import DataHubClient
from jeju_data_agent.report import export, zip_dir

TOOL_LABEL = {
    "search_datasets": "🔎 데이터 찾기", "inspect_dataset": "📄 데이터 살펴보기", "load_dataset": "📥 데이터 불러오기",
    "analyze": "🧮 분석", "make_chart": "📊 차트",
}
EXAMPLES = [
    "서귀포시 감귤 종류별로 생산량이 어떻게 변해왔어?",
    "제주에서 버스 이용객이 가장 많은 정류소는 어디야?",
    "요즘 깐마늘 도매 가격이 작년보다 올랐어?",
    "제주 월동무·양배추 같은 노지채소 재배 면적은 어떻게 돼?",
    "외국인 입도객은 어느 나라에서 가장 많이 와?",
]

st.set_page_config(page_title="제주 데이터 길잡이", page_icon="🍊", layout="wide")


@st.cache_resource
def _catalog():
    settings = Settings.load()
    return load_catalog(settings.data_dir, DataHubClient())


def _session() -> Session:
    if "session" not in st.session_state:
        st.session_state.session = Session.create(Settings.load(), _catalog())
        st.session_state.turns = []
    return st.session_state.session


def _render_answer(answer: Answer, session: Session, key: str) -> None:
    # 모델이 쓴 #/## 제목은 채팅 말풍선에서 너무 커서 소제목 크기로 낮춘다.
    st.markdown(re.sub(r"^#{1,3} ", "#### ", answer.markdown, flags=re.M))
    for chart in answer.charts:
        st.image(str(chart.path), caption=chart.title)
    if answer.unverified:
        st.warning("근거 표에서 확인되지 않은 수치가 있습니다: " + ", ".join(c.text for c in answer.unverified))
    elif answer.checks:
        st.caption(f"✅ 답변 속 수치 {len(answer.checks)}개를 모두 근거 표에서 확인했습니다.")
    if answer.limitations:
        with st.expander("데이터·분석의 한계"):
            for item in answer.limitations:
                st.markdown(f"- {item}")
    with st.expander("근거 데이터와 출처"):
        for h in answer.used_tables:
            table = session.store.tables[h]
            p = table.provenance
            st.markdown(f"**{h}** · {p.title} · [{p.source_url}]({p.source_url})")
            st.dataframe(table.df.head(200), use_container_width=True)
    with st.expander("분석 과정"):
        for step in answer.trace:
            st.markdown(f"{'✅' if step.ok else '⚠️'} {TOOL_LABEL.get(step.tool, step.tool)} — {step.summary}")
    if answer.output_dir:
        archive = zip_dir(answer.output_dir)
        st.download_button("결과 내려받기(보고서·표·차트·재현 코드)", archive.read_bytes(),
                           file_name=archive.name, mime="application/zip", key=f"dl-{key}")
    if answer.follow_ups:
        st.caption("이어서 물어볼 만한 질문: " + " · ".join(answer.follow_ups))


def _sidebar(settings: Settings) -> str | None:
    st.sidebar.title("🍊 제주 데이터 길잡이")
    st.sidebar.caption("제주데이터허브·제주빅데이터센터 데이터를 묻고 답하는 AI 분석 도우미")
    st.sidebar.markdown(f"- AI 모델: `{settings.llm_model or '미설정'}`")
    st.sidebar.markdown(f"- 데이터허브 API 키: {'설정됨' if settings.jeju_project_key else '없음(파일 데이터만 사용)'}")
    st.sidebar.markdown(f"- 센터 데이터 폴더: `{settings.center_data_dir or '미설정'}`")
    st.sidebar.markdown(f"- 카탈로그: {len(_catalog().entries):,}종")
    picked = None
    st.sidebar.subheader("예시 질문")
    for i, q in enumerate(EXAMPLES):
        if st.sidebar.button(q, key=f"ex{i}", use_container_width=True):
            picked = q
    if st.sidebar.button("새 대화", use_container_width=True):
        st.session_state.pop("session", None)
        st.rerun()
    return picked


def _chat_tab(settings: Settings, picked: str | None) -> None:
    session = _session()
    if not settings.llm_ready:
        st.error("AI 모델이 설정되지 않았습니다. 사용자 매뉴얼의 '.env 설정'을 따라 LLM_BASE_URL·LLM_MODEL을 넣어 주세요. "
                 "'데이터 찾아보기' 탭은 AI 없이도 쓸 수 있습니다.")
        return
    for i, (question, answer) in enumerate(st.session_state.turns):
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            _render_answer(answer, session, str(i))
    question = st.chat_input("궁금한 것을 물어보세요 (예: 애월읍 관광객 카드 소비는 어떤 업종이 많아?)") or picked
    if not question:
        return
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.status("분석 중…", expanded=True) as status:
            def show(step):
                st.write(f"{'✅' if step.ok else '⚠️'} {TOOL_LABEL.get(step.tool, step.tool)} — {step.summary}")
            try:
                answer = session.ask(question, on_event=show)
            except Exception as exc:  # 네트워크·모델 서버 오류를 화면에 그대로 안내
                status.update(label="오류", state="error")
                st.error(f"분석 중 오류가 났습니다: {exc}")
                return
            export(answer, session)
            status.update(label="분석 완료", state="complete", expanded=False)
        _render_answer(answer, session, str(len(st.session_state.turns)))
    st.session_state.turns.append((question, answer))


def _browse_tab() -> None:
    session = _session()
    query = st.text_input("데이터 검색(예: 버스, 감귤, 카드, 와이파이)")
    if not query:
        st.caption("검색어를 넣으면 제주데이터허브·제주빅데이터센터 데이터 목록에서 찾아 줍니다. AI 키가 없어도 동작합니다.")
        return
    hits = session.catalog.search(query, limit=20, kinds=None)
    rows = [{"ID": e.id, "데이터": e.title, "분류": e.category, "형태": e.kind, "수정일": e.updated, "링크": e.url}
            for e, _ in hits]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                 column_config={"링크": st.column_config.LinkColumn()})
    choice = st.selectbox("자세히 볼 데이터", [r["ID"] for r in rows]) if rows else None
    if choice:
        info = session.store.inspect(choice)
        st.json(info, expanded=False)
        entry = session.catalog.get(choice)
        if entry and entry.loadable and st.button("이 데이터 불러와 보기"):
            try:
                table = session.store.load(choice)
            except Exception as exc:
                st.error(str(exc))
            else:
                st.success(f"{table.handle}: {len(table.df):,}행")
                st.dataframe(table.df.head(500), use_container_width=True)


def main() -> None:
    settings = Settings.load()
    picked = _sidebar(settings)
    chat, browse = st.tabs(["💬 질문하기", "🗂️ 데이터 찾아보기"])
    with chat:
        _chat_tab(settings, picked)
    with browse:
        _browse_tab()


main()
