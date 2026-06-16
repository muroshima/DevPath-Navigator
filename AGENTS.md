# AGENTS.md

Instructions for AI coding agents (Claude Code, Antigravity, Cursor, etc.) working on this repo. Human contributors: see [README.md](./README.md) for the project pitch and [CONTRIBUTING.md](./CONTRIBUTING.md) for branch / commit conventions.

## What this project is

**DevPath Navigator** — a hackathon entry for *DevOps × AI Agent Hackathon 2026*. It vectorizes synthetic career trajectories of software engineers, projects them onto a 2D map (UMAP + HDBSCAN), and lets a Gemini agent recommend "what to do next" grounded in the actual moves of similar engineers.

Stack:

- **Agent**: FastAPI + [Google Agent Development Kit](https://github.com/google/adk) + Gemini 2.5 Flash via Vertex AI
- **Frontend**: Next.js 15 (App Router) + React 19 + TypeScript + Tailwind CSS
- **Data**: BigQuery (`VECTOR_SEARCH`) with synthetic-only trajectories
- **Embedding**: gensim Word2Vec (local, deterministic) → UMAP → HDBSCAN
- **Retrain loop**: Cloud Build → eval gate → `gcloud run services update`
- **Hosting**: Cloud Run + Terraform (`infra/`)

Synthetic data only — no real personnel data ever enters the repo.

## Repository layout

```
agent/            FastAPI server + ADK agent. 7 tools in agent/tools/: normalize_profile, locate_user, find_similar_trajectories, skill_gap_analysis, recommend_next_steps, explain_cluster, nlq_over_corpus
embedding/        Word2Vec training + UMAP + HDBSCAN
eval/             Metrics, retrain gate, BigQuery store
data-gen/         Synthetic trajectory generator (fixed-seed reproducible)
pipelines/        Cloud Build + drift injection scripts
frontend/         Next.js app (map + chat + reasoning log)
infra/            Terraform (Cloud Run, IAM, BigQuery dataset, budgets)
tests/            Pytest suites (taxonomy, gate, tokens, rate limit, NLQ validator)
docs/             Architecture diagrams + demo videos
scripts/demo/     Playwright + edge-tts video pipeline
```

## Setup

```bash
# Python (uv-managed; pyproject pins to >=3.11)
uv sync

# Frontend — use `--prefix` so every command in this file runs from repo root
npm --prefix frontend install
```

Authenticate to GCP if you need to touch real Vertex AI / BigQuery:

```bash
gcloud auth application-default login
gcloud config set project <your-project-id>
```

For purely local work (running tests, building the frontend), no GCP credentials are required.

## Build / run

```bash
# Agent — uses BigQuery for trajectories; needs ADC
AGENT_BATCHES=initial,drift uv run uvicorn agent.server:app --host 127.0.0.1 --port 8088

# Frontend dev — point at the local agent
AGENT_URL=http://127.0.0.1:8088 npm --prefix frontend run dev

# Frontend prod build (validates types + bundles)
npm --prefix frontend run build
```

## Test

Run the relevant subset for what you touched; CI runs all of them:

```bash
# Python: lint + tests (~30s)
uv run ruff check .
uv run pytest -q

# Frontend: typecheck + build (no separate typecheck script — build catches it)
npm --prefix frontend run build

# Frontend: e2e (Playwright). Both API routes are mocked, so no agent / no GCP
# credentials needed. Playwright auto-boots a production frontend build via
# its `webServer` config (`npm run build && npm run start`).
npm --prefix frontend run test:e2e
```

CI (`.github/workflows/ci.yml`) runs on every PR and on pushes to `main` — not on arbitrary branch pushes. Four jobs at time of writing: **Lint & test (Python)** (ruff + pytest as steps), **Build (frontend)**, **E2E (Playwright)**, and **Secret scan**. The workflow file is the source of truth — if these get out of sync, trust `.github/workflows/ci.yml`. Branch protection is not enforced yet (the repo is still private for the hackathon — see [CONTRIBUTING.md](./CONTRIBUTING.md) §7), so treat green CI as a social rule: don't merge with red checks.

## Conventions

- **Branch + PR flow only** — never push to `main` directly, even on this personal repo. Branch names: `feat/...`, `fix/...`, `docs/...`. Open issues first, reference them with `close #N` in PR bodies. Details: [CONTRIBUTING.md](./CONTRIBUTING.md).
- **Commit message style**: Conventional Commits-ish, e.g. `feat(frontend): responsive sidebar`, `fix(eval): clamp recall epsilon`. Wrap body at ~72 chars.
- **No Claude/AI co-author trailers** in commits or PRs.
- **Python**: ruff with `select = E,F,I,UP,B,SIM`, line-length 100. `E402` and `E501` are intentionally ignored — see `pyproject.toml` for why.
- **TypeScript / React**: `strict: true`. Avoid `any`; prefer `unknown` + narrowing.
- **Comments**: explain *why*, not *what*. Skip "this function does X" — the code does that. Do call out hidden constraints, invariants, and surprising edge cases.
- **No new files** unless necessary — prefer editing what exists.
- **No emoji** in code or commits unless explicitly requested.

## Hard rules

- **Synthetic data only**. Never commit real personnel data, real names, real `employee_id` mappings to anyone outside the generator's fixed seed.
- **No secrets** in code or commits. Vertex AI / BigQuery credentials come from ADC. Other secrets should live in your OS credential store locally (macOS Keychain, Windows Credential Manager, `pass`, etc.) and Secret Manager in Cloud Run — never in repo files or env files committed to git.
- **eval gate is load-bearing** — see `eval/gate.py`. Don't relax `RECALL_EPS` or `MIN_RECALL_EPS` without re-reading the comments explaining why those thresholds are wider than the textbook 0.05.
- **Prod deploys are explicit, not automatic.** A merge to `main` does NOT auto-deploy — there is no GitHub Actions deploy job today. Application code rolls out via a manual `gcloud run deploy --source . --region asia-northeast1` after the PR merges (see [CONTRIBUTING.md](./CONTRIBUTING.md) §7). Retrain rollouts (model + embeddings) ride the Cloud Build pipeline at `pipelines/cloudbuild.retrain.yaml`, which runs the eval gate and only flips the Cloud Run revision on pass. PR preview revisions go out as no-traffic tagged revisions (`gcloud run deploy --tag preview-pr<N> --no-traffic`) — safe from a laptop because they don't take any prod traffic.

## Where to read first when picking up a task

| You're touching... | Read first |
|---|---|
| Agent tools / prompts | [`agent/agent.py`](./agent/agent.py), [`agent/tools/`](./agent/tools/) |
| Frontend layout / interactions | [`frontend/src/app/page.tsx`](./frontend/src/app/page.tsx), [`frontend/src/components/ClusterMap.tsx`](./frontend/src/components/ClusterMap.tsx) |
| Embedding pipeline | [`embedding/train_w2v.py`](./embedding/train_w2v.py), [`embedding/umap_cluster.py`](./embedding/umap_cluster.py) |
| Eval / retrain loop | [`eval/gate.py`](./eval/gate.py), [`eval/run.py`](./eval/run.py), [`pipelines/cloudbuild.retrain.yaml`](./pipelines/cloudbuild.retrain.yaml) |
| Infra | [`infra/cloudrun.tf`](./infra/cloudrun.tf), [`infra/iam.tf`](./infra/iam.tf) |
| Design rationale (the *why* behind any of the above) | [`ARCHITECTURE.md`](./ARCHITECTURE.md) |
