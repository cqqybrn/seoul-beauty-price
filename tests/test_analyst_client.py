import json
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from pipeline.analyst.client import AnalystAPIError, AnalystClient, NoRedirect, check_connection
from pipeline.config import Settings


def config():
    return Settings(
        _env_file=None,
        analyst_provider="openai_compatible",
        analyst_base_url="https://gateway.example.org/v1",
        analyst_api_key="test-secret",
        model_analyst="gemini-4-hydrogen-xhigh",
    )


def response(**updates):
    return {
        "model": "gemini-4-hydrogen-xhigh",
        "choices": [
            {"message": {"role": "assistant", "content": '{"ok":true}'}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
        **updates,
    }


def test_gateway_completion_has_no_implicit_tools_or_retries():
    transport = Mock(return_value=response())
    client = AnalystClient(config(), transport=transport)
    result = client.complete([{"role": "user", "content": "hello"}])
    args = transport.call_args.args
    assert args[0] == "https://gateway.example.org/v1/chat/completions"
    assert args[1]["model"] == "gemini-4-hydrogen-xhigh"
    assert "tools" not in args[1]
    assert args[2] == "test-secret"
    assert result.total_tokens == 25
    transport.assert_called_once()


def test_tool_calls_are_returned_not_executed():
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "run_sql", "arguments": '{"query":"SELECT * FROM v_offers"}'},
            }
        ],
    }
    transport = Mock(
        return_value=response(choices=[{"message": message, "finish_reason": "tool_calls"}])
    )
    result = AnalystClient(config(), transport=transport).complete(
        [{"role": "user", "content": "inspect"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "run_sql",
                    "parameters": {"type": "object"},
                },
            }
        ],
    )
    assert result.message == message
    transport.assert_called_once()


@pytest.mark.parametrize(
    "bad",
    [
        {},
        response(usage={}),
        response(choices=[]),
        response(
            usage={
                "prompt_tokens": 1,
                "completion_tokens": 2,
                "total_tokens": 0,
            }
        ),
    ],
)
def test_missing_usage_or_message_rejected(bad):
    with pytest.raises(AnalystAPIError):
        AnalystClient(config(), transport=Mock(return_value=bad)).complete([{"role": "user"}])


def test_budget_limit_rejected():
    settings = config().model_copy(update={"analyst_token_limit": 24})
    with pytest.raises(AnalystAPIError, match="budget"):
        AnalystClient(settings, transport=Mock(return_value=response())).complete(
            [{"role": "user"}]
        )


def test_gateway_secrets_hidden_and_bad_urls_rejected():
    assert "test-secret" not in repr(config())
    for url in [
        "http://gateway.example.org/v1",
        "https://user:pw@gateway.example.org/v1",
        "https://gateway.example.org/v1?key=secret",
    ]:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, analyst_base_url=url)


def test_redirect_not_followed():
    assert NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid") is None


def test_check_connection_sanitized(monkeypatch):
    monkeypatch.setattr("pipeline.analyst.client._http_post", Mock(return_value=response()))
    result = check_connection(config())
    assert result["ok"]
    assert "secret" not in json.dumps(result)


def test_bad_check_content_rejected(monkeypatch):
    bad = response(
        choices=[{"message": {"role": "assistant", "content": "not json"}, "finish_reason": "stop"}]
    )
    monkeypatch.setattr("pipeline.analyst.client._http_post", Mock(return_value=bad))
    with pytest.raises(AnalystAPIError, match="expected JSON"):
        check_connection(config())
