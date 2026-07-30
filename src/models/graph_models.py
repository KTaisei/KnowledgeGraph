from __future__ import annotations

from datetime import UTC, datetime, date
from typing import Any
from uuid import uuid4

try:
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover - fallback when pydantic is unavailable
    BaseModel = object  # type: ignore[assignment]
    Field = None  # type: ignore[assignment]


def _today_iso() -> str:
    return date.today().isoformat()


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if BaseModel is not object:

    class KnowledgeNode(BaseModel):
        node_id: str
        label: str
        type: str = "concept"
        layer: int = 0
        description: str = ""
        prerequisites: list[str] = Field(default_factory=list)
        mastery: float = Field(default=0.0, ge=0.0, le=1.0)
        hesitation_score: float = Field(default=0.0, ge=0.0, le=1.0)
        cognitive_load_history: list[float] = Field(default_factory=list)
        next_review: str = Field(default_factory=_today_iso)
        review_count: int = 0
        difficulty_score: float = Field(default=0.0, ge=0.0, le=1.0)
        semantic: dict[str, Any] = Field(default_factory=dict)


    class KnowledgeEdge(BaseModel):
        edge_id: str = Field(default_factory=lambda: f"e_{uuid4().hex[:12]}")
        source_id: str
        target_id: str
        relationship: str = "prerequisite"
        weight: float = Field(default=1.0, ge=0.0, le=1.0)
        description: str = ""
        semantic: dict[str, Any] = Field(default_factory=dict)


    class KnowledgeGraph(BaseModel):
        graph_id: str = Field(default_factory=lambda: f"g_{uuid4().hex[:12]}")
        topic: str
        created_at: str = Field(default_factory=_utc_now_iso)
        updated_at: str = Field(default_factory=_utc_now_iso)
        nodes: list[KnowledgeNode] = Field(default_factory=list)
        edges: list[KnowledgeEdge] = Field(default_factory=list)
        meta: dict[str, Any] = Field(default_factory=dict)
