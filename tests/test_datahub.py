import httpx
import pytest

from jeju_data_agent.datahub import DataHubClient, DataHubError


def _client(handler, key="KEY"):
    client = DataHubClient(project_key=key)
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def test_call_api_follows_pages_until_has_more_false():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["number"])
        seen.append((request.url.path, page, request.url.params["startDate"]))
        rows = [{"baseDate": f"2024010{page}", "v": str(page)}]
        return httpx.Response(200, json={"totCnt": 3, "hasMore": page < 3, "data": rows})

    rows, total = _client(handler).call_api("DATAKEY", {"startDate": "20240101"}, max_rows=100)
    assert total == 3
    assert [r["v"] for r in rows] == ["1", "2", "3"]
    assert seen[0][0] == "/api/proxy/DATAKEY/KEY"


def test_call_api_stops_at_max_rows():
    def handler(request: httpx.Request) -> httpx.Response:
        limit = int(request.url.params["limit"])
        return httpx.Response(200, json={"totCnt": 10_000, "hasMore": True, "data": [{"v": "1"}] * limit})

    rows, total = _client(handler).call_api("K", {}, max_rows=250)
    assert len(rows) == 250 and total == 10_000


def test_call_api_without_project_key_explains_how_to_get_one():
    with pytest.raises(DataHubError, match="프로젝트 키"):
        _client(lambda r: httpx.Response(200), key=None).call_api("K", {}, max_rows=10)


def test_call_api_surfaces_server_rejection():
    def handler(request):
        return httpx.Response(403, text="Forbidden")

    with pytest.raises(DataHubError, match="403"):
        _client(handler).call_api("K", {}, max_rows=10)
