# PhotoAssistant

A photo editing style recommendation system with a web editor.

The user uploads a photograph, and based on its content the system suggests **three
stylistically different edits**. The suggestions are applied and fine-tuned in an editor with a
live preview, and the work is saved non-destructively per project — every saved version is a
complete "recipe", not a modified image.

The suggestions are not generated from rules but learned from examples: an offline pipeline
processes 25,000 expert edits from the [MIT-Adobe FiveK](https://data.csail.mit.edu/graphics/fivek/)
dataset, reconstructs each of them as a set of parameters in the project's own edit schema, and
indexes them as vectors. Instead of a single "optimal" solution, the system offers several
different ones, because photo editing is subjective.

Bachelor thesis — Faculty of Science, University of Kragujevac.
**Status:** the entire user flow works end to end; work on the application continues.

## What the application can do

- **Registration and sign-in** (ASP.NET Core Identity + JWT).
- **Photo upload** — two derived copies are made from it: 512 px for search and 2048 px for the
  editor. An upload opens a project.
- **Three edit suggestions** — the photograph is encoded with CLIP, similar scenes are found in
  the database, and three are chosen from their expert edits. The suggestion thumbnails are drawn
  by the browser, with the same renderer the editor uses, so what you pick is exactly what you get.
- **Editor with a live preview** — every edit schema parameter plus a tone curve with control
  points, over the 2048 px copy through WebGL2, without a single server call per slider move.
  Before/after comparison, undo/redo, works on narrow screens.
- **Versions** — every saved version is the complete recipe. An earlier version is opened from the
  strip on the left, and restoring it creates a **new** version: history is never overwritten.
- **Full-resolution export** — the untouched original is rendered in the background, through a
  job queue. The output is a lossless PNG. All of a project's exported files are available from its
  card.

## How it works

```
upload → derivatives (512 / 2048) → content embedding → similar-photo search
       → candidate-edit pool → pick three → editor → versions → export
```

An edit is described by the **edit schema** — a versioned JSON record with 11 parameters (white
balance, tone adjustments, colour, tone curve). Every part of the system uses the same record, so a
"recipe" is portable across the pipeline, the database, the editor and export.

The key consequence: edits from the dataset are not translated from Lightroom parameters but
**reconstructed from the result** — the system searches for the values of its own parameters that,
applied to the original image, come closest to the expert's version. The system would work the
same way if the edit had been made in any other tool.

The renderer has two implementations — NumPy for the server and the pipeline, WebGL2 for the live
preview in the browser. Both translate the same specification ([`docs/RENDERER_SPEC.md`](docs/RENDERER_SPEC.md)),
and their agreement is proven by a test over a fixed set of images and recipes: 295 combinations,
worst pixel ΔE 0.108 against a threshold of 3.

## Technologies

| Layer | Technology |
|---|---|
| Frontend | Angular 22 (zoneless, signals), Angular CDK, WebGL2 renderer |
| Backend | .NET 10, ASP.NET Core Identity + JWT, Clean Architecture |
| ML service | Python 3.14, FastAPI, NumPy, PyTorch (CLIP) |
| Database | PostgreSQL 18 + pgvector (HNSW) |
| Storage | MinIO (S3 API) |

## Structure

```
backend/    .NET API — the only public entry point (auth, projects, history, orchestration)
frontend/   Angular SPA with the editor
ml/         Python package (library) + FastAPI service (internal)
pipeline/   offline scripts that import the same Python package
fixtures/   shared test data for the agreement tests
infra/      docker-compose, nginx, database init scripts
docs/       renderer specification and documents for the mentors
sandbox/    research scripts, not part of the deliverable
```

## Running it, from scratch

The application consists of two parts that come into being differently: the **services** are
started with a single command, while the **corpus** — the 25,000 edits the recommendation works
over — is built once, by an offline pipeline over the FiveK dataset. Without the corpus the
application runs, but the suggestions have nothing to be chosen from. The steps below are in the
order in which they are run.

Requirements: Docker, [uv](https://docs.astral.sh/uv/) (the Python environment for the pipeline),
about 60 GB of free space (dataset archive ~50 GB, derived copies ~12 GB), and a stable
connection — the pipeline downloads about 1.6 TB. All commands are run from the repository root.

### 1. Configuration

```bash
cp .env.example .env        # fill in the values; FIVEK_DATASET_PATH can stay empty for now
```

Put values that contain a space (e.g. the dataset path) in quotes; otherwise the file cannot be
loaded from a shell.

### 2. Services

```bash
docker compose --env-file .env -f infra/docker-compose.yml up -d
docker compose --env-file .env -f infra/docker-compose.yml ps    # wait until all are healthy
```

The first start builds three images (the ML image is about 2 GB, because it carries PyTorch) and
takes around ten minutes. On startup the API **migrates the database**, and a helper container
creates three buckets in storage — these are prerequisites for the pipeline, so this step comes
before it.

From this point on the application is available at http://localhost:4200, but with an empty corpus.

### 3. Dataset

Download the archive (about 50 GB) from the [FiveK dataset page](https://data.csail.mit.edu/graphics/fivek/)
and extract it, then set `FIVEK_DATASET_PATH` in `.env` to the extracted directory. From it the
pipeline reads the catalogue `raw_photos/fivek.lrcat` and the lists `filesAdobe.txt` and
`filesAdobeMIT.txt`; it downloads the photographs and expert edits themselves separately, in step 4.

FiveK is under a **research licence with no commercial use**. Its images are not in the repository
or in the test data, and are not part of the deliverable.

The pipeline only reads the dataset directory; the catalogue is a SQLite database and is opened
strictly read-only.

### 4. Corpus

The commands set up the Python environment themselves (`uv run`); only step 4.5 needs `--extra
embeddings`, because it is the only one that runs CLIP. The pipeline reads `.env` on its own. Every
step is repeatable and resumes where it left off — state is kept in the database, so an
interrupted step is simply run again.

| | Step | What it does | Duration |
|---|---|---|---|
| 4.1 | `uv run --project ml python -m pipeline.parse_catalogue` | reads the catalogue: 5,000 photographs, 25,000 edits | seconds |
| 4.2 | `uv run --project ml python -m pipeline.fetch_derive` | downloads the original and the five expert versions of every photograph, writes 512 px and 2048 px copies to storage, and deletes the original | ~9 h |
| 4.3 | `uv run --project ml python -m pipeline.fit_all` | for every expert edit, searches for the values of our parameters that give the closest result | one night |
| 4.4 | `uv run --project ml python -m pipeline.refit_worst --confirm` | a more thorough search over the worst 5%; never makes things worse | ~3 h, optional |
| 4.5 | `uv run --project ml --extra embeddings python -m pipeline.embed_all --content` | a CLIP vector for every photograph, for content search | minutes |
| 4.6 | `uv run --project ml python -m pipeline.embed_all --style` | a style fingerprint for every edit | minutes |
| 4.7 | `uv run --project ml python -m pipeline.publish --confirm` | records the 19 edits the schema cannot represent and checks that everything is complete | seconds |

**The order is mandatory.** The fingerprint in 4.6 is computed from the recipes, so it must come
after fitting *and* after 4.4, which rewrites the recipes of the worst 5% — fingerprints computed
before that would describe recipes that no longer exist, and nothing would report it. The
fingerprint scaling constants are in the repository
(`pipeline/reports/fingerprint_scaling.json`) and are not recomputed.

Running `pipeline.publish --verify` before 4.7 shows what is missing, without writing anything.

For a smaller corpus, `fetch_derive` and `fit_all` accept `--experts` (e.g. `--experts c` for a
single expert — about a third of the transfer). The measurements in the thesis were made over all
five.

### 5. Done

After step 4 the application at http://localhost:4200 gives suggestions. The services do not need
to be restarted — the recommendation reads the corpus from the database on every request.

| | Address |
|---|---|
| Application | http://localhost:4200 |
| Health | http://localhost:4200/health |
| API documentation (outside production) | http://localhost:8080/scalar/v1 |
| OpenAPI document (outside production) | http://localhost:8080/openapi/v1.json |
| MinIO console | http://localhost:9001 |

The ML service deliberately has no published port — it is internal and reachable only by the .NET
API, and nginx proxies only `/api/` and `/health`. The first request for suggestions downloads the
CLIP weights (about 600 MB) into the `mlcache` volume, so it takes a few seconds longer.

### Stopping

```bash
docker compose --env-file .env -f infra/docker-compose.yml down      # data is kept
```

> **`down -v` also deletes the volumes** — the database with the corpus and the storage with the
> derived copies, and rebuilding them is the whole of step 4. Do not use it as a way to stop.

## Development

For day-to-day work only the database and storage run in Docker, and the services run locally:

```bash
docker compose --env-file .env -f infra/docker-compose.yml up -d postgres minio

dotnet run --project backend/src/PhotoAssistant.Api --urls http://localhost:8080
npm --prefix frontend start                                   # http://localhost:4200
```

The ML service, when run locally, **does not read `.env` on its own**; in the container, compose
provides its variables. On the host they are set from `.env`, renamed to the names the container
uses:

```bash
set -a; source .env; set +a
export POSTGRES_HOST=$POSTGRES_HOST_LOCAL S3_ENDPOINT=$S3_ENDPOINT_LOCAL \
       S3_ACCESS_KEY=$MINIO_ROOT_USER S3_SECRET_KEY=$MINIO_ROOT_PASSWORD
uv run --project ml --extra service --extra embeddings uvicorn service.main:app --port 8000
```

`--extra embeddings` is needed for suggestions, because they compute a CLIP vector on every
request; without it the service runs, but `POST /recommend` refuses.

Two pitfalls:

- `dotnet build` fails while the local API is running, because it holds its DLLs — stop it first.
- The dev server does not notice a **new** lazily loaded route; restart it after adding a route.

## Tests

```bash
dotnet test backend/PhotoAssistant.slnx
uv run --project ml --extra service pytest ml/tests pipeline/tests
uv run --project ml --extra service ruff check ml fixtures pipeline
npm --prefix frontend test
npm --prefix frontend run format:check
```

The shader tests run in a real browser, so the first time they need Playwright:

```bash
npx --prefix frontend playwright install chromium
npm --prefix frontend run test:browser
```

Agreement between the two renderers is measured in two steps, because ΔE is computed only in
Python — the first renders in the browser, the second compares:

```bash
npm --prefix frontend run golden
uv run --project ml --extra service pytest ml/tests/golden
```

The backend integration tests need the Postgres container to be up and use a separate database,
so that development data stays untouched.
