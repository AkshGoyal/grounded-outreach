"""The OpenRouter adapter, without the network or a key.

The interesting part is not the happy path — it is the two OpenRouter-specific
traps: a provider that ignores the schema and returns prose, and Pydantic's
optional fields being rejected by strict mode.
"""

import httpx2
import openai
import pytest
from pydantic import BaseModel

from outreach.adapters.llm_openrouter import OpenRouterLLM, _strict_schema
from outreach.core.drafting import Draft
from outreach.ports.llm import LLMError


class Answer(BaseModel):
    reply: str
    note: str | None = None


def _status_error(code: int) -> openai.APIStatusError:
    request = httpx2.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    return openai.APIStatusError("boom", response=httpx2.Response(code, request=request), body=None)


class FakeCompletion:
    def __init__(self, content):
        message = type("M", (), {"content": content})()
        self.choices = [type("C", (), {"message": message})()]


class FakeClient:
    def __init__(self, *outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0
        self.last_request = None
        outer = self

        class Completions:
            def create(self, **kwargs):
                outer.calls += 1
                outer.last_request = kwargs
                outcome = outer._outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome

        self.chat = type("Chat", (), {"completions": Completions()})()


@pytest.fixture
def llm_with(settings):
    ready = settings.model_copy(
        update={"openrouter_api_key": "sk-or-test", "llm_model": "some/model"}
    )

    def build(*outcomes):
        return OpenRouterLLM(ready, client=FakeClient(*outcomes))

    return build


# --- the schema rewrite -----------------------------------------------------


def test_optional_fields_become_required_and_nullable():
    """Strict mode rejects a property that is merely absent. Pydantic marks
    optional fields as not-required, so the schema has to be rewritten."""
    schema = _strict_schema(Draft)
    sentence = schema["$defs"]["DraftSentence"]
    assert sentence["required"] == ["text", "cites"]
    assert {"type": "null"} in sentence["properties"]["cites"]["anyOf"]


def test_no_unexpected_keys_are_allowed_anywhere():
    schema = _strict_schema(Draft)
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["DraftSentence"]["additionalProperties"] is False


# --- the routing trap -------------------------------------------------------


def test_it_only_routes_to_providers_that_enforce_the_schema(llm_with):
    """The same model is served by several providers, and some treat a schema
    as a suggestion. Without this the failure looks like a model problem."""
    llm = llm_with(FakeCompletion('{"reply": "hi"}'))
    llm.generate(prompt="x", schema=Answer)
    assert llm._client.last_request["extra_body"]["provider"]["require_parameters"] is True


def test_the_schema_is_sent_as_strict(llm_with):
    llm = llm_with(FakeCompletion('{"reply": "hi"}'))
    llm.generate(prompt="x", schema=Answer)
    fmt = llm._client.last_request["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True


def test_the_model_comes_from_configuration(llm_with):
    llm = llm_with(FakeCompletion('{"reply": "hi"}'))
    llm.generate(prompt="x", schema=Answer)
    assert llm._client.last_request["model"] == "some/model"


# --- nothing unvalidated escapes --------------------------------------------


def test_a_validated_object_comes_back(llm_with):
    llm = llm_with(FakeCompletion('{"reply": "hello", "note": null}'))
    assert llm.generate(prompt="x", schema=Answer).reply == "hello"


def test_prose_instead_of_json_is_an_error_naming_the_likely_cause(llm_with):
    """This is what a provider that ignored the schema actually returns."""
    llm = llm_with(FakeCompletion("Sure! Here is your email:\n\nDear sir,"))
    with pytest.raises(LLMError) as exc:
        llm.generate(prompt="x", schema=Answer)
    assert "not a valid Answer" in str(exc.value)


def test_an_empty_response_points_at_the_provider(llm_with):
    llm = llm_with(FakeCompletion(""))
    with pytest.raises(LLMError, match="may not enforce JSON schemas"):
        llm.generate(prompt="x", schema=Answer)


def test_valid_json_of_the_wrong_shape_is_rejected(llm_with):
    llm = llm_with(FakeCompletion('{"something_else": 1}'))
    with pytest.raises(LLMError, match="not a valid Answer"):
        llm.generate(prompt="x", schema=Answer)


# --- retries ----------------------------------------------------------------


def test_a_rate_limit_is_retried(llm_with, monkeypatch):
    monkeypatch.setattr("outreach.adapters.llm_openrouter.time.sleep", lambda _: None)
    llm = llm_with(_status_error(429), FakeCompletion('{"reply": "second"}'))
    assert llm.generate(prompt="x", schema=Answer).reply == "second"
    assert llm._client.calls == 2


def test_a_bad_request_is_not_retried(llm_with):
    llm = llm_with(_status_error(400))
    with pytest.raises(LLMError, match="refused the request"):
        llm.generate(prompt="x", schema=Answer)
    assert llm._client.calls == 1


def test_a_missing_key_fails_before_any_call(settings):
    from outreach.config import ConfigError

    with pytest.raises(ConfigError, match="OUTREACH_OPENROUTER_API_KEY"):
        OpenRouterLLM(settings.model_copy(update={"openrouter_api_key": None}))
