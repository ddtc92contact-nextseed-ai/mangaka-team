# mangaka-team

Studio **local** de planches manga/BD assisté par IA : scénario → découpage → génération case
par case via ComfyUI → contrôle qualité → lettrage vectoriel → planche finale.

Tout tourne sur l'ASUS GX10 (ARM64, Ubuntu). Rien n'est déployé. La spécification complète est
dans [`docs/SPEC.md`](docs/SPEC.md).

## Structure

| Dossier | Contenu |
| --- | --- |
| `web/` | Interface Next.js (App Router, TypeScript, Tailwind), en français |
| `engine/` | Moteur Python 3.12 + FastAPI : store SQLite, fournisseurs (LLM, vision, ComfyUI), API REST |
| `presets/` | Formats de page, workflows ComfyUI, paramètres des fournisseurs — voir [`presets/README.md`](presets/README.md) |
| `data/` | Base SQLite et images (créé au premier lancement, **jamais commité**) |
| `scripts/` | Scripts npm : installation du moteur, lancement conjoint web + moteur ; lanceur en un clic (`launch.sh`, `stop.sh`, `install-desktop.sh`) |
| `assets/icon/` | Icône de l'application (SVG + PNG 256/512) |
| `docs/` | Spécification |

## Installation sur le GX10

Prérequis : Node.js ≥ 20.9 et Python ≥ 3.12 avec `venv` (`sudo apt install python3.12-venv`).

```bash
git clone git@github.com:ddtc92contact-nextseed-ai/mangaka-team.git
cd mangaka-team
npm install          # dépendances web + crée engine/.venv et installe le moteur
npm run dev          # UI sur http://localhost:3000, moteur sur 127.0.0.1:8765
```

Sans fichier `.env`, **tout tourne en mode mock** : LLM, vision et ComfyUI sont simulés, aucun
appel réseau, aucun GPU. Le tableau de bord l'indique (« ComfyUI (mock) »).

Si le moteur s'arrête, l'interface reste en ligne et affiche « Moteur hors ligne » ; elle se
reconnecte toute seule quand il revient.

### Passer en mode réel

```bash
cp .env.example .env
```

Puis dans `.env` :

- `LLM_PROVIDER=deepseek` et `DEEPSEEK_API_KEY=sk-…` (la clé ne quitte jamais le moteur ; elle
  n'est ni dans le dépôt ni dans le bundle web) ;
- `COMFYUI_PROVIDER=http` et `COMFYUI_URL=http://127.0.0.1:8188` (ComfyUI lancé à part) ;
- adapte les noms de fichiers de modèles dans `presets/workflows/qwen-image-base.json` **et**
  `presets/workflows/qwen-image-edit-ref.json` à ceux présents dans `ComfyUI/models/` — le plus
  sûr est de ré-exporter ces workflows depuis ComfyUI (« Save (API Format) ») et d'ajuster leur
  mapping, voir [`presets/README.md`](presets/README.md#ré-exporter-un-workflow-depuis-comfyui) ;
- place les LoRA (style de la série, identité des personnages) dans `ComfyUI/models/loras/` et
  saisis leurs noms de fichiers exacts dans la série / les fiches personnages.

Au premier essai, lance une seule case (« Générer » dans l'atelier, ou
`POST /panels/{id}/generate`) : si ComfyUI refuse le workflow (modèle ou nœud absent), le job
passe en échec avec le détail par nœud (ex. « nœud 1 (UNETLoader) : Value not in list : unet_name… »).
ComfyUI éteint → « ComfyUI hors ligne (127.0.0.1:8188) » immédiatement, jamais de job bloqué
« en cours ». La progression arrive par le websocket de ComfyUI (`/ws`), avec repli sur un
sondage de `/history`.

### Lancer en un clic

Une icône « Mangaka Team » sur le bureau démarre tout ce qui manque — Ollama, ComfyUI, puis le
moteur et l'interface (`npm run dev`) — et ouvre l'atelier dans le navigateur.

Installation (une fois) :

```bash
cp launcher.env.example launcher.env   # facultatif : chemins, ports, services à démarrer
scripts/install-desktop.sh             # menu des applications + ~/Bureau
```

L'icône est copiée dans `~/.local/share/applications/` et dans le dossier du bureau
(`xdg-user-dir DESKTOP`, `~/Bureau` en français), exécutable et marquée de confiance : GNOME la
lance sans avertissement. Relancer le script met l'icône à jour sans doublon ;
`scripts/install-desktop.sh --uninstall` retire les deux copies. Si le dépôt change de place,
relance l'installation (le chemin est absolu).

Ce que fait l'icône (`scripts/launch.sh`, utilisable aussi dans un terminal) :

- chaque service est d'abord **sondé** — Ollama sur `$OLLAMA_URL/api/version`, ComfyUI sur
  `$COMFYUI_URL/system_stats`, l'application sur `http://127.0.0.1:$PORT/` — et n'est démarré
  que s'il ne répond pas. Un Ollama géré par systemd ou un ComfyUI lancé à la main est
  simplement réutilisé ; le lanceur n'appelle jamais `sudo` ni `systemctl` ;
- Ollama : `ollama serve` ; ComfyUI : `$COMFYUI_PYTHON main.py --listen 127.0.0.1 --port 8188`
  depuis `$COMFYUI_DIR` ; application : `npm run dev` à la racine du dépôt ;
- une notification suit la progression ; dès que l'interface répond, elle s'ouvre (`xdg-open`) ;
- si le port de l'interface est pris par **un autre programme**, le lanceur le dit et s'arrête ;
- en cas d'échec (délai dépassé, processus mort au démarrage, ComfyUI introuvable…), une
  notification nomme le service et son journal. Deux clics rapides ne lancent rien en double.

Configuration : `launcher.env` (gitignoré, modèle `launcher.env.example`), sinon `.env`, sinon
les valeurs par défaut : `COMFYUI_DIR=$HOME/ComfyUI`, `COMFYUI_PYTHON=$HOME/comfyui-env/bin/python`,
`COMFYUI_URL`, `OLLAMA_URL=http://127.0.0.1:11434`, `PORT=3000`, `START_OLLAMA` / `START_COMFYUI`
(`true`/`false`), délais d'attente `*_TIMEOUT`. Une variable d'environnement prime sur les fichiers.

Journaux : `~/.local/state/mangaka-team/logs/` — `launcher.log` (le lanceur lui-même),
`ollama.log`, `comfyui.log`, `app.log`. Les PID des services démarrés par le lanceur sont dans
`~/.local/state/mangaka-team/pids/`.

Arrêter : clic droit sur l'icône → « Arrêter », ou `scripts/stop.sh`. Seul ce que le lanceur a
démarré est arrêté (PID enregistrés, vérifiés contre leur date de démarrage) : un Ollama ou un
ComfyUI qui tournait déjà avant n'est jamais touché.

### Contrôle qualité réel (étape 4)

Le QC tourne en mock sans rien installer. Pour les vraies couches sur la GX10 :

```bash
# 1. Détecteurs visages / mains / texte + cohérence des personnages (deepghs, CPU, ARM64 OK)
engine/.venv/bin/pip install -e "engine[qc]"
#    Les modèles ONNX sont téléchargés depuis Hugging Face au premier contrôle, puis mis en cache
#    (~/.cache/huggingface).

# 2. Vision « la case colle-t-elle à sa description ? » (Ollama local)
ollama pull qwen3-vl:4b
```

Puis dans `.env` : `QC_DETECTORS_PROVIDER=dghs`, `QC_IDENTITY_PROVIDER=dghs`,
`VISION_PROVIDER=ollama` (URL et modèle dans `presets/providers.yaml`, `keep_alive: 0` : le modèle
est déchargé aussitôt pour rendre la mémoire à ComfyUI). Sans l'extra `qc`, le moteur démarre quand
même : l'atelier affiche « détecteurs non installés » et le QC continue avec les couches restantes.
Seuils, poids et règles : [`presets/qc.yaml`](presets/README.md#contrôle-qualité-qcyaml).

Redémarre `npm run dev`. Le tableau de bord affiche l'état de chaque fournisseur ; une
configuration incomplète (ex. clé absente) y apparaît en rouge sans empêcher le moteur de démarrer.

### Variables utiles

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `PORT` | `3000` | Port de l'interface web |
| `ENGINE_PORT` | `8765` | Port du moteur (joint par l'UI via le proxy `/api/engine`) |
| `LLM_PROVIDER` | `mock` | `deepseek` ou `mock` (`ollama`, `claude` : prévus) |
| `VISION_PROVIDER` | `mock` | Couche vision du QC : `ollama` (Qwen3-VL 4B) ou `mock` (DeepSeek n'accepte pas d'images) |
| `QC_DETECTORS_PROVIDER` | `mock` | Couche détecteurs du QC : `dghs` (extra `engine[qc]`) ou `mock` |
| `QC_IDENTITY_PROVIDER` | `mock` | Couche cohérence des personnages (CCIP) : `dghs` (extra `engine[qc]`) ou `mock` |
| `MOCK_VISION_SCORE` / `MOCK_VISION_INVALID_ATTEMPTS` | `80` / `0` | Mode mock : score de la vision factice, nombre de réponses invalides avant une valide (test des relances) |
| `COMFYUI_PROVIDER` | `mock` | `http` ou `mock` |
| `COMFYUI_URL` | `http://127.0.0.1:8188` | Adresse de ComfyUI |
| `COMFYUI_TIMEOUT_S` | `5` | Délai d'une requête HTTP vers ComfyUI (la durée max d'une génération est `timeout_s` du preset de workflow) |
| `COMFYUI_POLL_S` | `1` | Intervalle de sondage de `/history` pendant une génération |
| `MOCK_COMFYUI_SECONDS` | `4` | Mode mock : durée simulée d'une génération (progression factice) |
| `MANGAKA_DATA_DIR` | `./data` | Dossier de la base et des images |
| `MAX_UPLOAD_MB` | `20` | Taille max d'une image de référence |
| `MOCK_LLM_INVALID_ATTEMPTS` | `0` | Mode mock : nombre de réponses invalides du LLM factice avant une valide (test des relances ; `[mock:invalide:N]` dans un synopsis fait de même pour un chapitre) |

## Commandes

| Commande | Effet |
| --- | --- |
| `npm run dev` | Lance le moteur (rechargement auto) et l'interface |
| `npm run lint` / `npm run typecheck` / `npm run build` | Contrôles de l'interface web |
| `npm run test:engine` | Tests du moteur (pytest, tout simulé) |
| `npm run lint:engine` | Ruff sur le moteur |
| `npm run test:launcher` | Tests du lanceur en un clic (faux serveurs HTTP, aucun service réel) ; `shellcheck -x scripts/*.sh` pour le lint |
| `npm run setup:engine` | (Ré)installe le venv du moteur |

## API du moteur

Documentation interactive : `http://127.0.0.1:8765/docs` quand le moteur tourne.

- `GET /health` — état du moteur, de ComfyUI et des fournisseurs
- `GET /presets` — formats de page, workflows, erreurs de presets
- `GET|POST /projects`, `GET|PATCH|DELETE /projects/{id}`
- `GET|POST /projects/{id}/characters`, `GET|PATCH|DELETE /characters/{id}`
- `POST /characters/{id}/images` (multipart, champ `files`), `GET /characters/{id}/images/{image_id}/file`,
  `DELETE /characters/{id}/images/{image_id}`
- `GET /jobs/{id}`, `GET /jobs/{id}/events` (SSE : un événement `job` à chaque changement de
  progression), `POST /jobs/{id}/cancel`

### Génération (étape 3)

Une seule génération ComfyUI à la fois : chaque demande crée des jobs `generation` placés dans une
file FIFO dédiée (séparée des étapes LLM, qui restent parallèles). Chaque résultat est une nouvelle
version de la case ; régénérer une case ne touche jamais aux autres.

| Route | Rôle |
| --- | --- |
| `POST /panels/{id}/generate` | Corps optionnel `{count?: 1–4, seed?, preset?, prompt_override?}` → `202` + liste de jobs (un par variante). `seed` absente = tirée au hasard ; avec `count > 1`, les variantes prennent `seed`, `seed+1`… `prompt_override` remplace le prompt final et le garde comme édition manuelle. |
| `POST /pages/{id}/generate` | `{force?: false, count?, preset?}` → `{jobs, panel_ids, skipped}`. Seulement les cases **sans version choisie** (toutes avec `force`) ; une case déjà en file est toujours ignorée. |
| `POST /chapters/{id}/generate` | Idem pour tout le chapitre, page par page. |
| `GET /panels/{id}` | Détail de la case pour l'atelier : prompt final (+ `final_prompt_manual`), workflow imposé et workflow résolu, taille cible, versions, jobs actifs. |
| `PATCH /panels/{id}` | `{final_prompt?, generation_preset?}` : un prompt édité à la main est conservé (`""`/`null` = revenir au prompt automatique) ; `generation_preset` impose un workflow (`null` = automatique). |
| `POST /panels/{id}/prompt/rebuild` | Abandonne l'édition manuelle et reconstruit le prompt final. |
| `GET /panels/{id}/images` | Versions de la case (`version`, `seed`, `selected`, `url`, `params` complets : preset, prompt, négatif, taille, LoRA, références, durée…). |
| `GET /panel-images/{id}/file` | Fichier image (bon `Content-Type`). |
| `POST /panel-images/{id}/select` | Choisit cette version (une seule par case) → liste des versions. |
| `DELETE /panel-images/{id}` | Supprime la version et son fichier (`204`). Si c'était la version choisie, aucune ne l'est plus. |
| `GET /queue` | `{running, pending[], total_eta_s, comfyui}` : chaque élément porte le job (progression), sa position, un libellé « Série · ch. 3 · p. 2 · case 4 », les ids page/chapitre/série, le preset et `eta_s` (temps restant estimé d'après la médiane des 20 dernières générations réussies du même preset ; `null` tant qu'aucune n'est connue). |
| `POST /jobs/{id}/cancel` | Job en attente → `cancelled` tout de suite ; génération en cours → interrompue via `/interrupt` de ComfyUI, le job passe à `cancelled` dès que ComfyUI rend la main. `409` si le job est terminé (ou si c'est un découpage LLM déjà lancé). |
| `GET /presets/workflows` | Workflows disponibles : nombre d'emplacements de référence, LoRA possibles, délai max, workflow par défaut / « avec références ». |

**Choix du workflow** : `preset` de la demande > `generation_preset` de la case > workflow « avec
références » (`defaults.yaml` → `workflow_with_references`, `qwen-image-edit-ref`) si un personnage
de la case a une planche de référence > workflow de la série (`qwen-image-base` par défaut).

**Prompt final** (`presets/image_prompt.yaml`) : type de plan + description de la case (répliques
entre guillemets retirées) + personnages (description visuelle + mots-clés) + style de la série. Le
prompt négatif contient toujours « texte, lettres, bulles… » : le modèle ne dessine jamais de texte.

**Références et LoRA** : les images de référence des personnages (1re image de chacun, puis 2e…)
sont envoyées à ComfyUI (`/upload/image`) et remplissent les emplacements du workflow ; les
emplacements vides sont retirés. LoRA = LoRA de style de la série puis LoRA d'identité de chaque
personnage, chaînés dans cet ordre avec leurs poids. Taille : celle calculée par la mise en page
(même ratio que la case, ≈ 1 Mpx, multiples de 16).

**États** : case `queued` → `generating` → `review` (première version choisie d'office) ; page
`generating` puis `review` quand toutes ses cases ont une version ; le chapitre passe en
« génération ». Au redémarrage du moteur, les générations en cours ou en attente sont marquées
en échec (« Interrompu par un redémarrage du moteur ») et les états recalculés.

### Contrôle qualité (étape 4)

Objectif : produire beaucoup de cases et **ne relire que les douteuses**. Trois couches, réglées
uniquement dans `presets/qc.yaml` (validé au chargement, aucun seuil dans le code) :

1. **détecteurs** (rapide, CPU) : visages, mains, texte parasite (détecteurs anime ONNX deepghs).
   Règles : moins de visages que de personnages → à revoir ; texte détecté → rejet ; main détectée
   à faible confiance → pénalité… Les boîtes sont gardées par version (`detections`, en px de
   l'image) pour que le lettrage évite les visages ;
2. **cohérence des personnages** : similarité CCIP entre la case et les images de référence de
   chaque fiche, seuil dans le preset ;
3. **vision** (lente) : Qwen3-VL 4B via Ollama, réponse JSON validée (score 0–100 + raisons ;
   invalide → 1 nouvel essai → erreur lisible). Ne tourne que si les couches 1-2 hésitent (zone de
   doute du preset) ou à la demande. Les jobs `qc` passent **par la file de la génération** : la
   vision ne tourne jamais pendant une génération ComfyUI (et attend si ComfyUI a une file non vide).

Score combiné = moyenne pondérée des couches qui ont tourné → `ok` / `review` (à revoir) / `reject`
(rejet), durci par les règles. Après chaque génération (`auto_after_generation`), un QC automatique
est mis en file ; un rejet relance une génération avec une nouvelle seed (`max_auto_retries`), puis
la case est signalée « à revoir » (la meilleure version est choisie). Rien n'est supprimé.

| Route | Rôle |
| --- | --- |
| `POST /panels/{id}/qc` | `{image_id?, vision?: "auto"\|"force"\|"skip"}` → `202` + job `qc` (version choisie par défaut). |
| `POST /chapters/{id}/qc` | `{force?: false, vision?}` → `{job, panel_ids, skipped, summary}` : un job pour toutes les cases non contrôlées (toutes avec `force`), progression SSE. |
| `GET /chapters/{id}/qc` | Compteurs `{ok, review, reject, unchecked, no_image, total}` (version choisie de chaque case). |
| `POST /panel-images/{id}/qc/override` | « Valider quand même » : verdict forcé à `ok`, décision humaine tracée (`qc.override`, historique). |
| `GET /qc/status` | Preset et fournisseur de chaque couche (« détecteurs non installés »…). |

Chaque version porte `qc_verdict`, `qc_score`, `qc_reasons` (en français), `qc` (détail par couche :
statut, score, durée en ms, raisons ; source auto / manuelle / humaine ; historique) et `detections`.
États de case : `qc` pendant un contrôle, puis `approved` (QC ok) ou `flagged` (à revoir / rejet)
d'après la version choisie.

### Banc d'essai du QC

Avant tout fine-tuning d'un modèle de vision, on **mesure** le QC sur ses propres cases annotées
(50 à 100, objectif dans `qc.yaml` → `bench`). Dans l'atelier, chaque version s'annote « bonne » /
« mauvaise » (+ défauts : visage raté, mains, perso pas reconnaissable, ne colle pas à la
description, texte parasite, autre ; + note) — au clavier : **B** / **M**, **← / →** case
précédente / suivante (dans la fenêtre d'une version : version précédente / suivante). L'annotation
est indépendante du verdict QC.

L'écran **Banc d'essai QC** (barre latérale) lance un job `qc_bench` (file de la génération : la
vision ne tourne jamais pendant ComfyUI) qui fait tourner chaque couche seule (vision forcée), puis
rejoue le verdict combiné comme le QC réel. Classe positive = **mauvaise case** : précision, rappel,
faux positifs / négatifs, matrice de confusion, balayage de seuil 0–100 et seuil suggéré (rappel ≥
`bench.target_recall` avec la meilleure précision ; à égalité, le plus proche du seuil actuel), temps
moyen par case et par couche. Chaque run garde la version (empreinte) du preset utilisé.

| Route | Rôle |
| --- | --- |
| `PUT /panel-images/{id}/annotation` | `{label: "good"\|"bad", defects?: [...], note?}` ; `DELETE` pour effacer. Aussi exposée dans chaque version (`annotation`). |
| `GET /qc/bench/dataset` | `?project_id=&chapter_id=` → bonnes / mauvaises / par défaut + objectif. |
| `POST /qc/bench/runs` | `{project_id?, chapter_id?, vision?: true}` → `202` + run (job SSE). `422` sans case annotée, `409` si un banc tourne déjà. |
| `GET /qc/bench/runs`, `GET /qc/bench/runs/{id}` | Historique ; détail (métriques par couche, balayage, cases, run précédent). |
| `GET /qc/bench/runs/{id}/export?format=json\|csv` | Export du run (CSV séparé par « ; », UTF-8 avec BOM). |
| `POST /qc/bench/runs/{id}/apply` | `{confirm: false}` = aperçu ; `{confirm: true}` écrit `presets/qc.yaml` (`verdict.ok_min`, `identity.min_similarity`), revalidé puis rechargé. |

En mode mock, ComfyUI factice renvoie une image de la taille demandée avec « CASE n », la seed et
la taille dessinées dessus, après une progression factice (`MOCK_COMFYUI_SECONDS`).

Les erreurs de validation renvoient une 422 lisible :
`{"detail": "Données invalides", "errors": [{"field": "title", "message": "ne doit pas être vide"}]}`.
