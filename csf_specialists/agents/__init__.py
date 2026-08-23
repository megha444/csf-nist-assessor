"""
Registry of live specialist agents — the source of truth for "which Functions
actually have an agent built yet." csf_coordinator.coordinator and
csf_specialists.worker both key off this instead of hardcoding Function names,
so adding a new Function agent means adding one line here, not touching
coordinator/worker code.
"""
from __future__ import annotations

from csf_specialists.agent_base import SpecialistAgent
from csf_specialists.agents.detect import detect_agent
from csf_specialists.agents.govern import govern_agent
from csf_specialists.agents.identify import identify_agent
from csf_specialists.agents.protect import protect_agent
from csf_specialists.agents.recover import recover_agent
from csf_specialists.agents.respond import respond_agent

AGENTS: dict[str, SpecialistAgent] = {
    "govern": govern_agent,
    "identify": identify_agent,
    "protect": protect_agent,
    "detect": detect_agent,
    "respond": respond_agent,
    "recover": recover_agent,
}
