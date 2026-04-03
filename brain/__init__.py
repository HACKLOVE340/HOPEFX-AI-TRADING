# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
brain/ — centralized intelligence hub.

Primary entry point:
    from brain.hopefx_brain import HOPEFXBrain, get_brain

Nuclear event response:
    from brain.nuclear_supervisor import NuclearHopeFXSupervisor, get_nuclear_supervisor

Legacy components:
    brain.brain            — original HOPEFXBrain (kept for backward compat)
    brain.cognitive_engine — CognitiveEngine (analytical building blocks)
    brain.llm_agent        — LLMAgent (GPT-4 strategy generation)
"""

from brain.hopefx_brain import BrainDecision, HOPEFXBrain, Regime, get_brain
from brain.nuclear_supervisor import NuclearHopeFXSupervisor, get_nuclear_supervisor

__all__ = [
    "BrainDecision",
    "HOPEFXBrain",
    "NuclearHopeFXSupervisor",
    "Regime",
    "get_brain",
    "get_nuclear_supervisor",
]
