"""Run with: python -m uvicorn api:app --reload."""

import logging
import json
import os
import time
from uuid import uuid4
from contextlib import asynccontextmanager

import anthropic
import anyio
from fastapi import FastAPI, Request
from pydantic import BaseModel, Field, field_validator
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool
from starlette.datastructures import MutableHeaders
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from request_context import request_id, run_metrics, RunMetrics

from agent import AgentResult, configure_logging, run_agent, run_agent_stream


logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question")
    @classmethod
    def reject_blank_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question must contain non-whitespace characters.")
        return value.strip()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        logger.error("Startup failed: ANTHROPIC_API_KEY is missing")
        raise RuntimeError("ANTHROPIC_API_KEY must be set before starting the API.")

    with anthropic.Anthropic(max_retries=2, timeout=30.0) as client:
        app.state.client = client
        yield


app = FastAPI(lifespan=lifespan)


def safe_error(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, anthropic.AuthenticationError):
        return 502, "Upstream service authentication failed."
    if isinstance(exc, (anthropic.RateLimitError, anthropic.APIConnectionError)):
        return 503, "Service temporarily unavailable. Please try again later."
    return 500, "Something went wrong. Please try again."


def error_response(status: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": message, "request_id": request_id.get()},
    )


@app.exception_handler(anthropic.AuthenticationError)
async def authentication_error(request: Request, exc: Exception):
    logger.exception("Upstream authentication failed", exc_info=exc)
    return error_response(*safe_error(exc))


@app.exception_handler(anthropic.RateLimitError)
@app.exception_handler(anthropic.APIConnectionError)
async def unavailable_error(request: Request, exc: Exception):
    logger.exception("Upstream unavailable after retries", exc_info=exc)
    return error_response(*safe_error(exc))


async def unexpected_error(request: Request, exc: Exception):
    logger.exception("Unexpected request failure", exc_info=exc)
    return error_response(*safe_error(exc))


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: Exception):
    return error_response(422, "Invalid request. Provide a question of 1 to 2000 characters.")


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return error_response(exc.status_code, "Request could not be processed.")


class RequestLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        id_token = request_id.set(uuid4().hex)
        metrics = RunMetrics()
        metrics_token = run_metrics.set(metrics)
        started = time.perf_counter()
        status = 500
        headers_sent = False
        body_complete = False

        async def tracked_send(message):
            nonlocal status, headers_sent, body_complete
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id.get()
                headers_sent = True
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                body_complete = True

        try:
            try:
                await self.app(scope, receive, tracked_send)
            except Exception as exc:
                metrics.outcome = "error"
                metrics.stop_reason = "error"
                logger.exception("Request failed")
                if headers_sent:
                    raise
                response = error_response(*safe_error(exc))
                await response(scope, receive, tracked_send)
        finally:
            if status >= 400:
                metrics.outcome = "error"
                metrics.stop_reason = "error"
            elif not body_complete and metrics.outcome != "error":
                metrics.outcome = "incomplete"
            logger.info(
                "event=request_complete status=%s latency_ms=%.3f steps=%s "
                "input_tokens=%s output_tokens=%s tools=%s stop_reason=%s "
                "outcome=%s body_complete=%s",
                status, (time.perf_counter() - started) * 1000, metrics.steps,
                metrics.input_tokens, metrics.output_tokens,
                json.dumps(metrics.tools, separators=(",", ":")), metrics.stop_reason,
                metrics.outcome, body_complete,
            )
            run_metrics.reset(metrics_token)
            request_id.reset(id_token)


app.add_middleware(RequestLoggingMiddleware)


async def sse_events(question: str, client):
    events = run_agent_stream(question, client=client)
    metrics = run_metrics.get()
    done = False
    try:
        async for event in iterate_in_threadpool(events):
            if event.type == "done":
                done = True
            yield f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"
        if not done:
            raise RuntimeError("Agent stream ended without a done event")
    except Exception as exc:
        if metrics is not None:
            metrics.outcome = "error"
            metrics.stop_reason = "error"
        logger.exception("Agent stream failed")
        _, message = safe_error(exc)
        payload = json.dumps({"error": message, "request_id": request_id.get()})
        yield f"event: error\ndata: {payload}\n\n"
    finally:
        # Close the synchronous SDK stream off the event loop, even on cancellation.
        with anyio.CancelScope(shield=True):
            await run_in_threadpool(events.close)


@app.post("/chat/stream")
def chat_stream(body: ChatRequest, request: Request):
    return StreamingResponse(
        sse_events(body.question, request.app.state.client),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/chat", response_model=AgentResult)
def chat(body: ChatRequest, request: Request) -> AgentResult:
    return run_agent(body.question, client=request.app.state.client)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
