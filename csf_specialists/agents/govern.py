"""
Govern function specialist. Thin config wrapper around SpecialistAgent — all
behavior lives in the base class. Configuration is data-driven (rubric + examples
YAML), so this file has essentially no logic.
"""
from __future__ import annotations

from csf_specialists.agent_base import SpecialistAgent

# Module-level singleton: constructed at import time so rubric/example YAML load
# errors surface immediately rather than on first use.
govern_agent: SpecialistAgent = SpecialistAgent(function="govern")
