"""Test fixtures: a fake tool-calling chat model so tests never hit a real LLM."""

import json
import os

# Configure before anything imports server/agent settings.
os.environ.setdefault("OTEL_ENABLED", "false")
os.environ.setdefault("LANGFUSE_ENABLED", "false")
os.environ.setdefault("DEV_UI_ENABLED", "true")
os.environ.setdefault("LLM_MODEL", "fake")
os.environ["AUTH_TOKEN"] = ""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


class FakeToolChatModel(BaseChatModel):
    """Replies with scripted AIMessages (text and/or tool calls); streams word by word."""

    messages: Iterator[AIMessage]

    @property
    def _llm_type(self) -> str:
        return "fake-tool-chat"

    def bind_tools(self, tools: Any, **kwargs: Any) -> BaseChatModel:
        return self

    def _generate(
        self, messages: list[BaseMessage], stop=None, run_manager=None, **kw
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=next(self.messages))])

    def _stream(self, messages: list[BaseMessage], stop=None, run_manager=None, **kw):
        reply = next(self.messages)
        words = reply.content.split(" ") if reply.content else []
        for i, word in enumerate(words):
            chunk = ChatGenerationChunk(
                message=AIMessageChunk(content=word if i == 0 else " " + word)
            )
            if run_manager:
                run_manager.on_llm_new_token(chunk.text, chunk=chunk)
            yield chunk
        if reply.tool_calls or not words:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": tc["name"],
                            "args": json.dumps(tc["args"]),
                            "id": tc["id"],
                            "index": i,
                        }
                        for i, tc in enumerate(reply.tool_calls)
                    ],
                )
            )


def tool_call(name: str, args: dict, call_id: str = "call_1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


@pytest.fixture
def script_llm(monkeypatch) -> Callable[..., None]:
    """script_llm(msg1, msg2, ...) - the agent's LLM replies with these, in order."""

    def _script(*replies: AIMessage | str) -> None:
        messages: Iterator[AIMessage] = iter(
            r if isinstance(r, AIMessage) else AIMessage(content=r) for r in replies
        )
        monkeypatch.setattr("agent.llm.get_llm", lambda: FakeToolChatModel(messages=messages))

    return _script


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch) -> None:
    """Never build a real model in tests (tests that need replies use script_llm)."""
    monkeypatch.setattr("agent.llm.get_llm", lambda: FakeToolChatModel(messages=iter(())))


@pytest.fixture(autouse=True)
def _in_memory_checkpointer(monkeypatch) -> None:
    """Unit tests use in-memory conversation memory, whatever the configured backend."""
    from contextlib import asynccontextmanager

    from langgraph.checkpoint.memory import InMemorySaver

    @asynccontextmanager
    async def _open():
        yield InMemorySaver()

    monkeypatch.setattr("agent.main.open_checkpointer", _open)
