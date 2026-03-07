# architecture

how this thing works and what you'd need to do to make it production-ready.

## how it works right now

```
┌──────────────┐       ┌──────────────────────────────┐
│   browser    │       │        docker                 │
│              │       │                               │
│  index.html  │──────▶│  ┌─────────┐                  │
│  (search ui) │       │  │ FastAPI │ :8000            │
│              │       │  │ backend │                  │
└──────────────┘       │  └────┬────┘                  │
                       │       │ YQL queries            │
                       │       ▼                        │
                       │  ┌──────────┐                  │
                       │  │  Vespa   │ :8080 (search)   │
                       │  │ (single  │ :19071 (config)  │
                       │  │  node)   │                  │
                       │  └──────────┘                  │
                       └──────────────────────────────┘
```

### flow

1. user types in the search box
2. browser sends GET to `/api/search?q=...&category=...` etc
3. fastapi backend builds a YQL query from the params
4. sends it to vespa's `/search/` endpoint on port 8080
5. vespa runs BM25 ranking on title + description fields
6. results come back, fastapi formats them, browser renders cards

### vespa internals (single node)

in this setup, one container runs everything:
- **config server** (19071) — manages cluster config, accepts app package deployments
- **container** (8080) — handles search queries and document feeding
- **content node** — stores and indexes documents, runs matching

the product schema uses:
- `index` for text fields (title, description) — builds inverted index for BM25
- `attribute` for structured fields (category, brand, price) — column-store for filtering/sorting
- `summary` on everything — so fields appear in search results

ranking profiles:
- `default` — BM25 on title (2x weight) + description
- `price_asc` / `price_desc` — sort by price
- `top_rated` — sort by rating

## metrics

we collect metrics at two levels:

**app-level** (prometheus via `/metrics`):
- `search_requests_total` — counter with ok/error labels
- `search_latency_seconds` — histogram of end-to-end search time
- `search_results_count` — how many results per query

**vespa-level** (scraped from vespa's APIs):
- `vespa_up` — health check gauge
- `vespa_document_count` — indexed docs
- `vespa_container_memory_rss_bytes` — memory usage
- `vespa_container_cpu_percent` — cpu usage
- `vespa_queries_rate` / `vespa_query_latency_seconds` — internal query metrics

the `/api/vespa-metrics` endpoint gives you a human-readable json version. the search ui has a collapsible metrics panel that auto-refreshes every 5s.

## what you'd change for production

this is a learning setup. here's what a real deployment would look like.

### 1. multi-node cluster

right now everything runs on one container. in production:

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ config      │    │ container   │    │ container   │
│ server (x3) │    │ node 1      │    │ node 2      │
│ (zookeeper) │    │ (stateless) │    │ (stateless) │
└─────────────┘    └─────────────┘    └─────────────┘
                   ┌─────────────┐    ┌─────────────┐
                   │ content     │    │ content     │
                   │ node 1      │    │ node 2      │
                   │ (data +     │    │ (data +     │
                   │  indexing)  │    │  indexing)  │
                   └─────────────┘    └─────────────┘
```

- **3 config servers** with zookeeper for consensus
- **2+ container nodes** (stateless, behind a load balancer) — handles queries
- **2+ content nodes** — stores data with redundancy factor of 2

this gives you:
- no single point of failure
- horizontal scaling for queries (add container nodes)
- data redundancy (content nodes replicate across groups)

### 2. kubernetes deployment

instead of docker compose, you'd use:
- vespa helm charts or custom k8s manifests
- StatefulSets for content nodes (need persistent storage)
- Deployments for container nodes (stateless, easy to scale)
- PVCs for content node data
- Services + Ingress for routing

### 3. data pipeline

the `feed.py` script is fine for 50 products. for real data:
- use vespa's feed client (java or vespa-cli) for bulk feeding — much faster
- set up a pipeline: source db → change data capture → vespa feed
- consider using vespa's document processors for enrichment at feed time
- feed via the `/document/v1/` API supports conditional puts, updates, removes

### 4. search improvements

what we have is basic BM25. to make search actually good:
- **query understanding** — spelling correction, synonyms, query rewriting
- **embedding-based search** — add a vector field, use HNSW index for semantic search
- **hybrid ranking** — combine BM25 + vector similarity in a two-phase ranking
- **personalization** — boost results based on user behavior
- **query suggestions** — autocomplete from popular queries

vespa supports all of these natively. adding a vector field looks like:

```
field embedding type tensor<float>(x[384]) {
    indexing: attribute | index
    attribute {
        distance-metric: angular
    }
    index {
        hnsw {
            max-links-per-node: 16
            neighbors-to-explore-at-insert: 200
        }
    }
}
```

### 5. monitoring and alerting

the prometheus endpoint we added is a start. for production:
- scrape with prometheus, visualize with grafana
- key alerts: vespa health down, query latency p99 > threshold, error rate spike
- vespa has built-in metrics for everything — content node fill rate, memory usage, GC pauses
- add request tracing (opentelemetry) to track queries end-to-end

### 6. security

this setup has zero auth. for production:
- TLS everywhere (vespa supports mTLS between nodes)
- authentication on the search API (api keys, oauth, etc)
- network policies — vespa's internal ports shouldn't be exposed
- rate limiting on the search endpoint

### 7. performance tuning

some things to think about:
- **document summaries** — use separate summary classes, don't fetch all fields
- **caching** — vespa has built-in content node summary cache
- **grouping** — expensive, consider caching facet counts
- **JVM tuning** — vespa's container is a JVM app, tune heap size for your workload
- **proton tuning** — content node memory limits, flush strategy, compaction

## resources

if you want to dig deeper into any of this:
- vespa docs on sizing and performance: https://docs.vespa.ai/en/performance/
- vespa sample apps (great for patterns): https://github.com/vespa-engine/sample-apps
- the ranking guide is really good: https://docs.vespa.ai/en/ranking.html
- for k8s deployment: https://docs.vespa.ai/en/operations-selfhosted/docker-containers.html
