"""데이터 카탈로그: 제주데이터허브 1,259종 + 제주빅데이터센터 방문 데이터 목록을 한 색인으로.

검색은 한국어 글자 2-gram BM25. 형태소 분석기 없이도 '월동무 가격' → '농산물 품종별 일일 거래'처럼
제목·설명에 걸친 부분 일치를 잡고, 외부 서비스·GPU 없이 센터 PC에서 즉시 동작한다.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .datahub import DataHubClient

SNAPSHOT = Path(__file__).with_name("resources") / "catalog_snapshot.json"
MAX_AGE_SEC = 7 * 24 * 3600
LOADABLE_KINDS = ("API", "FILE", "CENTER")


@dataclass(frozen=True)
class Entry:
    id: str  # "hub:583" | "center:11"
    title: str
    category: str
    kind: str  # API | FILE | LINK | CENTER, 한 데이터가 여러 형태면 "API+FILE"
    description: str
    period: str
    updated: str
    auto_update: str
    owner: str
    views: int
    export_ok: bool | None = None  # 센터 데이터만: 반출 가능 여부

    @property
    def hub_id(self) -> int | None:
        return int(self.id.split(":", 1)[1]) if self.id.startswith("hub:") else None

    @property
    def url(self) -> str:
        if self.hub_id is not None:
            return f"https://jejudatahub.net/data/view/data/{self.hub_id}"
        return "https://jejudatahub.net/center/data"

    def card(self) -> dict:
        """에이전트에게 보여줄 요약(토큰 절약용)."""
        out = {
            "id": self.id, "title": self.title, "category": self.category, "kind": self.kind,
            "period": self.period, "updated": self.updated, "summary": self.description[:160],
        }
        if self.kind == "CENTER":
            out["note"] = "센터 방문 데이터: 센터 PC의 CENTER_DATA_DIR에 파일이 있어야 분석 가능" + (
                "" if self.export_ok else " (반출 불가)")
        elif not self.loadable:
            out["note"] = "외부 링크 데이터: 자동 적재 불가"
        return out

    @property
    def loadable(self) -> bool:
        return any(k in self.kind.split("+") for k in LOADABLE_KINDS)


_PREFIX = re.compile(r"^\s*\[[^\]]+\]\s*")


def _clean_title(title: str) -> str:
    # "[교통, 안전] [교통, 안전] 제목" 같은 중복 분류 접두어를 걷어낸다.
    prev = None
    while prev != title:
        prev, title = title, _PREFIX.sub("", title)
    return title.strip()


def _hub_entry(row: dict, kind: str) -> Entry:
    start, end = row.get("startDate") or "", row.get("endDate") or ""
    return Entry(
        id=f"hub:{row['id']}",
        title=_clean_title(row.get("title") or ""),
        category=row.get("categoryName") or "",
        kind=kind,
        description=re.sub(r"\s+", " ", row.get("description") or "").strip()[:600],
        period=f"{start}~{end}" if start or end else "",
        updated=(row.get("updateAt") or row.get("createAt") or "")[:10],
        auto_update=(row.get("autoUpdatePeriod") or "") if row.get("autoUpdateYn") else "",
        owner=row.get("owner") or row.get("createByName") or "",
        views=int(row.get("viewCount") or 0),
    )


def _center_entry(row: dict) -> Entry:
    return Entry(
        id=f"center:{row['id']}",
        title=row.get("title") or "",
        category=f"센터·{row.get('category') or ''}",
        kind="CENTER",
        description=f"제주빅데이터센터 방문 분석 데이터(테이블 {row.get('tableName')}).",
        period="", updated="", auto_update="", owner="제주빅데이터센터", views=0,
        export_ok=(row.get("returnAbleYn") == "Y"),
    )


def fetch_entries(client: DataHubClient) -> list[Entry]:
    kinds: dict[int, list[str]] = {}
    rows: dict[int, dict] = {}
    for kind in ("API", "FILE", "LINK"):
        for r in client.list_datasets(kind):
            kinds.setdefault(r["id"], []).append(kind)
            rows[r["id"]] = r
    entries = [_hub_entry(rows[i], "+".join(kinds[i])) for i in sorted(rows)]
    entries += [_center_entry(r) for r in client.center_tables()]
    return entries


# 도민 표현 ↔ 데이터허브 표기 차이를 메우는 최소 동의어. 검색어에 이 단어가 있으면 짝도 함께 찾는다.
SYNONYMS = {
    "관광객": ["입도객", "방문객"], "입도객": ["관광객"], "방문객": ["관광객", "입도객"],
    "가격": ["시세", "단가"], "시세": ["가격"], "매출": ["카드", "소비"], "소비": ["카드"],
    "손님": ["이용객", "방문객"], "사람": ["유동인구", "인구"], "날씨": ["기상"], "기상": ["날씨"],
    "버스": ["정류소", "노선"], "충전소": ["충전"], "사고": ["교통사고"], "쓰레기": ["폐기물", "종량제"],
}


def expand_query(query: str) -> str:
    extra = [syn for word, syns in SYNONYMS.items() if word in query for syn in syns]
    return " ".join([query, *extra])


def _bigrams(text: str) -> list[str]:
    grams: list[str] = []
    for token in re.findall(r"[0-9a-zA-Z]+|[가-힣]+", text.lower()):
        if len(token) == 1:
            grams.append(token)
        grams.extend(token[i:i + 2] for i in range(len(token) - 1))
    return grams


class Catalog:
    def __init__(self, entries: Iterable[Entry], fetched_at: float):
        self.entries = list(entries)
        self.fetched_at = fetched_at
        self._by_id = {e.id: e for e in self.entries}
        self._docs = [self._doc_terms(e) for e in self.entries]
        self._df = Counter(t for doc in self._docs for t in set(doc))
        self._avg_len = sum(sum(d.values()) for d in self._docs) / max(1, len(self._docs))

    @staticmethod
    def _doc_terms(e: Entry) -> Counter:
        terms: Counter = Counter()
        for weight, text in ((3, e.title), (1, e.category), (1, e.description)):
            for g in _bigrams(text):
                terms[g] += weight
        return terms

    def get(self, entry_id: str) -> Entry | None:
        return self._by_id.get(entry_id)

    def search(self, query: str, limit: int = 8, kinds: set[str] | None = None) -> list[tuple[Entry, float]]:
        q = Counter(_bigrams(expand_query(query)))
        if not q:
            return []
        n = len(self.entries)
        k1, b = 1.4, 0.6
        scored = []
        for e, doc in zip(self.entries, self._docs):
            if kinds and not kinds.intersection(e.kind.split("+")):
                continue
            length = sum(doc.values())
            s = 0.0
            for term, qf in q.items():
                tf = doc.get(term, 0)
                if not tf:
                    continue
                idf = math.log(1 + (n - self._df[term] + 0.5) / (self._df[term] + 0.5))
                s += qf * idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / self._avg_len))
            if s <= 0:
                continue
            if not e.loadable:
                s *= 0.5  # 외부 링크는 자동 적재가 안 되므로 뒤로 민다.
            scored.append((e, s))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    # --- 영속화 ----------------------------------------------------------
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"fetched_at": self.fetched_at, "entries": [asdict(e) for e in self.entries]}
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def from_file(cls, path: Path) -> "Catalog":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls((Entry(**e) for e in payload["entries"]), payload["fetched_at"])


def load_catalog(data_dir: Path, client: DataHubClient | None = None, refresh: bool = False) -> Catalog:
    """로컬 캐시 → (7일 경과·요청 시) 온라인 갱신 → 실패 시 동봉 스냅샷 순으로 연다."""
    cache = data_dir / "catalog.json"
    if cache.is_file() and not refresh:
        cat = Catalog.from_file(cache)
        if time.time() - cat.fetched_at < MAX_AGE_SEC:
            return cat
    if client is not None:
        try:
            cat = Catalog(fetch_entries(client), time.time())
            cat.save(cache)
            return cat
        except Exception:
            if cache.is_file():
                return Catalog.from_file(cache)
    return Catalog.from_file(cache if cache.is_file() else SNAPSHOT)
