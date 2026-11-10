"""데이터 적재: 카탈로그 항목 → pandas DataFrame + 출처 기록.

- FILE: 제주데이터허브 첨부 파일(CSV/XLSX/JSON)을 내려받아 캐시한다(키 불필요).
- API: 사용자 프로젝트 키로 프록시 API를 호출한다.
- CENTER: 제주빅데이터센터 PC의 CENTER_DATA_DIR에 놓인 반출/분석용 파일을 읽는다.
"""

from __future__ import annotations

import io
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .catalog import Catalog, Entry
from .datahub import DataHubClient, DataHubError

TABULAR_EXT = (".csv", ".xlsx", ".xls", ".json", ".txt")
API_MAX_ROWS = 20_000  # API 한 번 적재 상한 = 100행 × 200회 호출(일일 한도 1,000회의 1/5)


class LoadError(RuntimeError):
    pass


@dataclass
class Provenance:
    entry_id: str
    title: str
    source_url: str
    method: str  # FILE | API | CENTER | DERIVED
    detail: dict[str, Any] = field(default_factory=dict)
    rows: int = 0
    total_rows: int | None = None
    loaded_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id, "title": self.title, "source_url": self.source_url,
            "method": self.method, "detail": self.detail, "rows": self.rows,
            "total_rows": self.total_rows, "loaded_at": self.loaded_at,
        }


@dataclass
class Table:
    handle: str
    df: pd.DataFrame
    provenance: Provenance
    code: str  # 이 표를 다시 만드는 pandas 코드(재현성)


# --- 파싱 -----------------------------------------------------------------

def _encoding(raw: bytes) -> str:
    """앞부분만 보고 인코딩을 고른다(수백 MB 파일을 통째로 디코딩하지 않기 위해)."""
    head = raw[:1 << 20]
    # 잘라낸 끝에 걸친 멀티바이트 문자 때문에 UTF-8 판정이 틀어지지 않도록 소수의 깨진 문자는 허용한다.
    if head.decode("utf-8-sig", errors="replace").count("\ufffd") <= 2:
        return "utf-8-sig"
    try:
        head.decode("cp949")
        return "cp949"
    except UnicodeDecodeError:
        return "utf-8-sig"


def parse_bytes(raw: bytes, name: str) -> pd.DataFrame:
    lower = name.lower()
    if lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(raw))
    enc = _encoding(raw)
    if lower.endswith(".json"):
        body = json.loads(raw.decode(enc))
        rows = body.get("data") if isinstance(body, dict) else body
        return pd.json_normalize(rows)
    first_line = raw[:4096].split(b"\n", 1)[0]
    sep = "\t" if first_line.count(b"\t") > first_line.count(b",") else ","
    df = pd.read_csv(io.BytesIO(raw), sep=sep, encoding=enc, encoding_errors="replace", dtype=str,
                     keep_default_na=False, on_bad_lines="skip")
    lines = raw.count(b"\n") + (0 if raw.endswith(b"\n") else 1) - 1
    if lines > len(df):
        df = _repair_rows(df, raw, sep, enc)
    df.attrs["skipped_rows"] = max(0, lines - len(df))
    return df


def _repair_rows(df: pd.DataFrame, raw: bytes, sep: str, enc: str) -> pd.DataFrame:
    """따옴표 없이 구분자가 들어간 행(예: '제주국제공항(대정,화순,일주서로)')을 살린다.

    이런 행을 버리면 공항 같은 핵심 정류소가 통째로 빠져 순위가 왜곡된다. 정상 행에서 숫자가 아닌
    첫 열을 찾아, 넘치는 칸을 그 열에 다시 합친다.
    """
    ncol = len(df.columns)
    text_cols = [i for i, c in enumerate(df.columns)
                 if not df[c].head(1000).str.fullmatch(r"-?[\d.,]*").all()]
    if not text_cols:
        return df
    pos, bsep = text_cols[0], sep.encode()
    fixed = []
    for line in raw.split(b"\n")[1:]:
        if line.count(bsep) <= ncol - 1:
            continue
        parts = line.rstrip(b"\r").decode(enc, errors="replace").split(sep)
        extra = len(parts) - ncol
        fixed.append(parts[:pos] + [sep.join(parts[pos:pos + extra + 1])] + parts[pos + extra + 1:])
    if not fixed:
        return df
    return pd.concat([df, pd.DataFrame(fixed, columns=df.columns)], ignore_index=True)


_NUMERIC = re.compile(r"^-?[\d,]*\.?\d+$")
_DATE_NAME = re.compile(r"date|일자|날짜|기준일|년월|ymd|yearmonth|(^|_)ym$", re.I)
_CODE_NAME = re.compile(r"(^|_)(id|cd|code)$|아이디|코드|번호|ID$", re.I)
# 통계표에서 '자료 없음'을 뜻하는 표기(KOSIS 등): 숫자 열 안에 섞여 있으면 결측으로 본다.
_MISSING_MARKS = {"-", "–", "…", "...", "x", "X", "*", "N/A", "n/a", "NA", "null"}


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """문자열로 들어온 숫자·날짜 열을 실제 타입으로 바꾼다(API 응답은 모두 문자열)."""
    df = df.copy()
    df.columns = [str(c).strip().lstrip("\ufeff") for c in df.columns]
    for col in df.columns:
        s = df[col]
        if s.dtype != object and not pd.api.types.is_string_dtype(s):
            continue
        values = s.astype(str).str.strip()
        non_empty = values[(values != "") & ~values.isin(_MISSING_MARKS)]
        if non_empty.empty:
            continue
        if _DATE_NAME.search(col) and non_empty.str.fullmatch(r"\d{8}").all():
            df[col] = pd.to_datetime(values, format="%Y%m%d", errors="coerce")
        elif _DATE_NAME.search(col) and non_empty.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
            df[col] = pd.to_datetime(values, errors="coerce")
        elif _DATE_NAME.search(col) and non_empty.str.fullmatch(r"(19|20)\d{2}(0[1-9]|1[0-2])").all():
            df[col] = pd.to_datetime(values, format="%Y%m", errors="coerce")  # 202301 같은 연월
        elif _CODE_NAME.search(col) or non_empty.str.match(r"0\d").any():
            df[col] = values  # 정류소ID·코드처럼 앞자리 0이 의미 있는 값은 숫자로 바꾸지 않는다
        elif non_empty.str.fullmatch(_NUMERIC).all():
            numeric = values.str.replace(",", "", regex=False).where(~values.isin(_MISSING_MARKS))
            df[col] = pd.to_numeric(numeric, errors="coerce")
        else:
            df[col] = values
    return df


def profile(df: pd.DataFrame, max_cols: int = 40) -> list[dict[str, Any]]:
    out = []
    for col in list(df.columns)[:max_cols]:
        s = df[col]
        info: dict[str, Any] = {"column": col, "dtype": str(s.dtype), "non_null": int(s.notna().sum())}
        if pd.api.types.is_numeric_dtype(s):
            info.update(min=_py(s.min()), max=_py(s.max()), mean=_py(round(float(s.mean()), 3)) if s.notna().any() else None)
        elif pd.api.types.is_datetime64_any_dtype(s):
            info.update(min=str(s.min())[:10], max=str(s.max())[:10])
        else:
            vc = s.value_counts()
            info.update(unique=int(len(vc)), top=[str(v) for v in vc.index[:8]])
        out.append(info)
    return out


def _py(v: Any) -> Any:
    if hasattr(v, "item"):
        return v.item()
    return v


def preview_records(df: pd.DataFrame, n: int = 15) -> list[dict[str, Any]]:
    head = df.head(n).copy()
    for col in head.columns:
        if pd.api.types.is_datetime64_any_dtype(head[col]):
            head[col] = head[col].dt.strftime("%Y-%m-%d")
    return json.loads(head.to_json(orient="records", force_ascii=False))


def hub_file(client: DataHubClient, hub_id: int, file_name: str | None, cache_dir: Path | None = None,
             detail: dict | None = None) -> tuple[bytes, dict]:
    """제주데이터허브 FILE 데이터 원본을 받는다(캐시가 있으면 재사용). 반환: (바이트, 파일 정보)."""
    detail = detail or client.dataset_detail(hub_id)
    files = [f for f in ((detail.get("dataFile") or {}).get("fileInfos") or [])
             if f["fileName"].lower().endswith(TABULAR_EXT)]
    if not files:
        raise LoadError(f"'{detail.get('title')}'에 표 형식(CSV/XLSX/JSON) 파일이 없습니다.")
    info = next((f for f in files if f["fileName"] == file_name), files[0])
    cached = cache_dir / f"hub{hub_id}_{info['id']}{Path(info['fileName']).suffix.lower()}" if cache_dir else None
    if cached and cached.is_file():
        return cached.read_bytes(), info
    raw = client.download_file(info)
    if cached:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(raw)
    return raw, info


# --- 저장소 ---------------------------------------------------------------

class DatasetStore:
    """세션 하나에서 불러온/파생한 표를 핸들(D1, R1…)로 보관한다."""

    def __init__(self, catalog: Catalog, client: DataHubClient, cache_dir: Path, center_dir: Path | None):
        self.catalog = catalog
        self.client = client
        self.cache_dir = cache_dir
        self.center_dir = center_dir
        self.tables: dict[str, Table] = {}
        self._counters = {"D": 0, "R": 0}
        self._details: dict[int, dict] = {}

    def new_handle(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return f"{prefix}{self._counters[prefix]}"

    def get(self, handle: str) -> Table:
        if handle not in self.tables:
            raise LoadError(f"없는 표 핸들입니다: {handle} (사용 가능: {', '.join(self.tables) or '없음'})")
        return self.tables[handle]

    def _entry(self, entry_id: str) -> Entry:
        entry = self.catalog.get(entry_id)
        if entry is None:
            raise LoadError(f"카탈로그에 없는 데이터 ID: {entry_id}")
        return entry

    def detail(self, entry: Entry) -> dict:
        assert entry.hub_id is not None
        if entry.hub_id not in self._details:
            self._details[entry.hub_id] = self.client.dataset_detail(entry.hub_id)
        return self._details[entry.hub_id]

    # --- 살펴보기 ----------------------------------------------------------
    def inspect(self, entry_id: str) -> dict[str, Any]:
        entry = self._entry(entry_id)
        info: dict[str, Any] = {**entry.card(), "description": entry.description, "url": entry.url}
        if entry.kind == "CENTER":
            info["local_files"] = [p.name for p in self._center_files(entry)]
            return info
        if not entry.loadable:
            return info
        d = self.detail(entry)
        files = ((d.get("dataFile") or {}).get("fileInfos") or [])
        info["files"] = [
            {"name": f["fileName"], "size": f.get("fileSize")} for f in files
            if f["fileName"].lower().endswith(TABULAR_EXT)
        ]
        api = d.get("dataApi")
        if api:
            elems = api.get("dataApiElements") or []
            info["api"] = {
                "daily_quota": api.get("quota"),
                "request_params": [
                    {"name": e["name"], "desc": e.get("description"), "required": e.get("requireYn") == "Y",
                     "example": e.get("example")} for e in elems if e.get("type") == "request"],
                "response_fields": [
                    {"name": e["name"], "desc": e.get("description")} for e in elems if e.get("type") == "response"],
                "project_key_configured": bool(self.client.project_key),
            }
        sample = d.get("csvData") or []
        if sample:
            info["preview"] = {"columns": sample[0], "rows": sample[1:6]}
        return info

    # --- 불러오기 ----------------------------------------------------------
    def load(self, entry_id: str, file_name: str | None = None, api_params: dict[str, str] | None = None,
             max_rows: int = API_MAX_ROWS) -> Table:
        entry = self._entry(entry_id)
        if entry.kind == "CENTER":
            df, prov, code = self._load_center(entry, file_name)
        elif "API" in entry.kind.split("+") and (api_params is not None or "FILE" not in entry.kind):
            df, prov, code = self._load_api(entry, api_params or {}, max_rows)
        elif "FILE" in entry.kind.split("+"):
            df, prov, code = self._load_file(entry, file_name)
        else:
            raise LoadError(f"'{entry.title}'은(는) 외부 링크 데이터라 자동으로 불러올 수 없습니다: {entry.url}")
        skipped = int(df.attrs.get("skipped_rows", 0))
        df = normalize(df)
        prov.rows = len(df)
        if skipped:
            prov.detail["skipped_rows"] = skipped
        prov.loaded_at = time.strftime("%Y-%m-%d %H:%M")
        handle = self.new_handle("D")
        code = code.replace("__H__", handle)
        table = Table(handle, df, prov, code + f"\n{handle} = normalize({handle})")
        self.tables[handle] = table
        return table

    def _load_file(self, entry: Entry, file_name: str | None):
        assert entry.hub_id is not None
        raw, info = hub_file(self.client, entry.hub_id, file_name, self.cache_dir, self.detail(entry))
        df = parse_bytes(raw, info["fileName"])
        prov = Provenance(entry.id, entry.title, entry.url, "FILE", {"file": info["fileName"]})
        code = (f"# 출처: {entry.title} ({entry.url})\n"
                f"_raw, _info = hub_file(CLIENT, {entry.hub_id}, {info['fileName']!r}, CACHE)\n"
                "__H__ = parse_bytes(_raw, _info['fileName'])")
        return df, prov, code

    def _load_api(self, entry: Entry, params: dict[str, str], max_rows: int):
        # 모델이 ' startDate'처럼 공백 붙은 키를 함께 보내면 같은 변수가 두 번 기록된다 → 키·값 공백 정리.
        params = {str(k).strip(): str(v).strip() for k, v in params.items()}
        d = self.detail(entry)
        api = d.get("dataApi") or {}
        required = [e["name"] for e in api.get("dataApiElements") or []
                    if e.get("type") == "request" and e.get("requireYn") == "Y"]
        missing = [p for p in required if not str(params.get(p, "")).strip()]
        if missing:
            raise LoadError(f"필수 요청 변수 누락: {', '.join(missing)} — inspect_dataset의 request_params를 보세요.")
        try:
            rows, total = self.client.call_api(d["dataKey"], params, max_rows)
        except DataHubError as exc:
            raise LoadError(str(exc)) from exc
        df = pd.DataFrame(rows)
        prov = Provenance(entry.id, entry.title, entry.url, "API", {"params": params}, total_rows=total)
        code = (f"# 출처: {entry.title} ({entry.url})\n"
                f"rows, total = CLIENT.call_api({d['dataKey']!r}, {params!r}, {max_rows})\n"
                "__H__ = pd.DataFrame(rows)")
        return df, prov, code

    def _center_files(self, entry: Entry) -> list[Path]:
        if not self.center_dir or not self.center_dir.is_dir():
            return []
        table = re.search(r"테이블 (\S+?)\)", entry.description)
        keys = {entry.title.replace(" ", "")} | ({table.group(1)} if table else set())
        return sorted(p for p in self.center_dir.iterdir()
                      if p.suffix.lower() in TABULAR_EXT and any(k in p.name.replace(" ", "") for k in keys))

    def _load_center(self, entry: Entry, file_name: str | None):
        files = self._center_files(entry)
        if not files:
            where = self.center_dir or "(CENTER_DATA_DIR 미설정)"
            raise LoadError(
                f"'{entry.title}'은(는) 제주빅데이터센터 방문 데이터입니다. 센터 PC의 {where} 폴더에 "
                f"'{entry.title}' 또는 테이블명이 들어간 CSV/XLSX를 두면 분석할 수 있습니다.")
        path = next((p for p in files if p.name == file_name), files[0])
        df = parse_bytes(path.read_bytes(), path.name)
        prov = Provenance(entry.id, entry.title, entry.url, "CENTER", {"file": path.name})
        code = f"# 출처: 제주빅데이터센터 {entry.title}\n__H__ = parse_bytes(open(r'{path.as_posix()}', 'rb').read(), {path.name!r})"
        return df, prov, code
