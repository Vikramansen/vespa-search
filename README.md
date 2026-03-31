# vespa-search

a simple local vespa search setup for e-commerce products. built this to get familiar with vespa before using it at work.

## what's in here

- vespa running in docker (single node, nothing fancy)
- fastapi backend that talks to vespa
- basic search ui with filters
- ~50 sample products to play around with

## getting started

you need docker and python 3.10+.

```bash
# start vespa
docker compose up -d

# wait for it to be healthy (takes about a minute)
docker compose ps

# install python deps
pip install -r requirements.txt

# feed the sample data
python app/feed.py

# start the web app
uvicorn app.main:app --reload --port 8000
```

then go to http://localhost:8000 and search for stuff.

## vespa schema

the product schema has: title, description, category, brand, price, rating, in_stock, image_url.
search uses BM25 ranking on title and description. you can also filter by category, brand, price range, etc.

## useful endpoints

- `GET /` - the search ui
- `GET /health` - backend health (and Vespa reachability)
- `GET /api/search?q=headphones&category=electronics` - search api
- `GET /api/stats` - product count, categories, brands
- `GET /api/vespa-metrics` - vespa health, memory, cpu, query latency
- `GET /metrics` - prometheus-compatible metrics

vespa's own api is at http://localhost:8080 if you want to poke around directly.

## project structure

```
docker-compose.yml      # vespa container
vespa-app/              # vespa application package
  schemas/product.sd    # product schema (fields, ranking)
  services.xml          # vespa service config
  hosts.xml
app/
  main.py               # fastapi backend
  feed.py               # data feeder script
  templates/index.html  # search page
  static/style.css
data/products.json      # sample data (50 products)
```

## architecture and production notes

see [ARCHITECTURE.md](ARCHITECTURE.md) for how this works under the hood and what you'd need to change to make it production-ready (multi-node clusters, k8s, search improvements, monitoring, etc).

## Configuration

The FastAPI backend reads these environment variables:

- `VESPA_URL` (default `http://localhost:8080`)
- `VESPA_CONFIG_URL` (default `http://localhost:19071`)
- `HTTP_TIMEOUT_S` (default `10`)
- `SEARCH_DEFAULT_LIMIT` (default `20`)
- `SEARCH_MIN_LIMIT` (default `1`)
- `SEARCH_MAX_LIMIT` (default `100`)

## shutting down

```bash
docker compose down
# or if you want to nuke the data too
docker compose down -v
```
