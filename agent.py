"""Chat with a parking agent that executes tools in a bounded loop."""

import json
import logging
import os
import sys
from pathlib import Path
from collections.abc import Generator
from contextlib import closing
from typing import Literal

import anthropic
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field, JsonValue
from request_context import RequestIdFilter, run_metrics

from tools import (
    BadArgumentsError, ToolError, UnknownToolError,
    get_lot_status, list_free_slots,
)

logger = logging.getLogger(__name__)

class ToolCall(BaseModel):
    name: str
    # Preserve malformed JSON inputs too, so validation failures can be reviewed.
    input: JsonValue
    is_error: bool


class AgentResult(BaseModel):
    answer: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    steps: int = Field(ge=0)
    stop_reason: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


SYSTEM_PROMPT = (
    "Only answer questions about parking lot occupancy and available slots. "
    "For unrelated requests, explain your scope and ask for a parking question. "
    "You are a parking assistant. Answer parking questions only using successful "
    "tool results from this run. Never guess occupancy, availability, or lot IDs. "
    "If a tool fails, explain that the requested data could not be retrieved; "
    "ask for clarification when appropriate. Do not invent missing data. "
    "Report the reading timestamps without claiming how recent the data is."
)


class TextEvent(BaseModel):
    type: Literal["text"] = "text"
    chunk: str


class ToolStartEvent(BaseModel):
    type: Literal["tool_start"] = "tool_start"
    name: str


class ToolEndEvent(BaseModel):
    type: Literal["tool_end"] = "tool_end"
    name: str
    is_error: bool


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    result: AgentResult


AgentEvent = TextEvent | ToolStartEvent | ToolEndEvent | DoneEvent

LOT_ID_SCHEMA = {
    "type": "string",
    "description": (
        "Exact, case-sensitive lot identifier, without the 'Lot ' prefix or "
        "surrounding whitespace. For 'Lot A', send 'A'; for 'Lot B', send 'B'."
    ),
}

# No enum: the database determines which lot IDs exist as lots are added.
TOOLS = [
    {
        "name": "get_lot_status",
        "description": (
            "Get a parking lot's total, occupied, and free slot counts using "
            "each slot's latest reading. Use this to answer how full a lot is "
            "or how many spaces are available. Returns the newest reading "
            "timestamp, or a tool error for an unknown lot ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lot_id": LOT_ID_SCHEMA,
            },
            "required": ["lot_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_free_slots",
        "description": (
            "List the IDs of parking slots that are free according to each "
            "slot's latest reading. Use this when asked which specific spaces "
            "are available in a lot. Returns sorted slot IDs and the newest "
            "reading timestamp, or a tool error for an unknown lot ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lot_id": LOT_ID_SCHEMA,
            },
            "required": ["lot_id"],
            "additionalProperties": False,
        },
    },
]

DISPATCH = {
    "get_lot_status": get_lot_status,
    "list_free_slots": list_free_slots,
}


VALIDATORS = {}
for definition in TOOLS:
    Draft202012Validator.check_schema(definition["input_schema"])
    VALIDATORS[definition["name"]] = Draft202012Validator(definition["input_schema"])


def execute_tool(name: str, arguments: object) -> dict:
    if name not in DISPATCH:
        raise UnknownToolError("Unknown tool. Use one of the supplied tool names.")
    if not VALIDATORS[name].is_valid(arguments):
        raise BadArgumentsError(
            "Invalid arguments. Supply only the required lot_id field as a string."
        )
    return DISPATCH[name](**arguments)


def run_agent(question: str, max_steps: int = 8, *, client: anthropic.Anthropic) -> AgentResult:
    """Consume the shared streaming loop for CLI and non-streaming HTTP callers."""
    with closing(run_agent_stream(question, max_steps, client=client)) as events:
        for event in events:
            if isinstance(event, DoneEvent):
                return event.result
    raise RuntimeError("Agent stream ended without a done event")


def run_agent_stream(
    question: str, max_steps: int = 8, *, client: anthropic.Anthropic
) -> Generator[AgentEvent, None, None]:
    """Keep the full conversation for one question, with at most max_steps calls."""
    limit_message = f"Stopped after reaching the step limit ({max_steps}) without finishing."
    tool_calls: list[ToolCall] = []
    steps = 0
    input_tokens = 0
    output_tokens = 0
    metrics = run_metrics.get()

    def finish(answer: str, stop_reason: str) -> AgentResult:
        if metrics is not None:
            metrics.stop_reason = stop_reason
        answer = answer.strip()
        return AgentResult(
            answer=answer or "The model returned no text answer. Please try again.",
            tool_calls=tool_calls, steps=steps, stop_reason=stop_reason,
            input_tokens=input_tokens, output_tokens=output_tokens,
        )

    if max_steps <= 0:
        yield DoneEvent(result=finish(limit_message, "step_limit"))
        return

    # Local history is discarded on failure; never persist an incomplete turn.
    messages = [{"role": "user", "content": question}]

    for _ in range(max_steps):
        if metrics is not None:
            metrics.steps += 1
        with client.messages.stream(
            model="claude-sonnet-5-5",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=TOOLS,
        ) as stream:
            for chunk in stream.text_stream:
                yield TextEvent(chunk=chunk)
            response = stream.get_final_message()
        steps += 1
        input_tokens += response.usage.input_tokens
        output_tokens += response.usage.output_tokens
        if metrics is not None:
            metrics.input_tokens = input_tokens
            metrics.output_tokens = output_tokens
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "max_tokens":
            yield DoneEvent(result=finish("The response reached its token limit before finishing. Please try a narrower question.", "max_tokens"))
            return
        if response.stop_reason == "refusal":
            yield DoneEvent(result=finish("The model declined this request. Please try rephrasing your question.", "refusal"))
            return

        if response.stop_reason != "tool_use":
            yield DoneEvent(result=finish("\n".join(
                block.text for block in response.content if block.type == "text"
            ), response.stop_reason))
            return

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                yield ToolStartEvent(name=block.name)
                if metrics is not None:
                    metrics.tools.append(block.name)
                logger.info("[tool] %s(%s)", block.name, block.input)
                tool_result = {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                }
                try:
                    result = execute_tool(block.name, block.input)
                    tool_result["content"] = json.dumps(result)
                except ToolError as exc:
                    logger.warning("Recoverable tool failure: %s", block.name, exc_info=True)
                    tool_result["content"] = json.dumps({
                        "error": str(exc)
                    })
                    tool_result["is_error"] = True
                tool_results.append(tool_result)
                tool_calls.append(ToolCall(
                    name=block.name,
                    input=block.input,
                    is_error=tool_result.get("is_error", False),
                ))
                yield ToolEndEvent(name=block.name, is_error=tool_result.get("is_error", False))
        messages.append({"role": "user", "content": tool_results})

    yield DoneEvent(result=finish(limit_message, "step_limit"))


def configure_logging(log_path: Path | None = None) -> None:
    """Log to stdout by default; LOG_FILE or an explicit path selects a file."""
    destination = log_path or os.environ.get("LOG_FILE")
    handler = (
        logging.FileHandler(destination, encoding="utf-8")
        if destination else logging.StreamHandler(sys.stdout)
    )
    handler.addFilter(RequestIdFilter())
    logging.basicConfig(
        handlers=[handler],
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s",
        force=True,
    )


def main() -> int:
    configure_logging()
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        logger.error("Startup failed: ANTHROPIC_API_KEY is missing")
        print("Cannot start: set ANTHROPIC_API_KEY before running the agent.")
        return 1
    try:
        client = anthropic.Anthropic(max_retries=2, timeout=30.0)
    except Exception:
        logger.exception("Client startup failed")
        print("Cannot start: check the API configuration.")
        return 1

    with client:
        print("Parking agent (type quit to exit)")
        while True:
            try:
                question = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if question.lower() == "quit":
                break
            if not question:
                continue
            try:
                result = run_agent(question, client=client)
                print(result.answer)
            except anthropic.AuthenticationError:
                logger.exception("API authentication failed")
                print("Authentication failed. Please check the API configuration.")
            except (anthropic.RateLimitError, anthropic.APIConnectionError):
                logger.exception("API unavailable after SDK retries")
                print("The service is temporarily unavailable. Please try again later.")
            except Exception:
                logger.exception("Agent run failed")
                print("Something went wrong. Please try again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
