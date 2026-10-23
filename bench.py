"""Usage: python bench.py /slow-def (or /slow-async)."""

import asyncio
import sys
import time

import httpx


async def main(path: str) -> None:
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8001", timeout=30.0, trust_env=False
    ) as client:
        start = time.perf_counter()
        responses = await asyncio.gather(*(client.get(path) for _ in range(5)))
        elapsed = time.perf_counter() - start
        for response in responses:
            response.raise_for_status()
        print(f"{path}: 5 requests completed in {elapsed:.3f} seconds")


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].startswith("/"):
        raise SystemExit("Usage: python bench.py /slow-def (or /slow-async)")
    asyncio.run(main(sys.argv[1]))
