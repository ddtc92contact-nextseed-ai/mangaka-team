# mangaka-team — Spécification

> Spec validée par le manager. Document de référence pour tous les jalons.

**mangaka-team** est un outil **100 % local** (il tourne uniquement sur l'ASUS GX10 du manager —
ARM64, 128 Go de mémoire unifiée) qui automatise environ 90 % de la fabrication d'une planche
manga/BD :

**scénario → découpage en cases → génération d'images case par case via ComfyUI local →
contrôle qualité → lettrage vectoriel → planche finale.**

Rien n'est déployé nulle part. L'humain est scénariste, directeur artistique et valideur.
Langue de l'interface : **français**.

---

## 1. Contraintes non négociables

- **Images 100 % locales** : ComfyUI sur `http://127.0.0.1:8188` (API `/prompt`, `/history`,
  `/view`, websocket de progression). Pas de Docker requis, pas de VPS.
- **La mémoire GPU appartient à ComfyUI** (Qwen-Image 2.1 + encodeur Qwen3-VL 8B ≈ 30–50 Go).
  Aucun autre gros modèle ne reste chargé.
- **LLM texte = API DeepSeek** (`DEEPSEEK_API_KEY` dans `.env`, jamais dans le dépôt) derrière une
  couche de fournisseurs : `deepseek` (défaut en production) | `ollama` | `claude` | `mock`.
- **Contrôle qualité visuel** derrière la même couche : DeepSeek s'il accepte les images, sinon
  Qwen3-VL 4B local via Ollama, chargé à la demande avec `keep_alive: 0`, **jamais pendant une
  génération ComfyUI** | `mock`.
- **Tout ce qui évolue est un preset, pas du code** : modèles, LoRA, workflows ComfyUI (JSON API),
  formats de page, polices, seuils de QC.
- **Le texte n'est jamais dessiné par le modèle d'image** : bulles et textes sont vectoriels, avec de
  vraies polices (accents français).
- **Pas de framework d'agents** (ni LangGraph ni CrewAI) : pipeline explicite codé, état en base.
- **Une seule génération ComfyUI à la fois** ; les étapes LLM peuvent tourner en parallèle.
  **Chaque résultat est versionné.**

## 2. Architecture

```
┌──────────────────────────┐   REST + événements temps réel   ┌──────────────────────────────┐
│ Interface web            │ ───────────────────────────────▶ │ Moteur                       │
│ Next.js + TS + Tailwind  │ ◀─────── (SSE ou WebSocket) ──── │ Python 3.12 + FastAPI        │
└──────────────────────────┘                                  │                              │
                                                              │ pipeline/  étapes 1 → 5      │
                                                              │ providers/ llm, vision,      │
                                                              │            comfyui           │
                                                              │ store/     SQLite + data/    │
                                                              │ presets/   YAML / JSON       │
                                                              └──────────────┬───────────────┘
                                                                             │ HTTP + WS
                                                                     ┌───────▼───────┐
                                                                     │ ComfyUI local │
                                                                     └───────────────┘
```

- `pipeline/` : étapes 1 → 5, **idempotentes et rejouables case par case**.
- `providers/` : `llm`, `vision`, `comfyui` — chacun avec une implémentation réelle et un `mock`.
- `store/` : SQLite + fichiers dans `data/` (jamais commité).
- `presets/` : fichiers YAML/JSON validés au chargement.

## 3. Modèle de données

| Entité | Champs |
| --- | --- |
| **Projet / Série** | titre, style, sens de lecture (`ltr` / `rtl`), format de page, presets par défaut |
| **Personnage** | nom, description visuelle, images de la planche de référence, LoRA optionnel + poids, mots-clés de prompt |
| **Page** | numéro, gabarit de grille, état |
| **Case** (*panel*) | description, personnages, type de plan, dialogues, zone réservée aux bulles, prompt final, preset de génération, versions d'image, score QC, état |
| **Bulle** | locuteur, texte, type (`speech` parole / `thought` pensée / `shout` cri / `narration` récitatif / `off` hors-champ), position, queue |
| **Job** | étape, case, statut, durée, erreur |

## 4. Étapes du pipeline

1. **Scénario** — le LLM produit un JSON pages → cases validé par Pydantic. JSON invalide →
   nouvel essai (2 max) → erreur visible. Le résultat est éditable.
2. **Découpage** — déterministe : A4/B4 à 300 DPI, marges, gouttières, gabarit choisi selon le
   nombre et l'importance des cases, coordonnées de chaque case, zone réservée aux bulles par case.
3. **Génération** — ComfyUI, Qwen-Image 2.1 avec images de référence, LoRA d'identité, seed
   enregistrée, variantes.
4. **Contrôle qualité** — YOLO visages/mains + SAM → FaceDetailer (denoise 0,35–0,45) ; score
   visuel 0–100 + raisons ; nouvel essai automatique puis signalement.
5. **Lettrage / assemblage** — Pillow + Cairo/SVG ; bulles placées dans les zones réservées en
   évitant les visages ; export PNG 300 DPI + SVG.

## 5. Interface

- **Tableau de bord** : projets, statut et file d'attente ComfyUI.
- **Personnages**.
- **Scénario**.
- **Atelier de page** : clic sur une case → versions, QC, « régénérer cette case ».
- **Presets**.

Sombre, moderne, rapide.

## 6. Jalons

1. Fondation + étapes 1–2 + écrans Projet / Personnages / Scénario + aperçu du découpage.
2. Génération + file d'attente + atelier de page.
3. Contrôle qualité + lettrage + export.
4. ControlNet, upscaler, PSD, export vers nextseed-manga.

## 7. Tests

- ComfyUI, LLM et vision **toujours simulés** (le ComfyUI factice renvoie des images de la taille
  demandée).
- Tests unitaires : schéma du scénario, géométrie du découpage, placement des bulles,
  construction des workflows.
- Tests *golden image* pour l'assemblage.
