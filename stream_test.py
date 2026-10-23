"""Run both streaming experiments with: python stream_test.py."""

import os
import time

import anthropic

from agent import SYSTEM_PROMPT, TOOLS


MODEL = "claude-sonnet-5-5"
# The helper also yields synthetic events such as text and input_json.
RAW_EVENT_TYPES = {
    "message_start", "message_delta", "message_stop",
    "content_block_start", "content_block_delta", "content_block_stop",
}


def report(message, started: float, first: float | None, ended: float, label: str) -> None:
    print()
    if first is None:
        print(f"{label}: none received")
    else:
        print(f"{label}: {first - started:.3f} seconds")
    print(f"Total time: {ended - started:.3f} seconds")
    print(f"stop_reason: {message.stop_reason}")
    print(f"usage: {message.usage.model_dump_json()}")


def stream_text(client: anthropic.Anthropic) -> None:
    print("=== Text streaming: roughly 150 words ===", flush=True)
    first = None
    started = time.perf_counter()
    with client.messages.stream(
        model=MODEL,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": "In roughly 150 words, explain how parking occupancy sensors work.",
        }],
    ) as stream:
        for chunk in stream.text_stream:
            if chunk and first is None:
                first = time.perf_counter()
            print(chunk, end="", flush=True)
        message = stream.get_final_message()
        ended = time.perf_counter()
    report(message, started, first, ended, "Time to first text chunk")


def stream_tools(client: anthropic.Anthropic) -> None:
    print("\n=== Tool request: raw event types ===", flush=True)
    first = None
    started = time.perf_counter()
    with client.messages.stream(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=TOOLS,
        messages=[{"role": "user", "content": "How full is Lot A?"}],
    ) as stream:
        for event in stream:
            if event.type in RAW_EVENT_TYPES:
                if first is None:
                    first = time.perf_counter()
                print(event.type, flush=True)
        message = stream.get_final_message()
        ended = time.perf_counter()
    report(message, started, first, ended, "Time to first raw event")
    # Observe the request only; no tools are executed in this experiment.


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        raise SystemExit("ANTHROPIC_API_KEY must be set before running this script.")
    with anthropic.Anthropic(timeout=30.0, max_retries=2) as client:
        stream_text(client)
        stream_tools(client)


if __name__ == "__main__":
    main()
