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
- adapte les noms de fichiers de modèles dans `presets/workflows/qwen-image-base.json` à ceux
  présents dans `ComfyUI/models/`.

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
| `MANGAKA_DATA_DIR` | `./data` | Dossier de la base et des images |
| `MAX_UPLOAD_MB` | `20` | Taille max d'une image de référence |

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

Les erreurs de validation renvoient une 422 lisible :
`{"detail": "Données invalides", "errors": [{"field": "title", "message": "ne doit pas être vide"}]}`.
