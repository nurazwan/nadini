"""A2A adapter: exposes `agent.main.stream_events` as an A2A (JSON-RPC) agent.

- Streams the answer as artifact chunks (append=True) for streaming clients, then
  replaces it with the full answer (append=False, last_chunk=True).
- Reports tool calls as `working` status updates (event JSON in metadata).
- contextId == conversation memory thread.
"""

import logging

from a2a.helpers import new_task_from_user_message, new_text_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    HTTPAuthSecurityScheme,
    Role,
    SecurityRequirement,
    SecurityScheme,
    TaskState,
)
from a2a.utils.errors import UnsupportedOperationError
from starlette.routing import Route

from agent import main as agent_main
from agent.settings import get_settings as get_agent_settings
from server.config import ServerSettings

log = logging.getLogger(__name__)

ANSWER_ARTIFACT = "answer"


class AgentRunner(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work()

        artifact_id = f"{task.id}-{ANSWER_ARTIFACT}"
        streaming = False
        try:
            async for event in agent_main.stream_events(context.get_user_input(), task.context_id):
                match event["type"]:
                    case "token":
                        await updater.add_artifact(
                            [new_text_part(event["data"])],
                            artifact_id=artifact_id,
                            name=ANSWER_ARTIFACT,
                            append=streaming,
                        )
                        streaming = True
                    case "tool_call" | "tool_result":
                        verb = "Calling" if event["type"] == "tool_call" else "Finished"
                        status = new_text_message(
                            f"{verb} tool `{event.get('name')}`", role=Role.ROLE_AGENT
                        )
                        status.metadata.update({"agent_event": event})
                        await updater.update_status(TaskState.TASK_STATE_WORKING, message=status)
                    case "final":
                        # Replace the streamed chunks with the complete answer, so the
                        # stored task holds one clean text part (and any intermediate
                        # text streamed before a tool call is dropped).
                        await updater.add_artifact(
                            [new_text_part(event["data"]["text"])],
                            artifact_id=artifact_id,
                            name=ANSWER_ARTIFACT,
                            append=False,
                            last_chunk=True,
                        )
                        await updater.complete()
        except Exception as exc:
            log.exception("agent run failed")
            await updater.failed(new_text_message(f"Agent error: {exc}", role=Role.ROLE_AGENT))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise UnsupportedOperationError()


def build_agent_card(settings: ServerSettings) -> AgentCard:
    card = AgentCard(
        name=get_agent_settings().agent_name,
        description=settings.agent_description,
        version=settings.agent_version,
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=True),
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                url=settings.public_url.rstrip("/") + "/",
                protocol_version="1.0",
            )
        ],
        skills=[
            AgentSkill(
                id="message",
                name="Chat",
                description=settings.agent_description,
                input_modes=["text/plain"],
                output_modes=["text/plain"],
                tags=["chat"],
            )
        ],
    )
    if settings.auth_token:
        card.security_schemes["bearer"].CopyFrom(
            SecurityScheme(http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="Bearer"))
        )
        card.security_requirements.append(SecurityRequirement(schemes={"bearer": {}}))
    return card


def build_routes(settings: ServerSettings) -> list[Route]:
    card = build_agent_card(settings)
    handler = DefaultRequestHandler(
        agent_executor=AgentRunner(), task_store=InMemoryTaskStore(), agent_card=card
    )
    return [
        *create_agent_card_routes(card),
        *create_jsonrpc_routes(handler, "/", enable_v0_3_compat=True),
    ]
