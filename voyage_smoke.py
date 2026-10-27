"""Run: python voyage_smoke.py (requires VOYAGE_API_KEY)."""

import math
import os
from pathlib import Path

import voyageai


POLICIES = Path(__file__).resolve().parent / "docs" / "policies"
MODEL = "voyage-4"
# Standard synchronous pricing, verified 2026-10-28; excludes free allowance.
USD_PER_MILLION_TOKENS = 0.06


def norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Vectors must have equal dimensions.")
    denominator = norm(left) * norm(right)
    if denominator == 0:
        raise ValueError("Cosine similarity is undefined for a zero vector.")
    return sum(a * b for a, b in zip(left, right)) / denominator


def main() -> None:
    key = os.environ.get("VOYAGE_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set VOYAGE_API_KEY in this terminal before running voyage_smoke.py.")

    files = sorted(POLICIES.glob("*.md"))
    if len(files) != 6:
        raise ValueError(f"Expected six policy files, found {len(files)}.")
    documents = [path.read_text(encoding="utf-8") for path in files]
    by_name = dict(zip((path.name for path in files), documents))
    # Extract verbatim excerpts rather than maintaining a second policy copy.
    stay = by_name["01-lot-information.md"].split("## Maximum stay\n", 1)[1].strip().split("\n\n", 1)[0]
    overnight = next(
        line for line in by_name["02-pricing-and-rates.md"].splitlines()
        if line.startswith("- **Overnight flat rate")
    )
    client = voyageai.Client(api_key=key, max_retries=2, timeout=30.0)
    document_result = client.embed(
        [stay, overnight], model=MODEL, input_type="document", truncation=False,
    )
    query_result = client.embed(
        ["How long can I leave my car parked for?"],
        model=MODEL, input_type="query", truncation=False,
    )
    vector = document_result.embeddings[0]
    print(f"Model: {MODEL}")
    print(f"Vector length: {len(vector)}")
    print(f"Vector norm: {norm(vector):.8f}")
    print(f"Snippet total_tokens: {document_result.total_tokens}")
    print(f"Query total_tokens: {query_result.total_tokens}")
    for label, embedding in zip(("maximum stay", "overnight rate"), document_result.embeddings):
        score = cosine_similarity(query_result.embeddings[0], embedding)
        print(f"Cosine similarity ({label}): {score:.8f}")

    corpus_result = client.embed(
        documents, model=MODEL, input_type="document", truncation=False,
    )
    print(f"Corpus file count: {len(files)}")
    print(f"Corpus total_tokens: {corpus_result.total_tokens}")
    cost = corpus_result.total_tokens / 1_000_000 * USD_PER_MILLION_TOKENS
    print(f"Corpus cost after free allowance (USD): ${cost:.8f}")


if __name__ == "__main__":
    main()
