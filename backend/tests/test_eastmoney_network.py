from __future__ import annotations

from app.services import data_provider


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"data": {"total": 1, "diff": [{"f12": "000001"}]}}


class IPv6ThenAutomaticRequests:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def get(self, _url: str, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise ConnectionError("IPv6 unavailable in this environment")
        return FakeResponse()


def test_eastmoney_page_prefers_ipv6_then_preserves_automatic_fallback(monkeypatch) -> None:
    requests = IPv6ThenAutomaticRequests()
    monkeypatch.setattr(data_provider.time, "sleep", lambda *_args: None)

    payload = data_provider.fetch_eastmoney_page(
        requests,
        "https://push2.eastmoney.com/api/qt/clist/get",
        {"pn": 1},
        page=1,
    )

    assert payload["data"]["total"] == 1
    assert "curl_options" in requests.calls[0]
    assert "curl_options" not in requests.calls[1]
