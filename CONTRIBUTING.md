# Contributing to DevPath Navigator

Thanks for collaborating. This is a hackathon repo on a free private
GitHub account, which means **branch protection rules aren't enforced
by GitHub itself** (that requires GitHub Pro or a public repo). The
guard rails below are enforced socially — please follow them.

## 1. Branch & PR workflow

- **Never push directly to `main`.** Always branch first.
  ```bash
  git checkout main
  git pull --ff-only origin main
  git checkout -b <category>/<short-slug>
  # e.g. feat/cluster-map-zoom, fix/agent-timeout, docs/architecture-refresh
  ```
- **Every change ships as a PR.** Open a PR from your branch into
  `main`. Self-merge is fine for solo PRs, but the PR + CI flow is
  the audit trail.
- **CI must be green before merging.** Four jobs run on every PR at
  time of writing: `Lint & test (Python)`, `Build (frontend)`,
  `E2E (Playwright)`, `Secret scan`. `.github/workflows/ci.yml` is the
  source of truth — if this list drifts, trust the workflow. Don't
  merge a red PR — even if you're confident the failure is unrelated,
  open a follow-up rather than bypassing.
- **Squash on merge.** Keeps `main` linear and each PR collapses to
  one commit referencing the PR number.

## 2. Issue & PR linking

- **Open an Issue first.** Even small changes — it keeps the queue
  searchable.
- **Reference it in the PR body** with `close #<issue>` (or `closes`,
  `fix`, `resolves` — GitHub treats them the same). That auto-closes
  the issue when the PR merges.
- **Set yourself as assignee** on both the Issue and the PR. We use
  the assignee to know who's actively working on what.

## 3. Commits

- **Use your GitHub no-reply email as the commit author.** This keeps
  personal/work email addresses out of the public history if we flip
  the repo to public for the hackathon submission. For
  `muroshima` the no-reply is
  `103478594+muroshima@users.noreply.github.com`. Configure once per
  clone:
  ```bash
  git config user.email '<your-id>+<your-handle>@users.noreply.github.com'
  git config user.name '<Your Name>'
  ```
  Find your own no-reply on GitHub under **Settings → Emails →
  "Keep my email addresses private"**.
- **Don't add AI-tool co-author lines** like `Co-Authored-By: Claude
  <noreply@anthropic.com>` or `Co-Authored-By: Codex <codex@openai.com>`,
  and don't append `🤖 Generated with [Claude Code]` / similar
  footers in commit messages or PR bodies. Commits stand under your
  own name regardless of how they were produced.
- **Conventional commit prefixes** are encouraged for readability:
  `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`, `ui:`, `test:`.

## 4. Local checks before pushing

Run the same things CI runs:

```bash
# Python
uv run ruff check
uv run pytest tests/ -x

# Frontend (when touching frontend/)
cd frontend
npm run build

# Secrets — a paranoid check before any commit that touches new files
docker run --rm -v "$PWD:/path" zricethezav/gitleaks:latest detect \
  -s /path --no-banner --redact
```

## 5. Reviewing PRs

- **Copilot reviews are automatic and machine — fix or rebut them
  freely.** When you fix, leave a reply comment with the fix commit
  SHA and resolve the thread. When you disagree, leave a reply
  explaining why and resolve. The PR author handles their own
  Copilot loop.
- **Human review replies should not be sent unilaterally by an AI
  agent on the author's behalf** — draft the reply first, the author
  posts it after a sanity check. (Past incidents in adjacent repos:
  AI agents have machined responses to nuanced human feedback and
  missed the point.)

## 6. Things to flag before they ship

- Anything that exposes the public Cloud Run endpoints to abuse
  vectors not already covered (rate-limit, CORS, input length cap).
- Adding GCP API calls that incur per-call cost (Vertex AI, BigQuery
  jobs) without a cap or budget tie-in.
- Backward-incompatible changes to tool return shapes that the
  frontend consumes — the contract is in `frontend/src/lib/types.ts`
  and tool docstrings.

## 7. Pending repo-wide tasks (read once)

- This repo is **private** for the hackathon dev phase. When we flip
  it to public, branch protection becomes available and should be
  enabled — see issue tracker for the open task.
- Production deploy is **manual** today (`gcloud run deploy --source
  . --region asia-northeast1`). A merge to `main` does **not**
  auto-deploy. Promote new revisions explicitly after merging.

That's it. Open an issue or ping if anything's unclear.
