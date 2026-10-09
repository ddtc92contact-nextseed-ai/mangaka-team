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
| `scripts/` | Scripts npm : installation du moteur, lancement conjoint web + moteur |
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

Redémarre `npm run dev`. Le tableau de bord affiche l'état de chaque fournisseur ; une
configuration incomplète (ex. clé absente) y apparaît en rouge sans empêcher le moteur de démarrer.

### Variables utiles

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `PORT` | `3000` | Port de l'interface web |
| `ENGINE_PORT` | `8765` | Port du moteur (joint par l'UI via le proxy `/api/engine`) |
| `LLM_PROVIDER` | `mock` | `deepseek` ou `mock` (`ollama`, `claude` : prévus) |
| `VISION_PROVIDER` | `mock` | `mock` (`deepseek`, `ollama` : jalon 3) |
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

En mode mock, ComfyUI factice renvoie une image de la taille demandée avec « CASE n », la seed et
la taille dessinées dessus, après une progression factice (`MOCK_COMFYUI_SECONDS`).

Les erreurs de validation renvoient une 422 lisible :
`{"detail": "Données invalides", "errors": [{"field": "title", "message": "ne doit pas être vide"}]}`.
