"""Compare blocking sleep in sync and async FastAPI handlers."""

import time

from fastapi import FastAPI


app = FastAPI()


@app.get("/slow-def")
def slow_def() -> dict[str, str]:
    time.sleep(2)
    return {"status": "ok"}


@app.get("/slow-async")
async def slow_async() -> dict[str, str]:
    # Deliberately blocks the event loop for this experiment.
    time.sleep(2)
    return {"status": "ok"}
