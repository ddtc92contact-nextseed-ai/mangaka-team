"""Agents du pipeline : rôles déclarés dans `presets/agents/*.yaml`, réglables depuis l'écran « L'équipe ».

Le pipeline reste du Python simple (pas de framework d'agents, cf. docs/SPEC.md) : un agent n'est
qu'un nom, un rôle et la liste de ses réglages, chacun pointant vers le preset qui livre sa valeur.
Voir `profiles.py` (résolution série > profil global > presets, versions) et `trials.py` (« Essayer »).
"""

from .profiles import (
    AgentService,
    Knowledge,
    ProfileInvalid,
    ResolvedSetting,
    SettingError,
)

__all__ = ["AgentService", "Knowledge", "ProfileInvalid", "ResolvedSetting", "SettingError"]
