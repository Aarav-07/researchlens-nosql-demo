# ResearchLens

Research intelligence for scientific literature: search by meaning, pull matching
work off the internet when a topic is thinly covered, rank it with an explanation
attached to every result, and read or download the paper without leaving the page.

```
query -> local hybrid search -> coverage thin? -> fetch arXiv + OpenAlex -> embed
      -> rank -> group by the job each paper does -> read the PDF in-page
```

## Why it is built this way

Existing discovery tools share a few recurring complaints: recommendations are
opaque, graph-first interfaces overwhelm new users, new papers take weeks to show
up, searches are capped, and semantic similarity drifts into neighbouring fields.
Each of those shaped a decision here.

| Problem in existing tools | What ResearchLens does |
|---|---|
| "No idea why these papers were picked" | Every result carries its score breakdown (meaning, terms, recency, citations) and a plain-language reason |
| Graph-first UI is confusing | Results are a list, grouped by role. The relationship walk is one click deep, never the entry point |
| New papers lag the index by weeks | A poorly covered query triggers a live fetch from the sources before ranking |
| Monthly search caps | None. The corpus is yours |
| Semantic drift across fields | Hybrid anchoring, absolute similarity floors, and the topic shown on every card |
| Reading means leaving for a publisher tab | The PDF streams through the API and renders in-page with PDF.js, one click to download |

## Stack

| Layer | Choice |
|---|---|
| API | FastAPI (Python 3.13), synchronous handlers in the threadpool |
| Database | MongoDB — documents match the shape of paper metadata, and vectors live on the paper itself |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2`, 384-d, unit-norm |
| Vector search | Exact cosine over a numpy matrix held in process; MongoDB Atlas `$vectorSearch` when the URI points at Atlas |
| Keyword search | Weighted Mongo text index (title 10 / topics 5 / authors 3 / abstract 1); Atlas Search when available |
| Sources | arXiv and OpenAlex, both keyless |
| Client | React 19 + TypeScript + Vite + Tailwind v4, PDF.js for reading |

Both the vector index and the search backend sit behind interfaces, so moving to
Atlas — or to FAISS, or pgvector — is one class, not a rewrite.

## Running it

### Docker (whole stack)

```bash
cp .env.example .env        # optional; every value has a default
docker compose up --build
```

Then open <http://localhost:8080>. The compose file starts MongoDB, the API, and
nginx serving the built client with `/api` proxied to the API, so the browser
stays same-origin and never needs CORS.

The embedding model is baked into the API image at build time, so a cold
container is fast and a hub outage cannot silently degrade search quality.

### Free Render deployment

The root `render.yaml` deploys a free API web service and a free static site.
The API uses the lightweight hashing embedder to fit the free service's memory
limit; semantic ranking is less accurate than with the transformer model.

1. Push this repository to GitHub and choose **New > Blueprint** in Render,
  then connect the repository and select `render.yaml`.
2. Enter your Atlas URI when Render prompts for `RL_MONGODB_URI`. Add the API
  service's outbound IP ranges from Render to the Atlas project's Network
  Access allowlist. The Atlas user needs read/write access to `researchlens`.
3. Wait for both services to deploy, then open the `researchlens-web` URL. The
  API health endpoint is at `https://<api-host>/api/health`.

The API CORS setting allows all origins for this public demo. Restrict
`RL_CORS_ORIGINS` to the frontend's Render URL in the API service settings if
you want to limit browser origins. Free API services spin down after 15 minutes
of inactivity, so the first request after idle can take about a minute. The
free API image omits the transformer dependency; install `requirements-ml.txt`
for a local or paid deployment with the full model.

### Local development

Requires Python 3.13, Node 22, and a MongoDB reachable on `RL_MONGODB_URI`
(default `mongodb://localhost:27017`).

```bash
cd backend
pip install -r requirements-ml.txt
cp .env.example .env
uvicorn main:app --reload --port 8011
```

```bash
cd frontend
npm install
npm run dev          # http://localhost:5174, /api proxied to 8011
```

Seed a corpus, or just search — a thinly covered query fetches its own papers:

```bash
curl -X POST "http://127.0.0.1:8011/api/ingest" \
  -H "Content-Type: application/json" \
  -d '{"query": "graph neural networks for recommendation", "limit_per_source": 25}'
```

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Liveness, corpus counters, and whether embeddings are degraded |
| `GET /api/discover?q=&mode=&limit=&live=true` | Search, live-fetch when coverage is thin, and group the results. What the UI calls |
| `GET /api/search?q=&mode=hybrid\|semantic\|keyword&limit=` | Search only |
| `GET /api/recommend?q=` | Grouped recommendations only |
| `GET /api/papers?limit=&offset=&source=&topic=&sort=` | Browse the corpus |
| `GET /api/papers/{id}` | One paper |
| `GET /api/papers/{id}/similar` | Related work by vector neighbourhood |
| `GET /api/papers/{id}/file?download=false` | Stream the PDF through the API |
| `GET /api/papers/topics` | Topic facets |
| `POST /api/ingest` | Fetch a query from the sources into the corpus |
| `POST /api/ingest/embed` | Backfill missing vectors |

Interactive docs at `/docs`.

## How ranking works

Three modes, one result shape:

- **Terms** — weighted keyword match on the Mongo text index.
- **Meaning** — cosine between the query embedding and each paper embedding.
- **Hybrid** (default) — `0.7 × meaning + 0.3 × terms`, plus small nudges for
  recency (0.06, three-year half-life) and citations (0.04, log-compressed).

Two guards keep results honest, both learned from real failures:

1. **An absolute similarity floor** (`RL_SEARCH_MIN_SIMILARITY`, default 0.28).
   Vector search returns the K nearest neighbours however distant they are, so
   without a floor an unanswerable query comes back full of confident-looking
   but unrelated papers. An exact keyword match still passes on its own evidence.
2. **Coverage is measured by depth, not by the best hit.** A corpus collected for
   one narrow topic always has something adjacent to a neighbouring query, so a
   top-score test lets that query be answered out of the wrong literature. A topic
   counts as covered only when `RL_LIVE_MIN_RESULTS` papers clear
   `RL_LIVE_GOOD_SIMILARITY`; otherwise the sources are fetched first.

`score` and `score_parts` are min-max normalized within a result set, so they are
only meaningful relative to each other. Every hit also carries `similarity`, the
raw cosine, which is comparable across searches — that is what the guards read
and what the status line reports as "best match".

## Grouping

Results are grouped by the job a paper does for the reader, each group with an
explicit floor so a thin group stays empty rather than padding itself:

| Group | Contents |
|---|---|
| Closest to your query | Best combined match on meaning and terms |
| Recent work | Published recently and still relevant |
| Foundational | Older, heavily cited work the area builds on |
| Adjacent | Related methods worth a look |

## Configuration

Environment variables, all prefixed `RL_`, read from `backend/.env` or the
process environment. Full list with defaults in `backend/.env.example`.

| Variable | Default | Meaning |
|---|---|---|
| `RL_MONGODB_URI` | `mongodb://localhost:27017` | Community server or an Atlas SRV URI |
| `RL_MONGODB_DB` | `researchlens` | Database name |
| `RL_SEARCH_BACKEND` | `auto` | `atlas` unlocks `$search` / `$vectorSearch`; `auto` probes for it |
| `RL_EMBEDDING_BACKEND` | `auto` | `sentence_transformers` in deployments — see the warning below |
| `RL_EMBEDDING_MODEL_NAME` | `sentence-transformers/all-MiniLM-L6-v2` | Any sentence-transformers model |
| `RL_SEARCH_MIN_SIMILARITY` | `0.28` | Absolute floor for showing a result |
| `RL_LIVE_SEARCH_ENABLED` | `true` | Whether thin coverage triggers a fetch |
| `RL_LIVE_GOOD_SIMILARITY` | `0.52` | A hit must be this close to count as coverage |
| `RL_LIVE_MIN_RESULTS` | `8` | How many good matches mean a topic is covered |
| `RL_LIVE_COOLDOWN_HOURS` | `12` | Per-query fetch cooldown |
| `RL_HYBRID_SEMANTIC_WEIGHT` | `0.7` | Meaning weight in hybrid |
| `RL_HYBRID_KEYWORD_WEIGHT` | `0.3` | Terms weight in hybrid |
| `RL_OPENALEX_MAILTO` | — | Your email; puts requests in OpenAlex's polite pool |

### One warning worth reading

`RL_EMBEDDING_BACKEND=auto` falls back to a built-in hashing embedder when the
model cannot be loaded. That keeps the project runnable offline, but the fallback
is much weaker and its vectors live in a different space from the real model's.
A transient load failure once downgraded a running server, whose next ingest
re-embedded the whole corpus in that weaker space and quietly wrecked search
quality.

The loader now retries (including from the local cache only), refuses to
overwrite another model's vectors while degraded, and reports
`embedding_degraded` from `/api/health`. Set `sentence_transformers` explicitly
in any deployment so a failure is loud instead of silent — the compose file
already does.

If a corpus does end up mixed, repair it:

```bash
python scripts/maintenance.py reembed   # rebuild every vector with the active model
```

## Maintenance

```bash
python scripts/maintenance.py stats     # corpus counters
python scripts/maintenance.py dedupe    # merge records that share a title
python scripts/maintenance.py embed     # embed anything missing a vector
python scripts/maintenance.py reembed   # rebuild every vector with the active model
```

## Deduplication

The same paper arrives from arXiv and OpenAlex under different identifiers, so
records collapse on a fingerprint — DOI, then arXiv id, then a normalized title
hash — with a second pass that merges records agreeing only on the title. The
discarded identifier is kept in `alt_fingerprints` so the same paper arriving
under it later resolves to the existing document. Merges never overwrite a value
with an empty one: the longer abstract wins, and citation counts only ever rise.

## Tests

```bash
cd backend && pytest -q
```

Fingerprinting, dedupe, score normalization, the coverage rule, and the group
assembly are covered. The repository tests talk to a real MongoDB using a
throwaway database, because dedupe depends on index behaviour a mock would not
reproduce; they skip when no MongoDB is reachable.

## Project layout

```
backend/
  main.py                  FastAPI app and entrypoint
  researchlens/
    config.py              env-driven settings, no business logic
    db.py                  Mongo client, index management, Atlas detection
    documents.py           the paper document shape and fingerprinting
    repository.py          every Mongo query the app issues
    schemas.py             API contracts
    sources/               arXiv and OpenAlex adapters behind one interface
    ingest/                fetch -> dedupe -> upsert -> embed
    ml/                    embedders and the vector index
    search/                keyword, semantic, hybrid, grouping, live fetch
    api/                   routers
  scripts/maintenance.py   dedupe, embed, reembed, stats
frontend/
  src/components/          the UI, one component per surface
  src/lib/                 API client, formatting, types
```

## Roadmap

Interaction tracking and a per-user preference vector are the next step: the
ranking layer already takes weighted signals, so personalization slots into the
hybrid combiner rather than replacing it. Full-text and OCR ingestion would feed
the same embedding path at section granularity.
