import time

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Optional
import httpx
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
)

app = FastAPI(title="Vespa Product Search")

VESPA_URL = "http://localhost:8080"

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

# --- prometheus metrics ---

SEARCH_REQUESTS = Counter(
    "search_requests_total",
    "Total search requests",
    ["status"],
)
SEARCH_LATENCY = Histogram(
    "search_latency_seconds",
    "Search request latency",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
SEARCH_RESULTS = Histogram(
    "search_results_count",
    "Number of results returned per search",
    buckets=[0, 1, 5, 10, 20, 50],
)
VESPA_UP = Gauge(
    "vespa_up",
    "Whether vespa search container is reachable (1=up, 0=down)",
)
VESPA_DOCS = Gauge(
    "vespa_document_count",
    "Number of documents indexed in vespa",
)
VESPA_QUERIES_RATE = Gauge(
    "vespa_queries_rate",
    "Vespa internal query rate (queries/sec)",
)
VESPA_QUERY_LATENCY = Gauge(
    "vespa_query_latency_seconds",
    "Vespa internal average query latency",
)
VESPA_CONTAINER_MEMORY_RSS = Gauge(
    "vespa_container_memory_rss_bytes",
    "Vespa container RSS memory usage",
)
VESPA_CONTAINER_CPU = Gauge(
    "vespa_container_cpu_percent",
    "Vespa container CPU usage percent",
)


@app.get("/", response_class=HTMLResponse)
async def search_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/search")
async def search(
    q: str = Query(default="", description="Search query"),
    category: Optional[str] = Query(default=None),
    brand: Optional[str] = Query(default=None),
    min_price: Optional[float] = Query(default=None),
    max_price: Optional[float] = Query(default=None),
    in_stock: Optional[bool] = Query(default=None),
    sort: Optional[str] = Query(default=None, description="price_asc, price_desc, top_rated"),
    limit: int = Query(default=20, ge=1, le=100),
):
    start = time.monotonic()

    # build YQL query
    where_clauses = []

    if q:
        where_clauses.append(f'userQuery()')
    else:
        where_clauses.append("true")

    if category:
        where_clauses.append(f'category contains "{category}"')
    if brand:
        where_clauses.append(f'brand contains "{brand}"')
    if min_price is not None:
        where_clauses.append(f"price >= {min_price}")
    if max_price is not None:
        where_clauses.append(f"price <= {max_price}")
    if in_stock is not None:
        where_clauses.append(f"in_stock = {'true' if in_stock else 'false'}")

    where = " and ".join(where_clauses)
    yql = f"select * from product where {where}"

    params = {
        "yql": yql,
        "hits": limit,
        "query": q if q else None,
        "ranking": sort if sort else "default",
    }
    # remove None values
    params = {k: v for k, v in params.items() if v is not None}

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{VESPA_URL}/search/", params=params, timeout=10)
            data = resp.json()
            SEARCH_REQUESTS.labels(status="ok").inc()
        except Exception as e:
            SEARCH_REQUESTS.labels(status="error").inc()
            duration = time.monotonic() - start
            SEARCH_LATENCY.observe(duration)
            return {"error": str(e), "hits": [], "total": 0}

    duration = time.monotonic() - start
    SEARCH_LATENCY.observe(duration)

    hits = []
    for hit in data.get("root", {}).get("children", []):
        fields = hit.get("fields", {})
        hits.append({
            "id": hit.get("id", ""),
            "relevance": hit.get("relevance", 0),
            **fields,
        })

    total = data.get("root", {}).get("fields", {}).get("totalCount", 0)
    SEARCH_RESULTS.observe(len(hits))

    return {"hits": hits, "total": total, "query": q}


@app.get("/api/stats")
async def stats():
    """Get some basic stats about what's in vespa."""
    async with httpx.AsyncClient() as client:
        try:
            # get total doc count
            resp = await client.get(
                f"{VESPA_URL}/search/",
                params={"yql": "select * from product where true", "hits": 0},
                timeout=10,
            )
            data = resp.json()
            total = data.get("root", {}).get("fields", {}).get("totalCount", 0)

            # get unique categories
            cat_resp = await client.get(
                f"{VESPA_URL}/search/",
                params={
                    "yql": "select category from product where true | all(group(category) each(output(count())))",
                    "hits": 0,
                },
                timeout=10,
            )
            cat_data = cat_resp.json()
            categories = []
            for group in _extract_groups(cat_data):
                categories.append(group)

            # get unique brands
            brand_resp = await client.get(
                f"{VESPA_URL}/search/",
                params={
                    "yql": "select brand from product where true | all(group(brand) each(output(count())))",
                    "hits": 0,
                },
                timeout=10,
            )
            brand_data = brand_resp.json()
            brands = []
            for group in _extract_groups(brand_data):
                brands.append(group)

            return {
                "total_products": total,
                "categories": categories,
                "brands": brands,
            }
        except Exception as e:
            return {"error": str(e)}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus-compatible metrics endpoint. Scrapes vespa metrics too."""
    await _collect_vespa_metrics()
    return PlainTextResponse(
        content=generate_latest().decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/api/vespa-metrics")
async def vespa_metrics():
    """Human-readable vespa metrics for the dashboard."""
    async with httpx.AsyncClient() as client:
        try:
            # container metrics
            resp = await client.get(
                f"{VESPA_URL}/state/v1/metrics", timeout=5
            )
            container_metrics = resp.json()

            # config server metrics (has cpu/memory)
            config_resp = await client.get(
                "http://localhost:19071/metrics/v2/values", timeout=5
            )
            config_data = config_resp.json()

            return {
                "status": "ok",
                "container": _summarize_container_metrics(container_metrics),
                "system": _summarize_system_metrics(config_data),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}


async def _collect_vespa_metrics():
    """Pull key metrics from vespa and update prometheus gauges."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{VESPA_URL}/state/v1/health", timeout=3)
            VESPA_UP.set(1 if resp.status_code == 200 else 0)
        except Exception:
            VESPA_UP.set(0)
            return

        try:
            # doc count
            resp = await client.get(
                f"{VESPA_URL}/search/",
                params={"yql": "select * from product where true", "hits": 0},
                timeout=5,
            )
            data = resp.json()
            total = data.get("root", {}).get("fields", {}).get("totalCount", 0)
            VESPA_DOCS.set(total)
        except Exception:
            pass

        try:
            config_resp = await client.get(
                "http://localhost:19071/metrics/v2/values", timeout=5
            )
            config_data = config_resp.json()
            for node in config_data.get("nodes", []):
                for service in node.get("services", []):
                    for m in service.get("metrics", []):
                        vals = m.get("values", {})
                        if "memory_rss" in vals:
                            VESPA_CONTAINER_MEMORY_RSS.set(vals["memory_rss"])
                        if "cpu_util" in vals:
                            VESPA_CONTAINER_CPU.set(vals["cpu_util"])
                        if "queries.rate" in vals:
                            VESPA_QUERIES_RATE.set(vals["queries.rate"])
                        if "query_latency.average" in vals:
                            VESPA_QUERY_LATENCY.set(vals["query_latency.average"] / 1000)
        except Exception:
            pass


def _summarize_container_metrics(data):
    """Pull interesting bits from vespa container /state/v1/metrics."""
    summary = {}
    for metric in data.get("metrics", {}).get("values", []):
        name = metric.get("name", "")
        vals = metric.get("values", {})
        if name == "search_connections":
            summary["search_connections"] = vals.get("last", 0)
        elif name == "queries.rate":
            summary["queries_per_sec"] = round(vals.get("rate", 0), 3)
        elif name == "query_latency":
            summary["query_latency_avg_ms"] = round(vals.get("average", 0), 2)
            summary["query_latency_max_ms"] = round(vals.get("max", 0), 2)
        elif name == "totalhits_per_query":
            summary["avg_hits_per_query"] = round(vals.get("average", 0), 2)
        elif name == "jdisc.thread_pool.work_queue.size":
            summary["thread_pool_queue_size"] = vals.get("last", 0)
    return summary


def _summarize_system_metrics(data):
    """Pull system-level metrics from vespa /metrics/v2/values."""
    summary = {}
    for node in data.get("nodes", []):
        for service in node.get("services", []):
            for m in service.get("metrics", []):
                vals = m.get("values", {})
                if "memory_rss" in vals:
                    summary["memory_rss_mb"] = round(vals["memory_rss"] / 1024 / 1024, 1)
                if "memory_virt" in vals:
                    summary["memory_virt_mb"] = round(vals["memory_virt"] / 1024 / 1024, 1)
                if "cpu" in vals:
                    summary["cpu_percent"] = round(vals["cpu"], 2)
                if "cpu_util" in vals:
                    summary["cpu_util_percent"] = round(vals["cpu_util"], 4)
            break  # just first service
        break  # just first node
    return summary


def _extract_groups(data):
    """Pull group labels and counts out of vespa grouping response."""
    groups = []
    try:
        children = data["root"]["children"]
        for child in children:
            if "children" in child:
                for group_list in child["children"]:
                    if "children" in group_list:
                        for g in group_list["children"]:
                            label = g.get("value", g.get("id", "unknown"))
                            count = g.get("fields", {}).get("count()", 0)
                            groups.append({"label": label, "count": count})
    except (KeyError, TypeError):
        pass
    return groups
