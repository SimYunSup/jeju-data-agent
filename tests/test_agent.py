"""Agent 루프 동작을 가짜 LLM으로 검증한다(네트워크·모델 없이 결정적으로)."""

import json
import time
from types import SimpleNamespace

import pandas as pd

from jeju_data_agent.agent import Session
from jeju_data_agent.catalog import Catalog
from jeju_data_agent.config import Settings
from jeju_data_agent.datasets import DatasetStore, Provenance, Table


class FakeLLM:
    """미리 정한 응답(도구 호출 목록)을 차례로 돌려주고, 받은 메시지를 기록한다."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.requests = []
        self.texts = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs["messages"], default=str)))
        calls = [SimpleNamespace(
            id=f"c{len(self.requests)}{i}", type="function",
            function=SimpleNamespace(name=name, arguments=args),
            model_dump=lambda exclude_none=True, n=name, a=args, i=i: {
                "id": f"c{len(self.requests)}{i}", "type": "function", "function": {"name": n, "arguments": a}},
        ) for i, (name, args) in enumerate(self.turns.pop(0))]
        msg = SimpleNamespace(content="" if calls or not self.texts else self.texts.pop(0), tool_calls=calls or None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _session(tmp_path, llm) -> Session:
    settings = Settings("x", "fake", "k", None, tmp_path, tmp_path / "out", None, max_steps=6)
    catalog = Catalog([], time.time())
    store = DatasetStore(catalog, client=None, cache_dir=tmp_path, center_dir=None)
    df = pd.DataFrame({"정류소": ["A", "B"], "이용자": [1200, 800]})
    store.tables["R1"] = Table("R1", df, Provenance("hub:1", "t", "u", "DERIVED"), "")
    return Session(settings, catalog, client=None, store=store, llm=llm, run_dir=tmp_path / "run")


def _finish(text):
    return ("finish", json.dumps({"answer_markdown": text, "used_tables": ["R1"], "limitations": []},
                                 ensure_ascii=False))


def test_unverified_number_triggers_one_revision(tmp_path):
    llm = FakeLLM([[_finish("A는 1,200명, A와 B 차이는 400명")], [_finish("A는 1,200명, B는 800명")]])
    answer = _session(tmp_path, llm).ask("질문")
    assert answer.completed
    assert answer.markdown == "A는 1,200명, B는 800명"
    assert all(c.verified for c in answer.checks)
    # 두 번째 요청에는 '400'이 확인되지 않았다는 도구 결과가 들어가 있어야 한다
    tool_msgs = [m for m in llm.requests[1] if m["role"] == "tool"]
    assert "400" in tool_msgs[-1]["content"]


def test_second_unverified_finish_is_accepted_with_warning(tmp_path):
    llm = FakeLLM([[_finish("차이는 400명")], [_finish("차이는 약 400명")]])
    answer = _session(tmp_path, llm).ask("질문")
    assert answer.completed
    assert [c.text for c in answer.unverified] == ["400"]


def test_plain_text_answer_goes_through_the_same_revision(tmp_path):
    llm = FakeLLM([[], [_finish("A는 1,200명입니다.")]])
    llm.texts = ["A 정류소가 1위이고, 2위 B와의 차이는 400명입니다. " * 3]
    answer = _session(tmp_path, llm).ask("질문")
    assert answer.markdown == "A는 1,200명입니다."
    assert "400" in llm.requests[1][-1]["content"]


def test_broken_tool_arguments_are_not_replayed_to_the_model(tmp_path):
    llm = FakeLLM([[("analyze", "{broken")], [_finish("A는 1,200명")]])
    answer = _session(tmp_path, llm).ask("질문")
    assert answer.completed
    replayed = [c for m in llm.requests[1] if m.get("tool_calls") for c in m["tool_calls"]]
    assert replayed[0]["function"]["arguments"] == "{}"
