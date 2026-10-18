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
| `goulots.html` | Goulots et faiblesses : durées et attentes mesurées dans ta base, carte colorée par coût, constats tirés du code (fichier et ligne), faiblesses classées |
| `prompts.html` | La chaîne des prompts : graphe de qui écrit quoi à qui, une fiche par gabarit (texte réel, variables et leur provenance, contrat de sortie, effet en aval), traçage « d'où vient ce mot ? » du prompt d'une case, constats « leviers » classés par effet probable sur l'image |

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
vérifie que chaque fichier source cité existe, et liste les écarts. Il demande PyYAML, Node et, pour la chaîne des prompts, le venv du moteur (`engine/.venv`).

## Goulots et faiblesses : mesurer ta base

`goulots.html` lit ses chiffres dans `data/mesures.js`, écrit par `mesurer.py` à partir de la base SQLite du
moteur. Depuis la racine du dépôt :

```bash
python3 mangaka-tuto/mesurer.py data/mangaka.db
```

Sans chemin, le script prend la base du moteur : `MANGAKA_DATA_DIR` (environnement, puis `.env`), sinon `data/`,
fichier `mangaka.db`. Puis recharge `goulots.html`.

- **Lecture seule** : la base est ouverte en `file:…?mode=ro` avec `PRAGMA query_only`. Le script n'écrit que
  `mangaka-tuto/data/mesures.js` et ne touche ni à ComfyUI ni à `output/`. Bibliothèque standard seulement.
- **Ce qui est mesuré** : par étape de job, nombre, durée médiane, p90 et max, taux d'échec, erreurs les plus
  fréquentes regroupées ; attente en file (`started_at − created_at`) comparée à l'exécution ; par chapitre, temps
  machine par étape et temps humain présumé entre deux jobs ; régénérations par case ; rejets du QC par couche ;
  réparations ; signaux tirés des messages d'erreur du moteur (redémarrage, délai ComfyUI, vision sautée…).
- **Ce qui n'est pas mesurable** dans la base est marqué « à mesurer » sur la page, jamais estimé.
- **Base vide ou absente** : le fichier dit « pas encore de données » et la page explique quoi lancer. Tant que
  `data/mesures.js` n'a jamais été généré (clone neuf), le navigateur signale dans sa console que ce fichier manque :
  c'est attendu, la page affiche les mêmes explications.
- `data/mesures.js` vient de ta vraie base : il est ignoré par git (`mangaka-tuto/.gitignore`). Seul l'exemple
  factice `data/mesures.exemple.js` est commité (bouton « Voir l'exemple factice »). Pour le régénérer :

  ```bash
  python3 mangaka-tuto/tests/base_factice.py /tmp/factice.db
  python3 mangaka-tuto/mesurer.py /tmp/factice.db --exemple --sortie mangaka-tuto/data/mesures.exemple.js
  ```

La vue structurelle et le tableau des faiblesses vivent dans `assets/goulots-data.js`. Chaque citation y donne un
fichier, une ligne et un extrait ; `verifier.py` contrôle que l'extrait est toujours à cette ligne.

Tests (lecture seule vérifiée avant/après, médiane, p90, attente en file, base vide) :

```bash
engine/.venv/bin/python -m pytest mangaka-tuto/tests -q
```

## La chaîne des prompts (`prompts.html`)

Deux fichiers de données :

- `assets/prompts-gabarits.js` est **généré**, ne pas le modifier à la main. Il contient le texte réel des gabarits
  (`presets/prompts/`, morceaux d'`image_prompt.yaml`, consigne de vision de `qc.yaml`) avec leurs lignes, les
  variables déclarées par les agents, les modèles de `providers.yaml`, et le prompt de la case d'essai de l'appli
  (`engine/mangaka_engine/agents/trials.py`) construit par le vrai code du moteur (`build_prompt`,
  `frame_references`…), découpé morceau par morceau. Aucun appel LLM, aucune base. Après un
  changement de preset ou de code de prompt, depuis la racine du dépôt :

  ```bash
  engine/.venv/bin/python mangaka-tuto/extraire_prompts.py
  ```

- `assets/prompts-data.js` est écrit à la main : graphe, provenance des variables, effet de chaque champ en aval,
  constats. Chaque bloc cite `fichier:ligne`.

`verifier.py` contrôle aussi cette page : `prompts-gabarits.js` à jour, chaque agent de `presets/agents/` dans le
graphe ou parmi les agents sans prompt, une fiche par gabarit, une provenance pour chaque variable utilisée ou
déclarée (et aucune pour une variable disparue), chaque point du code qui assemble un prompt image cité par une
fiche, chaque fichier et chaque ligne cités existants. Il affiche aussi la liste des variables déclarées mais
absentes de leur gabarit. Lance-le avec le Python du moteur (`engine/.venv/bin/python mangaka-tuto/verifier.py`).

Les constats sont des **constats, pas des chantiers** : « à vérifier » marque ce que le code seul ne tranche pas
(il faut une mesure sur des images).
