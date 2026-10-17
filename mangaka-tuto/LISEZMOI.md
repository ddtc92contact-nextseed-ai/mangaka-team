# Mangaka Team — tutoriel visuel du pipeline

Un petit site statique qui montre qui fait quoi dans Mangaka Team, avec quel outil et dans quel ordre, de la
création d'une série jusqu'à la planche exportée et à la couverture du tome.

## L'ouvrir

Double-clique sur `index.html` : la page s'ouvre dans le navigateur, directement depuis le disque (`file://`).
Pas de serveur, pas de npm, pas de réseau : polices système, aucune ressource externe.

En ligne de commande :

```bash
xdg-open mangaka-tuto/index.html
```

## Le copier sur le bureau

Depuis la racine du dépôt :

```bash
cp -r mangaka-tuto ~/Desktop/
```

(Sur un Ubuntu en français, le bureau peut s'appeler `~/Bureau/`.) Le dossier est autonome : il marche une fois
copié n'importe où. Seul `verifier.py` a besoin du dépôt à côté de lui.

## Ce qu'il contient

| Page | Contenu |
|---|---|
| `index.html` | Sommaire et glossaire |
| `pipeline.html` | Carte interactive des 21 étapes ; clic sur une étape = ce qu'elle fait, qui la fait, entrées et sorties, portes, fichiers source. Tableau de la garde d'étapes. |
| `voies.html` | Animation du pool LLM parallèle (4 workers) face à la file ComfyUI sérielle, et la liste de tout ce qui partage cette file |
| `equipe.html` | Une fiche par agent de `presets/agents/` : rôle, modèle, variables de prompt, étapes |
| `case.html` | La vie d'une case pas à pas, de la ligne de scénario à la planche exportée |

Navigation au clavier partout (Tab, Entrée, flèches). Les animations s'arrêtent si le système demande moins de
mouvement (`prefers-reduced-motion`).

## Tenir le tutoriel à jour

Toutes les données sont dans `assets/data.js`, relevées dans `engine/mangaka_engine`, `presets/` et `web/src`.
Après un changement de modèle, de flux, d'agent ou de garde d'étapes, lance depuis la racine du dépôt :

```bash
python3 mangaka-tuto/verifier.py
```

Il compare `data.js` aux presets et au code (modèle par défaut et modèle de vision de `providers.yaml`, flux et
leur nom, défauts de `defaults.yaml`, agents et variables de prompt, étapes de la file ComfyUI, garde d'étapes),
vérifie que chaque fichier source cité existe, et liste les écarts. Il demande PyYAML et Node.
