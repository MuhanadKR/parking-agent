"""Run the three live streaming-agent experiments."""

import os
from contextlib import closing

import anthropic

from agent import run_agent_stream


QUESTIONS = (
    "How full is Lot A?",
    "Compare Lot A and Lot B",
    "Is Lot Z full?",
)


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        raise SystemExit("ANTHROPIC_API_KEY must be set before running this script.")
    with anthropic.Anthropic(timeout=30.0, max_retries=2) as client:
        for question in QUESTIONS:
            print(f"\n=== {question} ===", flush=True)
            with closing(run_agent_stream(question, client=client)) as events:
                for event in events:
                    if event.type == "text":
                        print(event.chunk, end="", flush=True)
                    else:
                        print(f"\n{event.model_dump_json()}", flush=True)


if __name__ == "__main__":
    main()
