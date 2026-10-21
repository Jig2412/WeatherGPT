"""Tests for the chat plumbing.

These cover the parts of the assistant that run *before* Claude is involved:
the tool loop, the card builder, the suggestion/action builders and the
response contract. The Claude client itself is stubbed, so these tests do not
need an API key and never make a model call.

The tests marked ``network`` do hit the real keyless providers
(Open-Meteo, RainViewer, NWS). Run them with ``pytest -m network``.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.schemas import ChatCard, LocationInfo  # noqa: E402
from app.services import ai  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeBlock:
    """Stands in for an Anthropic content block."""

    def __init__(self, **kwargs: Any) -> None:
        self.type = kwargs.get("type", "text")
        self.text = kwargs.get("text", "")
        self.name = kwargs.get("name")
        self.input = kwargs.get("input")
        self.id = kwargs.get("id")

    def model_dump(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "type": self.type,
            "text": self.text,
            "name": self.name,
            "input": self.input,
            "id": self.id,
        }


class FakeUsage:
    input_tokens = 42
    output_tokens = 17


class FakeResponse:
    def __init__(self, content: list[FakeBlock], stop_reason: str) -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.model = "claude-test-model"
        self.usage = FakeUsage()


class FakeMessages:
    """Returns a scripted sequence of Anthropic responses."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        return self._responses[len(self.calls) - 1]


class FakeClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.messages = FakeMessages(responses)


@pytest.fixture
def scripted_client(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    """Install a fake Anthropic client and pretend a key is configured."""
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test", raising=False)

    client = FakeClient([])
    monkeypatch.setattr(ai, "AsyncAnthropic", lambda **kwargs: client)
    return client


@pytest.fixture
def fake_tool(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace the tool executor with a deterministic stub.

    Returns the list of calls that were made, so tests can assert on which
    tools the model reached for.
    """
    calls: list[dict[str, Any]] = []

    async def _stub(name: str, payload: dict[str, Any], default_units: str) -> dict[str, Any]:
        calls.append({"name": name, "payload": payload})
        if name == "get_current_weather":
            return {
                "model": {"current": {"temperature": 21.5}, "units": default_units},
                "card": ChatCard(
                    kind="current",
                    title="Current conditions · Testville",
                    location="Testville",
                    data={"current": {"temperature": 21.5}},
                ),
                "location": LocationInfo(
                    name="Testville", latitude=10.0, longitude=20.0, country="Nowhere"
                ),
            }
        return {"model": {"ok": True}, "card": None, "location": None}

    monkeypatch.setattr(ai, "_execute_tool", _stub)
    return calls


# ---------------------------------------------------------------------------
# Tool loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_chat_collects_cards_suggestions_and_actions(
    scripted_client: FakeClient, fake_tool: list[dict[str, Any]]
) -> None:
    scripted_client.messages._responses = [
        FakeResponse(
            [
                FakeBlock(
                    type="tool_use",
                    id="toolu_1",
                    name="get_current_weather",
                    input={"location": "Testville"},
                )
            ],
            stop_reason="tool_use",
        ),
        FakeResponse([FakeBlock(type="text", text="It is 21.5 degrees in Testville.")], "end_turn"),
    ]

    result = await ai.run_chat([{"role": "user", "content": "How is it?"}])

    assert result.reply == "It is 21.5 degrees in Testville."
    assert result.tools_used == ["get_current_weather"]
    assert [card.kind for card in result.cards] == ["current"]
    assert result.cards[0].title == "Current conditions · Testville"
    assert result.suggestions, "the assistant should offer follow-up questions"
    assert result.actions, "the assistant should offer action buttons"
    assert result.focus_location is not None
    assert result.focus_location.name == "Testville"


@pytest.mark.asyncio
async def test_run_chat_passes_the_tool_result_back_to_the_model(
    scripted_client: FakeClient, fake_tool: list[dict[str, Any]]
) -> None:
    scripted_client.messages._responses = [
        FakeResponse(
            [FakeBlock(type="tool_use", id="toolu_1", name="get_current_weather", input={})],
            stop_reason="tool_use",
        ),
        FakeResponse([FakeBlock(type="text", text="done")], "end_turn"),
    ]

    await ai.run_chat([{"role": "user", "content": "weather?"}])

    assert len(scripted_client.messages.calls) == 2
    second_call = scripted_client.messages.calls[1]
    conversation = second_call["messages"]
    # assistant tool_use turn, then the user tool_result turn
    assert conversation[-2]["role"] == "assistant"
    assert conversation[-1]["role"] == "user"
    assert conversation[-1]["content"][0]["type"] == "tool_result"
    assert conversation[-1]["content"][0]["tool_use_id"] == "toolu_1"


@pytest.mark.asyncio
async def test_run_chat_reports_a_failing_tool_without_crashing(
    scripted_client: FakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(name: str, payload: dict[str, Any], default_units: str) -> dict[str, Any]:
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(ai, "_execute_tool", _boom)

    scripted_client.messages._responses = [
        FakeResponse(
            [FakeBlock(type="tool_use", id="toolu_1", name="get_current_weather", input={})],
            stop_reason="tool_use",
        ),
        FakeResponse([FakeBlock(type="text", text="I could not reach the provider.")], "end_turn"),
    ]

    result = await ai.run_chat([{"role": "user", "content": "weather?"}])

    assert "could not reach" in result.reply
    # The error must be visible to the model, not swallowed.
    tool_result = scripted_client.messages.calls[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert "upstream exploded" in tool_result["content"]


@pytest.mark.asyncio
async def test_run_chat_requires_a_configured_key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", None, raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)

    with pytest.raises(Exception) as excinfo:
        await ai.run_chat([{"role": "user", "content": "hi"}])
    assert "ANTHROPIC_API_KEY" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Suggestion / action builders
# ---------------------------------------------------------------------------


def test_suggestions_are_grounded_in_the_tools_that_were_used() -> None:
    suggestions = ai._build_suggestions(
        ["get_current_weather", "get_hourly_forecast"], "New Delhi"
    )
    assert suggestions
    assert all("New Delhi" in item for item in suggestions)
    assert len(suggestions) == len(set(suggestions)), "suggestions must be unique"


def test_suggestions_fall_back_when_no_weather_tool_was_used() -> None:
    suggestions = ai._build_suggestions(["search_locations"], "Berlin")
    assert suggestions
    assert all("Berlin" in item for item in suggestions)


def test_actions_point_at_the_relevant_screens() -> None:
    actions = ai._build_actions(["get_radar_status", "get_official_alerts"])
    values = {action.value for action in actions}
    assert "/maps" in values
    assert "/alerts" in values
    assert all(action.kind == "navigate" for action in actions)


# ---------------------------------------------------------------------------
# Live provider checks (network)
# ---------------------------------------------------------------------------


@pytest.mark.network
@pytest.mark.asyncio
async def test_execute_tool_builds_a_card_from_live_data() -> None:
    outcome = await ai._execute_tool("get_current_weather", {"location": "New Delhi"}, "metric")

    card = outcome["card"]
    assert card is not None
    assert card.kind == "current"
    data = card.data
    assert data["current"]["temperature"] is not None
    assert data["provider"]["name"] == "Open-Meteo"
    # Model analysis must never be presented as a live observation.
    assert data["provider"]["is_live_observation"] is False
    assert outcome["location"] is not None


@pytest.mark.network
@pytest.mark.asyncio
async def test_execute_tool_reports_unsupported_alert_coverage() -> None:
    outcome = await ai._execute_tool("get_official_alerts", {"location": "New Delhi"}, "metric")

    card = outcome["card"]
    assert card is not None
    assert card.kind == "alerts"
    assert card.data["supported"] is False
    assert card.data["coverage_note"]
