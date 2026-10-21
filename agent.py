"""Chat with a parking agent that executes tools in a bounded loop."""

import json
import logging
import os
from pathlib import Path

import anthropic
from jsonschema import Draft202012Validator

from tools import (
    BadArgumentsError, ToolError, UnknownToolError,
    get_lot_status, list_free_slots,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a parking assistant. Answer parking questions only using successful "
    "tool results from this run. Never guess occupancy, availability, or lot IDs. "
    "If a tool fails, explain that the requested data could not be retrieved; "
    "ask for clarification when appropriate. Do not invent missing data. "
    "Use the reading timestamps to describe how recent the data is."
)

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


def run_agent(question: str, max_steps: int = 8, *, client: anthropic.Anthropic) -> str:
    """Keep the full conversation for one question, with at most max_steps calls."""
    limit_message = f"Stopped after reaching the step limit ({max_steps}) without finishing."
    if max_steps <= 0:
        return limit_message

    # Local history is discarded on failure; never persist an incomplete turn.
    messages = [{"role": "user", "content": question}]

    for _ in range(max_steps):
        response = client.messages.create(
            model="claude-sonnet-5-5",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=TOOLS,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "max_tokens":
            return "The response reached its token limit before finishing. Please try a narrower question."
        if response.stop_reason == "refusal":
            return "The model declined this request. Please try rephrasing your question."

        if response.stop_reason != "tool_use":
            return "\n".join(
                block.text for block in response.content if block.type == "text"
            )

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
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
        messages.append({"role": "user", "content": tool_results})

    return limit_message


def main() -> int:
    logging.basicConfig(
        filename=Path(__file__).resolve().with_name("agent.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        logger.error("Startup failed: ANTHROPIC_API_KEY is missing")
        print("Cannot start: set ANTHROPIC_API_KEY before running the agent.")
        return 1
    try:
        client = anthropic.Anthropic(max_retries=2)
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
                print(run_agent(question, client=client))
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
