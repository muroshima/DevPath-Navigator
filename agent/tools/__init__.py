"""Agent tools registry.

Each tool is a plain Python function with a type-hinted signature and a
docstring; ADK introspects these to build the FunctionDeclaration shown to
Gemini. Keep parameter names and docstrings stable — they are what the model
sees.
"""

from agent.tools.explain_cluster import explain_cluster
from agent.tools.find_similar_trajectories import find_similar_trajectories
from agent.tools.locate_user import locate_user
from agent.tools.nlq_over_corpus import nlq_over_corpus
from agent.tools.normalize_profile import normalize_profile
from agent.tools.recommend_next_steps import recommend_next_steps
from agent.tools.skill_gap_analysis import skill_gap_analysis

ALL_TOOLS = [
    normalize_profile,
    locate_user,
    find_similar_trajectories,
    explain_cluster,
    skill_gap_analysis,
    recommend_next_steps,
    nlq_over_corpus,
]

__all__ = [
    "ALL_TOOLS",
    "normalize_profile",
    "locate_user",
    "find_similar_trajectories",
    "explain_cluster",
    "skill_gap_analysis",
    "recommend_next_steps",
    "nlq_over_corpus",
]
