from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SearchHit(BaseModel):
    id: str
    relevance: float = 0.0

    title: str | None = None
    description: str | None = None
    category: str | None = None
    brand: str | None = None
    price: float | None = None
    rating: float | None = None
    in_stock: bool | None = None
    image_url: str | None = None


class SearchResponse(BaseModel):
    hits: list[SearchHit]
    total: int
    query: str | None = None
    error: str | None = None


class GroupCount(BaseModel):
    label: str
    count: int


class StatsResponse(BaseModel):
    total_products: int
    categories: list[GroupCount]
    brands: list[GroupCount]
    error: str | None = None


class VespaMetricsSummary(BaseModel):
    total_docs: int | None = None
    query_latency_avg_ms: float | None = None
    query_latency_max_ms: float | None = None
    queries_per_sec: float | None = None
    search_connections: int | None = None
    memory_rss_mb: float | None = None
    cpu_percent: float | None = None


class HealthResponse(BaseModel):
    status: str
    vespa_reachable: bool
    error: str | None = None


class VespaMetricsResponse(BaseModel):
    status: str
    container: dict[str, Any] = Field(default_factory=dict)
    system: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

