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

Rythme visé : une dizaine de séries en parallèle, **un chapitre par semaine et par série**, publiés
chapitre par chapitre sur le site manga du manager. Le travail s'organise donc en
**Série → Chapitre → Page** (et non Projet → Page).

| Entité | Champs |
| --- | --- |
| **Série** (table historique `projects`, routes `/projects`) | titre, style, **statut**, sens de lecture (`ltr` / `rtl`), format de page, presets par défaut (workflow ComfyUI, **LoRA de style + poids**) |
| **Personnage** | série, nom, description visuelle, images de la planche de référence, LoRA optionnel + poids, mots-clés de prompt |
| **Chapitre** | série, numéro (unique dans la série), titre, synopsis ou script brut, nombre de pages visé (15 par défaut), **statut**, date de publication prévue, résumé (écrit par l'étape 1, relu par les chapitres suivants) |
| **Page** | chapitre, numéro, **type**, gabarit imposé (optionnel), mise en page (JSON de l'étape 2), état |
| **Case** (*panel*) | description, personnages (noms + fiches reliées), type de plan, importance 1–3, coordonnées, zone réservée aux bulles, prompt final, preset de génération, versions d'image, score QC, état |
| **Bulle** | locuteur (nom + fiche reliée), texte, type (`speech` parole / `thought` pensée / `shout` cri / `narration` récitatif / `off` hors-champ), position, queue |
| **Job** | étape, série, chapitre, case, statut, progression 0–100 + message, durée, erreur |
| **Collection de savoir-faire** | nom, description, globale ou rattachée à une série ; documents (titre, source md/txt/pdf/texte, étiquettes, texte) → passages (section, texte, jetons, vecteur + modèle, index FTS5) |
| **Bible de série** | une par série : univers, ton, règles, gags et motifs, notes par fiche personnage, résumés des chapitres validés (« Prêt » / « Publié ») |
| **Appel LLM** (`llm_runs`) | agent, job, chapitre, modèle, requête, passages reçus (sources, extraits, scores), bible reçue |

**Statuts d'une série** : `ongoing` en cours · `paused` en pause · `completed` terminée · `cancelled` arrêtée.

**Statuts d'un chapitre** : `draft` brouillon · `script` scénario · `layout` mise en page ·
`generation` génération · `lettering` lettrage · `ready` prêt · `published` publié. L'étape 1 fait
passer un brouillon en « scénario » ; les autres changements sont manuels pour l'instant.

**Types de page** : `story` page de l'histoire · `bonus` (croquis, notes de l'auteur…) ·
`chapter_cover` page de garde. Relancer le découpage ne remplace que les pages `story`.

**Migrations** : le schéma est versionné par `PRAGMA user_version` (`engine/mangaka_engine/store/migrations.py`).
Une base du jalon #1 est migrée au démarrage : les projets deviennent des séries sans chapitre
(d'éventuelles pages orphelines seraient regroupées dans un chapitre 1 « Pages importées »).

## 4. Étapes du pipeline

1. **Scénario** (par chapitre, `pipeline/script.py`) — entrée : synopsis ou script brut du
   chapitre + fiche de la série + personnages + **résumés des chapitres précédents** (continuité).
   Le LLM produit un JSON pages → cases (description, personnages, type de plan, dialogues,
   importance 1–3) + un résumé du chapitre, validé par Pydantic. JSON invalide → nouvel essai avec
   l'erreur renvoyée au LLM (2 max) → job en erreur avec un message lisible. Prompts dans
   `presets/prompts/`. Tourne comme un job (progression en direct par SSE). Le résultat
   (Pages + Cases + Bulles) est éditable à la main.
2. **Découpage** (`pipeline/layout.py`, déterministe) — A4 300 DPI par défaut (B4 disponible),
   marges (reliure alternée recto/verso selon le sens de lecture) et gouttières en mm ; gabarits
   « guillotine » de 1 à 9 cases (`presets/layouts/`, au-delà grille générée), choisis selon le
   nombre et l'importance des cases ; coordonnées (x1, y1, x2, y2) en px, taille cible de
   génération (même ratio, ≈ 1 Mpx, multiples de 16) et zone réservée aux bulles dimensionnée par
   la longueur des dialogues, placée côté début de lecture (ltr / rtl). JSON stocké par page,
   rejouable ; déplacer une gouttière recalcule ses deux voisines.
3. **Génération** — ComfyUI, Qwen-Image 2.1 avec images de référence, LoRA d'identité, seed
   enregistrée, variantes.
4. **Contrôle qualité** (`pipeline/qc.py`, seuils dans `presets/qc.yaml`) — en couches, pour ne
   relire que les cases douteuses : détecteurs anime ONNX deepghs (visages, mains, texte parasite ;
   boîtes gardées par version pour le lettrage), cohérence des personnages (CCIP vs images de
   référence), vision Qwen3-VL 4B via Ollama seulement en cas de doute ou à la demande, jamais
   pendant une génération ComfyUI (même file). Score 0–100 + raisons → ok / à revoir / rejet ;
   QC automatique après génération, rejet → nouvel essai (nouvelle seed) puis « à revoir » ;
   « valider quand même » tracé. Retouche FaceDetailer (YOLO + SAM) : jalon 4.
5. **Lettrage / assemblage** — Pillow + Cairo/SVG ; bulles placées dans les zones réservées en
   évitant les visages ; export PNG 300 DPI + SVG.

## 5. Interface

- **Tableau de bord** : séries, « chapitres de la semaine » (publication prévue dans les 7 jours),
  statut et file d'attente ComfyUI.
- **Série** : paramètres, personnages, chapitres (badges de statut, dates prévues, création,
  édition, réordonnancement).
- **Personnages**.
- **Scénario** (par chapitre) : synopsis → « Découper » → progression en direct → découpage
  éditable (pages, cases, description, personnages, plan, dialogues ; ajout / suppression / ordre).
- **Mise en page** (par chapitre) : page à l'échelle avec cases, gouttières, zones de bulles et
  numéros d'ordre de lecture ; gouttières déplaçables ; « Recalculer ».
- **Atelier de page** : clic sur une case → versions, QC (badge, raisons, boîtes détectées,
  relancer, « valider quand même »), « régénérer cette case » ; filtre « seulement les cases à
  revoir » et compteur QC du chapitre.
- **Presets**.

Sombre, moderne, rapide.

## 6. Jalons

1. Fondation + étapes 1–2 + écrans Série / Chapitres / Personnages / Scénario + aperçu du découpage.
2. Génération + file d'attente + atelier de page.
3. Contrôle qualité + lettrage + export.
4. ControlNet, upscaler, PSD, export vers nextseed-manga.

## 7. Tests

- ComfyUI, LLM et vision **toujours simulés** (le ComfyUI factice renvoie des images de la taille
  demandée).
- Tests unitaires : schéma du scénario, géométrie du découpage, placement des bulles,
  construction des workflows.
- Tests *golden image* pour l'assemblage.
