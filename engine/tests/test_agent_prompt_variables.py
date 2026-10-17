"""Garde-fou : chaque prompt livré d'un agent passe `check_template` avec ses `variables` déclarées.

Sans cela, une variable ajoutée au prompt mais oubliée dans `presets/agents/*.yaml` bloque
l'enregistrement de tous les réglages de l'agent dans « L'équipe » (cf. #213).
"""

from __future__ import annotations

import pytest

from mangaka_engine.agents.profiles import _MISSING, _get, check_template, file_data
from mangaka_engine.presets import PresetRegistry
from mangaka_engine.presets.schemas import AgentSetting
from tests.conftest import PRESETS_DIR

REG = PresetRegistry.load(PRESETS_DIR)
PROMPT_SETTINGS = [
    (agent.id, setting)
    for agent in sorted(REG.agents.values(), key=lambda a: a.id)
    for setting in agent.settings
    if setting.type in ("prompt", "prompt_list")
]


def test_every_agent_is_covered() -> None:
    assert len(REG.agents) == len(list((PRESETS_DIR / "agents").glob("*.yaml")))
    assert PROMPT_SETTINGS


@pytest.mark.parametrize(("agent_id", "setting"), PROMPT_SETTINGS, ids=[f"{a}:{s.key}" for a, s in PROMPT_SETTINGS])
def test_shipped_prompt_only_uses_declared_variables(agent_id: str, setting: AgentSetting) -> None:
    assert setting.file is not None, f"{agent_id}.{setting.key} : source sans fichier"
    data = file_data(REG, setting.file)
    assert data is not None, f"{agent_id}.{setting.key} : {setting.file} absent ou invalide"
    value = _get(data, setting.path)
    if value is _MISSING or value is None:
        value = setting.fallback
    parts = value if setting.type == "prompt_list" else [value]
    for part in parts or []:
        assert isinstance(part, str)
        assert check_template(part, setting.variables) is None, f"{agent_id}.{setting.key}"
