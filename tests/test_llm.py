import pytest

from novel_notes.llm import LLMClient, LLMConfig, LLMError


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


def test_extract_content():
    client = LLMClient(LLMConfig(base_url="http://example.com/v1", api_key="k"))
    resp = FakeResponse(200, {"choices": [{"message": {"content": " 笔记内容 "}}]})
    assert client._extract_content(resp) == "笔记内容"


def test_retry_then_success(monkeypatch):
    responses = [
        FakeResponse(503, {"error": "busy"}),
        FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]}),
    ]
    session = FakeSession(responses)
    client = LLMClient(LLMConfig(base_url="http://example.com/v1", api_key="k", max_retries=3))
    monkeypatch.setattr(client, "session", session)
    assert client.complete("s", "u") == "ok"
    assert session.calls == 2


def test_fail_after_retries(monkeypatch):
    responses = [
        FakeResponse(503, {"error": "busy"}),
        FakeResponse(503, {"error": "busy"}),
    ]
    session = FakeSession(responses)
    client = LLMClient(LLMConfig(base_url="http://example.com/v1", api_key="k", max_retries=1))
    monkeypatch.setattr(client, "session", session)
    with pytest.raises(LLMError):
        client.complete("s", "u")
    assert session.calls == 2


def test_400_not_retried(monkeypatch):
    responses = [FakeResponse(400, {"error": "bad request"})]
    session = FakeSession(responses)
    client = LLMClient(LLMConfig(base_url="http://example.com/v1", api_key="k", max_retries=3))
    monkeypatch.setattr(client, "session", session)
    with pytest.raises(LLMError):
        client.complete("s", "u")
    assert session.calls == 1
