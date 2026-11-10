"""제주데이터허브(jejudatahub.net) HTTP 클라이언트.

- 카탈로그·상세 메타데이터: 사이트가 쓰는 공개 JSON API(로그인 불필요).
- FILE 데이터: 사이트의 파일 다운로드 경로(로그인 불필요).
- API 데이터: 사용자 본인의 프로젝트 키(projectKey)로 open.jejudatahub.net 프록시 호출.
"""

from __future__ import annotations

from typing import Any

import httpx

HUB = "https://jejudatahub.net"
OPEN_API = "https://open.jejudatahub.net/api/proxy"
USER_AGENT = "jeju-data-agent/0.1 (+https://jejudatahub.net)"
# API 프록시는 한 번에 최대 100행만 준다(실측: limit 150 이상은 HTTP 500). 일일 호출 한도(1,000~3,000회)도
# 이 요청 수로 차감되므로 적재 상한은 datasets.API_MAX_ROWS로 따로 묶는다.
API_PAGE_SIZE = 100


class DataHubError(RuntimeError):
    pass


class DataHubClient:
    def __init__(self, project_key: str | None = None, timeout: float = 60.0):
        self.project_key = project_key
        self._http = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*"},
            follow_redirects=True,
        )

    def _json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        resp = self._http.get(url, params=params)
        if resp.status_code != 200:
            hint = ""
            if url.startswith(OPEN_API) and resp.status_code in (401, 403):
                hint = (" — 프로젝트 키가 맞는지, 이 데이터를 제주데이터허브에서 '프로젝트 담기' 했는지, "
                        "일일 호출 한도를 넘지 않았는지 확인하세요.")
            raise DataHubError(f"HTTP {resp.status_code}: {resp.text[:200]}{hint}")
        return resp.json()

    # --- 카탈로그 -------------------------------------------------------
    def list_datasets(self, data_type: str) -> list[dict[str, Any]]:
        """data_type: API | FILE | LINK. 한 번에 전체 목록을 받는다(1,259건 기준 수 초)."""
        params = {
            "includedKeywords": "", "excludedKeywords": "", "categories": "", "userId": "",
            "dataType": data_type, "orderBy": "createAt", "authYn": "false",
            "autoUpdateYn": "false", "keyword": "", "keywordOrTagFlag": "keyword",
            "isPaging": "true", "start": 0, "pageNumber": 1, "length": 5000,
        }
        body = self._json(f"{HUB}/api/data", params)
        return list(body.get("data") or [])

    def center_tables(self) -> list[dict[str, Any]]:
        """제주빅데이터센터 방문 데이터 목록(반출 가능 여부 포함)."""
        body = self._json(f"{HUB}/api/ndapTable/list")
        return list(body.get("data") or [])

    def dataset_detail(self, dataset_id: int) -> dict[str, Any]:
        # viewCount 파라미터를 빼면 사이트 조회수를 올리지 않는다.
        return self._json(f"{HUB}/api/data/view", {"id": dataset_id, "userId": ""})

    # --- 원천 데이터 -----------------------------------------------------
    def download_file(self, info: dict[str, Any]) -> bytes:
        params = {
            "id": info["id"], "fileId": info["fileId"], "fileName": info["fileName"],
            "fileSize": info.get("fileSize", ""), "contentType": info.get("contentType", ""),
            "saveFileName": info["saveFileName"],
        }
        resp = self._http.get(f"{HUB}/api/file/test-download", params=params)
        if resp.status_code != 200 or not resp.content:
            raise DataHubError(f"파일 다운로드 실패({info['fileName']}): HTTP {resp.status_code}")
        return resp.content

    def call_api(self, data_key: str, params: dict[str, str], max_rows: int) -> tuple[list[dict], int]:
        """API 데이터를 페이지 단위로 모은다. 반환: (행 목록, 서버가 알려준 전체 건수)."""
        if not self.project_key:
            raise DataHubError(
                "API 데이터는 제주데이터허브 프로젝트 키가 필요합니다. "
                "README의 'API 키 발급' 절차대로 JEJU_DATAHUB_PROJECT_KEY를 설정하세요."
            )
        rows: list[dict] = []
        total = 0
        page = 1
        limit = min(API_PAGE_SIZE, max_rows)
        while len(rows) < max_rows:
            body = self._json(
                f"{OPEN_API}/{data_key}/{self.project_key}",
                {**params, "number": page, "limit": limit},
            )
            if not isinstance(body, dict) or "data" not in body:
                raise DataHubError(f"예상과 다른 API 응답: {str(body)[:200]}")
            data = body.get("data") or []
            total = int(body.get("totCnt") or len(data))
            rows.extend(data)
            if not body.get("hasMore") or not data:
                break
            page += 1
        return rows[:max_rows], total
