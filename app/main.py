from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Optional
import httpx

app = FastAPI(title="Vespa Product Search")

VESPA_URL = "http://localhost:8080"

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


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
        except Exception as e:
            return {"error": str(e), "hits": [], "total": 0}

    hits = []
    for hit in data.get("root", {}).get("children", []):
        fields = hit.get("fields", {})
        hits.append({
            "id": hit.get("id", ""),
            "relevance": hit.get("relevance", 0),
            **fields,
        })

    total = data.get("root", {}).get("fields", {}).get("totalCount", 0)

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
