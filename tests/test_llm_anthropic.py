"""The Claude adapter, tested without the network or an API key.

A fake client stands in for the SDK. These cover the parts that carry real
logic — retries, refusals, and the promise that nothing unvalidated escapes.
The live API call itself is not exercised here; that needs a key and costs
money, and is noted as untested in the roadmap.
"""

import anthropic
import httpx2
import pytest
from pydantic import BaseModel

from outreach.adapters.llm_anthropic import AnthropicLLM
from outreach.ports.llm import LLMError


class Answer(BaseModel):
    reply: str


class Other(BaseModel):
    something_else: str


def _status_error(code: int) -> anthropic.APIStatusError:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIStatusError(
        "boom", response=httpx2.Response(code, request=request), body=None
    )


def _connection_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )


class FakeMessage:
    def __init__(self, parsed=None, stop_reason="end_turn", stop_details=None):
        self.parsed_output = parsed
        self.stop_reason = stop_reason
        self.stop_details = stop_details


class FakeClient:
    """Replays a queue of outcomes. An Exception is raised; anything else is
    returned."""

    def __init__(self, *outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0
        self.last_kwargs = None
        outer = self

        class Messages:
            def parse(self, **kwargs):
                outer.calls += 1
                outer.last_kwargs = kwargs
                outcome = outer._outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome

        self.messages = Messages()


@pytest.fixture
def llm_with(settings):
    def build(*outcomes):
        return AnthropicLLM(settings, client=FakeClient(*outcomes))

    return build


# --- the happy path ---------------------------------------------------------


def test_a_validated_object_comes_back(llm_with):
    llm = llm_with(FakeMessage(parsed=Answer(reply="hello")))
    assert llm.generate(prompt="hi", schema=Answer).reply == "hello"


def test_the_model_comes_from_configuration(llm_with, settings):
    llm = llm_with(FakeMessage(parsed=Answer(reply="x")))
    llm.generate(prompt="hi", schema=Answer)
    assert llm._client.last_kwargs["model"] == settings.anthropic_model == "claude-opus-5"


def test_the_schema_is_passed_to_the_api_not_just_checked_afterwards(llm_with):
    """Constraining the output is better than validating it after the fact."""
    llm = llm_with(FakeMessage(parsed=Answer(reply="x")))
    llm.generate(prompt="hi", schema=Answer)
    assert llm._client.last_kwargs["output_config"]["format"] is Answer


# --- nothing unvalidated escapes --------------------------------------------


def test_an_empty_response_raises_rather_than_returning_none(llm_with):
    llm = llm_with(FakeMessage(parsed=None))
    with pytest.raises(LLMError, match="nothing that matched"):
        llm.generate(prompt="hi", schema=Answer)


def test_the_wrong_shape_raises(llm_with):
    llm = llm_with(FakeMessage(parsed=Other(something_else="x")))
    with pytest.raises(LLMError, match="Expected Answer"):
        llm.generate(prompt="hi", schema=Answer)


def test_a_refusal_is_reported_not_silently_empty(llm_with):
    llm = llm_with(FakeMessage(parsed=None, stop_reason="refusal", stop_details="cyber"))
    with pytest.raises(LLMError, match="declined"):
        llm.generate(prompt="hi", schema=Answer)


# --- retries ----------------------------------------------------------------


def test_a_rate_limit_is_retried_and_can_succeed(llm_with, monkeypatch):
    monkeypatch.setattr("outreach.adapters.llm_anthropic.time.sleep", lambda _: None)
    llm = llm_with(_status_error(429), FakeMessage(parsed=Answer(reply="second try")))
    assert llm.generate(prompt="hi", schema=Answer).reply == "second try"
    assert llm._client.calls == 2


def test_a_dropped_connection_is_retried(llm_with, monkeypatch):
    monkeypatch.setattr("outreach.adapters.llm_anthropic.time.sleep", lambda _: None)
    llm = llm_with(_connection_error(), FakeMessage(parsed=Answer(reply="ok")))
    assert llm.generate(prompt="hi", schema=Answer).reply == "ok"


def test_a_bad_request_is_not_retried(llm_with):
    """A 400 fails identically every time. Retrying it only spends money."""
    llm = llm_with(_status_error(400))
    with pytest.raises(LLMError, match="refused the request"):
        llm.generate(prompt="hi", schema=Answer)
    assert llm._client.calls == 1


def test_it_gives_up_rather_than_retrying_forever(llm_with, monkeypatch):
    monkeypatch.setattr("outreach.adapters.llm_anthropic.time.sleep", lambda _: None)
    llm = llm_with(_status_error(503), _status_error(503), _status_error(503))
    with pytest.raises(LLMError, match="unreachable after 3 attempts"):
        llm.generate(prompt="hi", schema=Answer)
    assert llm._client.calls == 3


def test_a_missing_api_key_fails_at_construction_not_mid_campaign(settings):
    from outreach.config import ConfigError, load_settings

    with pytest.raises(ConfigError, match="OUTREACH_ANTHROPIC_API_KEY"):
        AnthropicLLM(load_settings(_env_file=None), client=FakeClient())
