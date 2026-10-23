"""Run with: python -m uvicorn api:app --reload."""

import logging
import json
import os
import time
from uuid import uuid4
from contextlib import asynccontextmanager

import anthropic
from fastapi import FastAPI, Request
from pydantic import BaseModel, Field, field_validator
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from request_context import request_id, run_metrics, RunMetrics

from agent import AgentResult, configure_logging, run_agent


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


def error_response(status: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": message, "request_id": request_id.get()},
    )


@app.exception_handler(anthropic.AuthenticationError)
async def authentication_error(request: Request, exc: Exception):
    logger.exception("Upstream authentication failed", exc_info=exc)
    return error_response(502, "Upstream service authentication failed.")


@app.exception_handler(anthropic.RateLimitError)
@app.exception_handler(anthropic.APIConnectionError)
async def unavailable_error(request: Request, exc: Exception):
    logger.exception("Upstream unavailable after retries", exc_info=exc)
    return error_response(503, "Service temporarily unavailable. Please try again later.")


async def unexpected_error(request: Request, exc: Exception):
    logger.exception("Unexpected request failure", exc_info=exc)
    return error_response(500, "Something went wrong. Please try again.")


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: Exception):
    return error_response(422, "Invalid request. Provide a question of 1 to 2000 characters.")


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return error_response(exc.status_code, "Request could not be processed.")


@app.middleware("http")
async def request_logging(request: Request, call_next):
    id_token = request_id.set(uuid4().hex)
    metrics = RunMetrics()
    metrics_token = run_metrics.set(metrics)
    start = time.perf_counter()
    status = 500
    try:
        try:
            response = await call_next(request)
        except Exception as exc:
            # Handle here, before context reset: ServerErrorMiddleware sits
            # outside user middleware and would otherwise lose this context.
            response = await unexpected_error(request, exc)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id.get()
        return response
    finally:
        if status >= 400:
            metrics.stop_reason = "error"
        logger.info(
            "event=request_complete status=%s latency_ms=%.3f steps=%s "
            "input_tokens=%s output_tokens=%s tools=%s stop_reason=%s",
            status, (time.perf_counter() - start) * 1000, metrics.steps,
            metrics.input_tokens, metrics.output_tokens,
            json.dumps(metrics.tools, separators=(",", ":")), metrics.stop_reason,
        )
        run_metrics.reset(metrics_token)
        request_id.reset(id_token)


@app.post("/chat", response_model=AgentResult)
def chat(body: ChatRequest, request: Request) -> AgentResult:
    return run_agent(body.question, client=request.app.state.client)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
