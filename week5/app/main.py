"""FastAPI wrapper around the TechCorp agent.

Run from the week5 folder:
    python3 -m uvicorn app.main:app --reload
then open http://localhost:8000/docs

The agent is created lazily on the first request so the server still starts
(and /health still answers) when GOOGLE_API_KEY isn't set yet.
"""

from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from app.agent import Agent

DB_PATH = str(Path(__file__).resolve().parents[1] / "data" / "techcorp.db")

app = FastAPI(title="TechCorp Agent")
_agent = None


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = Agent(DB_PATH)
    return _agent


class QueryRequest(BaseModel):
    question: str
    user_role: str = "engineer"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/agent/query")
def query_agent(req: QueryRequest):
    try:
        return get_agent().query(req.question, req.user_role)
    except ValueError as e:
        # No API key configured.
        return {"answer": str(e), "tokens_used": 0, "cost": 0.0, "role": req.user_role}


@app.post("/agent/metrics")
def metrics():
    try:
        return get_agent().get_metrics()
    except ValueError as e:
        return {"error": str(e)}
