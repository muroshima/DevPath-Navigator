"""Taxonomy loader and normalization helpers.

Loads `data-gen/taxonomy.yaml` once at import time and exposes:
- TAXONOMY               : raw dict
- ROLES, SENIORITY       : sets of valid bare tokens
- TECH_TOKENS            : set of valid "category.tool" tokens
- ALL_TECH_BY_NAME       : map from bare tool name → fully-qualified token
- ALIAS_MAP              : hand-curated common aliases for natural-language inputs
- normalize_token        : best-effort mapping from a free-form token to a taxonomy token
- normalize_trajectory   : apply normalize_token to a (role, tech, seniority) tuple
- taxonomy_summary       : Markdown summary used in the system instruction
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
_CANDIDATE_PATHS = [
    REPO_ROOT / "data-gen" / "taxonomy.yaml",                 # local dev
    Path("/app/data-gen/taxonomy.yaml"),                       # container
]


def _load() -> dict[str, Any]:
    for p in _CANDIDATE_PATHS:
        if p.exists():
            with p.open() as f:
                return yaml.safe_load(f)
    raise FileNotFoundError(
        f"taxonomy.yaml not found in any of: {[str(p) for p in _CANDIDATE_PATHS]}"
    )


TAXONOMY: dict[str, Any] = _load()
ROLES: set[str] = set(TAXONOMY["roles"])
SENIORITY: set[str] = set(TAXONOMY["seniority"])

TECH_TOKENS: set[str] = set()
ALL_TECH_BY_NAME: dict[str, str] = {}
for _category, _items in TAXONOMY["tech"].items():
    for _item in _items:
        _fq = f"{_category}.{_item}"
        TECH_TOKENS.add(_fq)
        ALL_TECH_BY_NAME[_item.lower()] = _fq

# Hand-curated aliases. Lowercase keys.
ALIAS_MAP: dict[str, str] = {
    "k8s": "infra.kubernetes",
    "kube": "infra.kubernetes",
    "postgresql": "data.postgres",
    "psql": "data.postgres",
    "pg": "data.postgres",
    "js": "lang.javascript",
    "ts": "lang.typescript",
    "node": "web.nodejs",
    "node.js": "web.nodejs",
    "next": "web.nextjs",
    "next.js": "web.nextjs",
    "tf": "infra.terraform",
    "terraform": "infra.terraform",
    "gke": "infra.gcp",
    "gcp": "infra.gcp",
    "aws": "infra.aws",
    "azure": "infra.azure",
    "go": "lang.go",
    "golang": "lang.go",
    "python": "lang.python",
    "java": "lang.java",
    "kotlin": "lang.kotlin",
    "scala": "lang.scala",
    "ruby": "lang.ruby",
    "swift": "lang.swift",
    "c#": "lang.csharp",
    "csharp": "lang.csharp",
    "react": "web.react",
    "vue": "web.vue",
    "django": "web.django",
    "rails": "web.rails",
    "spark": "data.spark",
    "kafka": "data.kafka",
    "airflow": "data.airflow",
    "dbt": "data.dbt",
    "bigquery": "data.bigquery",
    "bq": "data.bigquery",
    "snowflake": "data.snowflake",
    "redis": "data.redis",
    "mongo": "data.mongodb",
    "mongodb": "data.mongodb",
    "mysql": "data.mysql",
    "pytorch": "ml.pytorch",
    "torch": "ml.pytorch",
    "tensorflow": "ml.tensorflow",
    "tf-keras": "ml.tensorflow",
    "huggingface": "ml.huggingface",
    "hf": "ml.huggingface",
    "langchain": "ml.langchain",
    "vertex": "ml.vertex_ai",
    "vertex_ai": "ml.vertex_ai",
    "mlflow": "ml.mlflow",
    "sklearn": "ml.scikit_learn",
    "scikit-learn": "ml.scikit_learn",
    "rn": "mobile.react_native",
    "react native": "mobile.react_native",
    "react_native": "mobile.react_native",
    "flutter": "mobile.flutter",
    "swiftui": "mobile.swift_ui",
    "swift_ui": "mobile.swift_ui",
    "jetpack compose": "mobile.jetpack_compose",
    "jetpack_compose": "mobile.jetpack_compose",
    # role aliases — we keep these too for normalize_role
    "sre engineer": "sre",
    "site reliability": "sre",
    "platform engineer": "platform",
    "engineering manager": "em",
    "product manager": "pm",
    "data engineer": "data_engineer",
    "ml engineer": "ml_engineer",
    "machine learning engineer": "ml_engineer",
    "ai engineer": "ml_engineer",
    "generative ai engineer": "genai_engineer",
    "genai engineer": "genai_engineer",
}


def normalize_tech(token: str) -> str | None:
    """Map a free-form tech token to a taxonomy 'category.tool' token, or None if no match."""
    if not token:
        return None
    raw = token.strip().lower().replace("-", "_")
    if raw in TECH_TOKENS:
        return raw
    if raw in ALIAS_MAP:
        out = ALIAS_MAP[raw]
        return out if out in TECH_TOKENS else None
    if raw in ALL_TECH_BY_NAME:
        return ALL_TECH_BY_NAME[raw]
    # Suffix match across categories ("postgres" → "data.postgres")
    for cat_dot_tool in TECH_TOKENS:
        if cat_dot_tool.split(".", 1)[1] == raw:
            return cat_dot_tool
    return None


def normalize_role(token: str) -> str | None:
    if not token:
        return None
    raw_lower = token.strip().lower().replace("-", " ")  # keep spaces for alias lookup
    raw_underscore = raw_lower.replace(" ", "_")
    if raw_underscore in ROLES:
        return raw_underscore
    # Alias map uses both space- and underscore-separated keys
    if raw_lower in ALIAS_MAP and ALIAS_MAP[raw_lower] in ROLES:
        return ALIAS_MAP[raw_lower]
    if raw_underscore in ALIAS_MAP and ALIAS_MAP[raw_underscore] in ROLES:
        return ALIAS_MAP[raw_underscore]
    # Fall back to substring match on role tokens
    for r in ROLES:
        if raw_underscore == r or raw_underscore in r:
            return r
    return None


def normalize_seniority(token: str) -> str | None:
    if not token:
        return None
    raw = token.strip().lower()
    if raw in SENIORITY:
        return raw
    return None


def normalize_trajectory(
    steps_roles: list[list[str]],
    steps_role_years: list[list[float]],
    steps_tech: list[list[str]],
    steps_seniority: list[str],
) -> dict:
    """Normalize a multi-role-per-step trajectory against the taxonomy.

    Returns parallel arrays of the same shape, plus `corrections` (per-category
    mapping original→normalized) and `unresolved` (tokens that could not be
    placed and were dropped from the output).
    """
    corrections: dict[str, dict[str, str]] = {"role": {}, "tech": {}, "seniority": {}}
    unresolved: dict[str, list[str]] = {"role": [], "tech": [], "seniority": []}

    n_steps = max(len(steps_roles), len(steps_role_years), len(steps_tech), len(steps_seniority))
    # Pad short arrays with empties so we can iterate uniformly.
    def _pad(arr, fill):
        return list(arr) + [fill] * (n_steps - len(arr))
    sr = _pad(steps_roles, [])
    sy = _pad(steps_role_years, [])
    st = _pad(steps_tech, [])
    ss = _pad(steps_seniority, "")

    out_roles: list[list[str]] = []
    out_years: list[list[float]] = []
    out_tech: list[list[str]] = []
    out_sen: list[str] = []

    for i in range(n_steps):
        step_roles_out: list[str] = []
        step_years_out: list[float] = []
        roles_i = sr[i] or []
        years_i = sy[i] or []
        # If years array doesn't align with roles array, default missing years to 1.0
        for j, raw in enumerate(roles_i):
            n = normalize_role(raw)
            if n is None:
                unresolved["role"].append(raw)
                continue
            if n != raw:
                corrections["role"][raw] = n
            yrs = float(years_i[j]) if j < len(years_i) and years_i[j] is not None else 1.0
            step_roles_out.append(n)
            step_years_out.append(yrs)
        out_roles.append(step_roles_out)
        out_years.append(step_years_out)

        step_tech_out: list[str] = []
        for t in st[i] or []:
            n = normalize_tech(t)
            if n is None:
                unresolved["tech"].append(t)
            else:
                if n != t:
                    corrections["tech"][t] = n
                step_tech_out.append(n)
        out_tech.append(step_tech_out)

        sen_norm = normalize_seniority(ss[i])
        if sen_norm is None and ss[i]:
            unresolved["seniority"].append(ss[i])
            out_sen.append("mid")  # safest non-empty default
        else:
            out_sen.append(sen_norm or "mid")

    return {
        "steps_roles": out_roles,
        "steps_role_years": out_years,
        "steps_tech": out_tech,
        "steps_seniority": out_sen,
        "corrections": corrections,
        "unresolved": unresolved,
    }


def taxonomy_summary() -> str:
    """Compact Markdown summary intended for the agent system instruction."""
    lines = ["Roles: " + ", ".join(sorted(ROLES))]
    lines.append("Seniority: " + ", ".join(["junior", "mid", "senior", "staff", "manager"]))
    lines.append("Tech tokens (use the fully-qualified 'category.tool' form):")
    for cat, items in TAXONOMY["tech"].items():
        lines.append(f"  - {cat}.* — " + ", ".join(items))
    return "\n".join(lines)
