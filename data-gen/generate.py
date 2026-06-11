"""Synthetic engineer career trajectory generator for DevPath Navigator (v2).

Schema v2 differences vs v1:
- Each step now carries a list of (role, years) pairs instead of a single role
  string. Multi-role steps model engineers who wore more than one hat in the
  same position (e.g. backend + tech-lead).
- `tenure_months` is gone. Per-role years live inside `roles`.
- Trajectories include controlled noise:
  * cross-archetype detours: a small fraction of trajectories get an extra
    "off-path" step from another archetype's role pool, with shorter tenure
  * tech overlap: a small fraction of tech tokens per step come from a wider
    cross-category pool instead of the stage's primary tech list
  * jobhopper still uses random walks but is biased toward more natural
    transitions inside related domains
The combined effect is that HDBSCAN no longer produces a clean 1-cluster-per-
archetype layout — cluster purity drops into the 80–95% range, which matches
what real career data tends to look like.

Two batches are supported:
  - initial: 1,200 employees across the 5 main archetypes
  - drift:   300 employees in ml→genai (reserved for the retraining demo)
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import random
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
TAXONOMY_PATH = REPO_ROOT / "data-gen" / "taxonomy.yaml"
OUTPUT_DIR = REPO_ROOT / "data" / "synthetic"

BATCH_SPECS = {
    "initial": {"size": 1200, "seed": 20260610, "id_offset": 0},
    "drift": {"size": 300, "seed": 20260620, "id_offset": 10000},
}

# Fraction of trajectories that get a cross-archetype "detour" step inserted.
DETOUR_RATE = 0.15
# Per-stage probability that a secondary role joins the primary.
SECONDARY_ROLE_RATE = 0.25
# Fraction of tech slots within a step that come from the wider noise pool
# rather than the stage's primary tech_pool.
TECH_NOISE_RATE = 0.10


@dataclasses.dataclass(frozen=True)
class StageSpec:
    primary_roles: list[str]
    secondary_roles: list[str]
    tech_pool: list[str]
    tech_min: int
    tech_max: int
    seniority_pool: list[str]
    years_min: float
    years_max: float
    optional: bool = False


@dataclasses.dataclass(frozen=True)
class ArchetypeSpec:
    name: str
    weights: dict[str, float]
    stages: list[StageSpec]
    is_jobhopper: bool = False


def _stage(
    primary_roles: list[str],
    tech_pool: list[str],
    tech_min: int,
    tech_max: int,
    seniority_pool: list[str],
    years_min: float = 1.0,
    years_max: float = 4.0,
    secondary_roles: list[str] | None = None,
    optional: bool = False,
) -> StageSpec:
    return StageSpec(
        primary_roles=primary_roles,
        secondary_roles=secondary_roles or [],
        tech_pool=tech_pool,
        tech_min=tech_min,
        tech_max=tech_max,
        seniority_pool=seniority_pool,
        years_min=years_min,
        years_max=years_max,
        optional=optional,
    )


ARCHETYPES: list[ArchetypeSpec] = [
    ArchetypeSpec(
        name="backend_to_sre",
        weights={"initial": 0.25, "drift": 0.0},
        stages=[
            _stage(
                primary_roles=["backend"],
                tech_pool=["lang.java", "lang.python", "lang.go", "data.mysql", "data.postgres", "infra.docker"],
                tech_min=2, tech_max=3,
                seniority_pool=["junior"],
                years_min=1, years_max=3,
            ),
            _stage(
                primary_roles=["backend"],
                tech_pool=["lang.go", "lang.python", "infra.docker", "infra.kubernetes", "infra.gcp", "infra.aws", "data.postgres", "data.redis"],
                tech_min=3, tech_max=5,
                seniority_pool=["mid"],
                years_min=2, years_max=4,
                secondary_roles=["platform"],
            ),
            _stage(
                primary_roles=["sre", "platform"],
                tech_pool=["infra.kubernetes", "infra.terraform", "infra.helm", "lang.go", "lang.python", "infra.linux", "infra.gcp", "infra.aws"],
                tech_min=3, tech_max=5,
                seniority_pool=["mid", "senior"],
                years_min=2, years_max=5,
                secondary_roles=["em"],
            ),
            _stage(
                primary_roles=["sre", "platform"],
                tech_pool=["infra.kubernetes", "infra.terraform", "infra.helm", "lang.go", "infra.linux", "infra.gcp"],
                tech_min=3, tech_max=5,
                seniority_pool=["senior", "staff"],
                years_min=2, years_max=6,
                optional=True,
            ),
        ],
    ),
    ArchetypeSpec(
        name="frontend_to_em",
        weights={"initial": 0.22, "drift": 0.0},
        stages=[
            _stage(
                primary_roles=["frontend"],
                tech_pool=["lang.typescript", "lang.javascript", "web.react", "web.vue"],
                tech_min=2, tech_max=3,
                seniority_pool=["junior"],
                years_min=1, years_max=2,
            ),
            _stage(
                primary_roles=["frontend", "fullstack"],
                tech_pool=["lang.typescript", "web.react", "web.nextjs", "web.nodejs", "web.graphql"],
                tech_min=3, tech_max=4,
                seniority_pool=["mid"],
                years_min=2, years_max=4,
            ),
            _stage(
                primary_roles=["fullstack"],
                tech_pool=["lang.typescript", "web.react", "web.nextjs", "web.nodejs", "data.postgres", "infra.gcp"],
                tech_min=3, tech_max=5,
                seniority_pool=["senior"],
                years_min=2, years_max=4,
                secondary_roles=["em"],
            ),
            _stage(
                primary_roles=["em"],
                tech_pool=["lang.typescript", "web.react"],
                tech_min=1, tech_max=2,
                seniority_pool=["manager"],
                years_min=2, years_max=6,
                optional=True,
            ),
        ],
    ),
    ArchetypeSpec(
        name="data_to_ml",
        weights={"initial": 0.22, "drift": 0.0},
        stages=[
            _stage(
                primary_roles=["data_engineer"],
                tech_pool=["lang.python", "data.bigquery", "data.snowflake", "data.airflow", "data.dbt"],
                tech_min=2, tech_max=3,
                seniority_pool=["junior"],
                years_min=1, years_max=3,
            ),
            _stage(
                primary_roles=["data_engineer"],
                tech_pool=["lang.python", "data.bigquery", "data.snowflake", "data.airflow", "data.dbt", "data.spark", "data.kafka"],
                tech_min=3, tech_max=5,
                seniority_pool=["mid"],
                years_min=2, years_max=4,
                secondary_roles=["ml_engineer"],
            ),
            _stage(
                primary_roles=["ml_engineer"],
                tech_pool=["lang.python", "ml.pytorch", "ml.tensorflow", "ml.scikit_learn", "ml.mlflow", "data.bigquery", "ml.vertex_ai"],
                tech_min=3, tech_max=5,
                seniority_pool=["mid", "senior"],
                years_min=2, years_max=5,
                secondary_roles=["data_engineer"],
            ),
            _stage(
                primary_roles=["ml_engineer"],
                tech_pool=["lang.python", "ml.pytorch", "ml.tensorflow", "ml.mlflow", "ml.vertex_ai", "ml.huggingface"],
                tech_min=3, tech_max=5,
                seniority_pool=["senior", "staff"],
                years_min=2, years_max=6,
                optional=True,
            ),
        ],
    ),
    ArchetypeSpec(
        name="mobile_to_backend",
        weights={"initial": 0.13, "drift": 0.0},
        stages=[
            _stage(
                primary_roles=["mobile"],
                tech_pool=["lang.kotlin", "lang.swift", "mobile.react_native", "mobile.flutter", "mobile.swift_ui", "mobile.jetpack_compose"],
                tech_min=2, tech_max=3,
                seniority_pool=["junior"],
                years_min=1, years_max=3,
            ),
            _stage(
                primary_roles=["mobile"],
                tech_pool=["lang.kotlin", "lang.swift", "lang.typescript", "mobile.react_native", "mobile.flutter"],
                tech_min=2, tech_max=4,
                seniority_pool=["mid"],
                years_min=2, years_max=4,
                secondary_roles=["fullstack"],
            ),
            _stage(
                primary_roles=["backend", "fullstack"],
                tech_pool=["lang.kotlin", "lang.typescript", "lang.go", "infra.docker", "data.postgres", "web.nodejs"],
                tech_min=3, tech_max=5,
                seniority_pool=["mid", "senior"],
                years_min=2, years_max=5,
            ),
        ],
    ),
    ArchetypeSpec(
        name="jobhopper",
        weights={"initial": 0.18, "drift": 0.0},
        is_jobhopper=True,
        stages=[],  # built procedurally
    ),
    ArchetypeSpec(
        name="ml_to_genai",
        weights={"initial": 0.0, "drift": 1.0},
        stages=[
            _stage(
                primary_roles=["ml_engineer"],
                tech_pool=["lang.python", "ml.pytorch", "ml.tensorflow", "ml.scikit_learn", "ml.mlflow", "ml.vertex_ai"],
                tech_min=3, tech_max=5,
                seniority_pool=["mid", "senior"],
                years_min=2, years_max=4,
            ),
            _stage(
                primary_roles=["genai_engineer"],
                tech_pool=["lang.python", "ml.langchain", "ml.huggingface", "ml.vertex_ai", "ml.pytorch"],
                tech_min=3, tech_max=5,
                seniority_pool=["senior", "staff"],
                years_min=1, years_max=4,
                secondary_roles=["ml_engineer"],
            ),
        ],
    ),
]


def load_taxonomy() -> dict[str, Any]:
    with TAXONOMY_PATH.open() as f:
        return yaml.safe_load(f)


def all_tech_tokens(taxonomy: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for category, items in taxonomy["tech"].items():
        for item in items:
            out.append(f"{category}.{item}")
    return sorted(out)


def archetype_counts(batch: str, total: int) -> dict[str, int]:
    weights = {a.name: a.weights.get(batch, 0.0) for a in ARCHETYPES}
    nonzero = {k: v for k, v in weights.items() if v > 0}
    if not nonzero:
        raise ValueError(f"No archetypes configured for batch '{batch}'")
    s = sum(nonzero.values())
    if abs(s - 1.0) > 1e-6:
        raise ValueError(f"Archetype weights for batch '{batch}' sum to {s}, expected 1.0")
    raw = {k: v * total for k, v in nonzero.items()}
    counts = {k: int(v) for k, v in raw.items()}
    diff = total - sum(counts.values())
    fracs = sorted(((k, raw[k] - counts[k]) for k in counts), key=lambda x: -x[1])
    for i in range(diff):
        counts[fracs[i % len(fracs)][0]] += 1
    return counts


def sample_tech(
    rng: random.Random,
    stage: StageSpec,
    all_tech: list[str],
) -> list[str]:
    k = rng.randint(stage.tech_min, min(stage.tech_max, len(stage.tech_pool)))
    picks: list[str] = []
    for _ in range(k):
        if rng.random() < TECH_NOISE_RATE:
            # Sample from the wider pool, excluding what we've already picked.
            candidates = [t for t in all_tech if t not in picks]
            picks.append(rng.choice(candidates))
        else:
            candidates = [t for t in stage.tech_pool if t not in picks]
            if not candidates:  # fallback if pool exhausted
                candidates = [t for t in all_tech if t not in picks]
            picks.append(rng.choice(candidates))
    return sorted(set(picks))


def sample_stage_roles(rng: random.Random, stage: StageSpec) -> list[dict[str, Any]]:
    primary_role = rng.choice(stage.primary_roles)
    years_primary = round(rng.uniform(stage.years_min, stage.years_max), 1)
    roles: list[dict[str, Any]] = [{"role": primary_role, "years": years_primary}]
    if stage.secondary_roles and rng.random() < SECONDARY_ROLE_RATE:
        secondary_role = rng.choice([r for r in stage.secondary_roles if r != primary_role])
        years_secondary = round(years_primary * rng.uniform(0.4, 0.8), 1)
        if years_secondary >= 0.5:
            roles.append({"role": secondary_role, "years": years_secondary})
    return roles


def sample_stage(
    rng: random.Random,
    stage: StageSpec,
    all_tech: list[str],
) -> dict[str, Any]:
    return {
        "roles": sample_stage_roles(rng, stage),
        "tech_stack": sample_tech(rng, stage, all_tech),
        "seniority": rng.choice(stage.seniority_pool),
    }


def sample_detour(
    rng: random.Random,
    own_archetype: ArchetypeSpec,
    all_tech: list[str],
    batch: str,
) -> dict[str, Any]:
    """A short cross-archetype side step — picks a role from a different archetype.

    Only considers archetypes that are themselves present in this batch, so
    that e.g. initial-batch detours never leak `genai_engineer` (which is
    reserved for the drift batch and the demo's before/after story).
    """
    other = [
        a for a in ARCHETYPES
        if a.name != own_archetype.name
        and not a.is_jobhopper
        and a.stages
        and a.weights.get(batch, 0.0) > 0
    ]
    if not other:
        return None  # type: ignore
    target = rng.choice(other)
    stage = rng.choice(target.stages)
    primary_role = rng.choice(stage.primary_roles)
    years = round(rng.uniform(0.5, 1.5), 1)
    tech = sample_tech(rng, stage, all_tech)
    return {
        "roles": [{"role": primary_role, "years": years}],
        "tech_stack": tech[:2],  # keep detour light
        "seniority": rng.choice(["junior", "mid"]),
    }


def generate_jobhopper(rng: random.Random, taxonomy: dict[str, Any], all_tech: list[str]) -> list[dict[str, Any]]:
    """Jobhopper: 3-5 short stints. Biased toward related-domain transitions, not pure random.

    genai_engineer is intentionally excluded from the role pool — the drift
    demo depends on that token only appearing once the drift batch is loaded.
    """
    domain_groups = [
        ["backend", "sre", "platform"],
        ["frontend", "fullstack", "mobile"],
        ["data_engineer", "ml_engineer"],
        ["security", "platform"],
    ]
    excluded_jobhopper_roles = {"em", "pm", "genai_engineer"}
    all_roles = [r for r in taxonomy["roles"] if r not in excluded_jobhopper_roles]

    n_steps = rng.randint(3, 5)
    last_role: str | None = None
    out: list[dict[str, Any]] = []
    for _ in range(n_steps):
        if last_role and rng.random() < 0.75:
            # Pick from a group that contains last_role
            related = [r for grp in domain_groups if last_role in grp for r in grp if r != last_role]
            role = rng.choice(related) if related else rng.choice(all_roles)
        else:
            role = rng.choice(all_roles)
        last_role = role
        years = round(rng.uniform(0.5, 1.8), 1)
        tech_k = rng.randint(2, 4)
        tech_stack = sorted(rng.sample(all_tech, tech_k))
        seniority = rng.choice(["junior", "mid", "senior"])
        out.append({
            "roles": [{"role": role, "years": years}],
            "tech_stack": tech_stack,
            "seniority": seniority,
        })
    return out


def generate_archetype_trajectory(
    rng: random.Random,
    arch: ArchetypeSpec,
    all_tech: list[str],
    batch: str,
) -> list[dict[str, Any]]:
    if arch.is_jobhopper:
        traj = generate_jobhopper(rng, load_taxonomy(), all_tech)
    else:
        traj: list[dict[str, Any]] = []
        for stage in arch.stages:
            if stage.optional and rng.random() < 0.4:
                continue
            traj.append(sample_stage(rng, stage, all_tech))

    # Optionally insert a cross-archetype detour somewhere mid-career
    if not arch.is_jobhopper and len(traj) >= 2 and rng.random() < DETOUR_RATE:
        detour = sample_detour(rng, arch, all_tech, batch)
        if detour is not None:
            insertion = rng.randint(1, len(traj) - 1)
            traj.insert(insertion, detour)

    return traj


def validate_archetypes_against_taxonomy(taxonomy: dict[str, Any]) -> None:
    valid_roles = set(taxonomy["roles"])
    valid_seniority = set(taxonomy["seniority"])
    valid_tech = set(all_tech_tokens(taxonomy))
    for arch in ARCHETYPES:
        if arch.is_jobhopper:
            continue
        for i, stage in enumerate(arch.stages):
            for r in stage.primary_roles + stage.secondary_roles:
                if r not in valid_roles:
                    raise ValueError(f"{arch.name} stage {i}: unknown role '{r}'")
            for s in stage.seniority_pool:
                if s not in valid_seniority:
                    raise ValueError(f"{arch.name} stage {i}: unknown seniority '{s}'")
            for t in stage.tech_pool:
                if t not in valid_tech:
                    raise ValueError(f"{arch.name} stage {i}: unknown tech '{t}'")


def generate_batch(batch: str) -> list[dict[str, Any]]:
    if batch not in BATCH_SPECS:
        raise ValueError(f"Unknown batch '{batch}'. Available: {list(BATCH_SPECS)}")
    spec = BATCH_SPECS[batch]
    taxonomy = load_taxonomy()
    validate_archetypes_against_taxonomy(taxonomy)

    counts = archetype_counts(batch, spec["size"])
    rng = random.Random(spec["seed"])
    arch_by_name = {a.name: a for a in ARCHETYPES}
    all_tech = all_tech_tokens(taxonomy)

    rows: list[dict[str, Any]] = []
    emp_seq = spec["id_offset"]
    for arch_name, count in counts.items():
        arch = arch_by_name[arch_name]
        for _ in range(count):
            emp_seq += 1
            employee_id = f"E{emp_seq:05d}"
            traj = generate_archetype_trajectory(rng, arch, all_tech, batch)
            for step_idx, step in enumerate(traj):
                rows.append({
                    "employee_id": employee_id,
                    "step": step_idx,
                    "roles": step["roles"],
                    "tech_stack": step["tech_stack"],
                    "seniority": step["seniority"],
                    "archetype": arch_name,
                    "batch_id": batch,
                })
    return rows


def write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def summarize(rows: list[dict[str, Any]]) -> str:
    from collections import Counter

    employees: set[str] = set()
    arch_per_emp: dict[str, str] = {}
    multi_role_steps = 0
    for r in rows:
        employees.add(r["employee_id"])
        arch_per_emp[r["employee_id"]] = r["archetype"]
        if len(r["roles"]) > 1:
            multi_role_steps += 1
    arch_counts = Counter(arch_per_emp.values())
    lines = [
        f"  total rows  : {len(rows)}",
        f"  employees   : {len(employees)}",
        f"  multi-role  : {multi_role_steps} steps ({multi_role_steps / max(1, len(rows)) * 100:.1f}%)",
        "  by archetype:",
    ]
    for k, v in sorted(arch_counts.items(), key=lambda x: -x[1]):
        lines.append(f"    {k:24s} {v}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch", required=True, choices=list(BATCH_SPECS))
    ap.add_argument("--output", type=Path, default=None)
    args = ap.parse_args()

    rows = generate_batch(args.batch)
    output = args.output or (OUTPUT_DIR / f"{args.batch}.jsonl")
    write_jsonl(rows, output)
    print(f"Wrote {output}")
    print(summarize(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
