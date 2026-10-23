"""Run with: python -m uvicorn api:app --reload."""

import logging
import os
from contextlib import asynccontextmanager

import anthropic
from fastapi import FastAPI, Request
from pydantic import BaseModel, Field, field_validator

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

    with anthropic.Anthropic(max_retries=2) as client:
        app.state.client = client
        yield


app = FastAPI(lifespan=lifespan)


@app.post("/chat", response_model=AgentResult)
def chat(body: ChatRequest, request: Request) -> AgentResult:
    return run_agent(body.question, client=request.app.state.client)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
