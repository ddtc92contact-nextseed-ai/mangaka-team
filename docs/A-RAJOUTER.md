# À rajouter — journal des manques

Ce fichier liste les idées notées à la demande du manager mais **pas encore décidées**. Une entrée
ne devient une issue GitHub que lorsque le manager donne son feu vert. Quand une entrée est réalisée,
elle n'est pas supprimée : son statut passe à « fait (#PR) ».

## État actuel

- 33 flows ComfyUI branchés, tous sur Qwen-Image 2.1 : 29 workflows d'image dans `presets/workflows/` (Croquis 2, Turbo 7, Rapide 7, Qualité 6, Qualité max 7) et 4 agrandisseurs dans `presets/upscalers/` (Real-ESRGAN x4plus anime 6B, 4x-UltraSharp, 4x Remacri, SeedVR2 7B).
- Croquis : brouillons des cases (`qwen-image-croquis`) ; Turbo : fiches de référence et planche de style (`workflow_library`) ; Qualité : cases des nouvelles séries et leur passage au propre (`from_sketch`) ; Turbo et Rapide restent proposés par série ; chaque palier a sa variante ControlNet (composition verrouillée) ; réparation ciblée en Turbo, Rapide et Qualité max (`qwen-image-inpaint*`) ; Qualité max sert à « Régénérer en Qualité » (`workflow_quality`) ; les agrandisseurs servent à la finition d'impression.
- Tous dessinent, redessinent ou agrandissent l'image : **aucun ne fait de travail spécialisé après le dessin**.

## FaceDetailer — visages et mains

- **Ce que ça fait** : un détecteur trouve chaque visage et chaque main de la case, les recadre, les
  redessine en plus grand, puis les recolle à leur place. Les yeux ratés et les mains à six doigts
  sont corrigés sans toucher au reste de la case.
- **Aujourd'hui dans l'appli** : seulement la réparation manuelle (`qwen-image-inpaint`,
  `qwen-image-inpaint-rapide`, `qwen-image-inpaint-turbo`), avec un masque peint à la main dans
  l'atelier.
- **Ce qu'il faudrait** : Impact Pack (déjà installé) et des détecteurs YOLO de visages et de mains
  (par ex. `face_yolov8m`, `hand_yolov8s`), absents au 09/10/2026 — à vérifier sur la GX10 avant
  installation.
- **Priorité proposée** : **1** (visages et mains représentent l'essentiel des retouches manuelles
  du manager).
- **Statut** : à décider.

## Trame (screentone)

- **Ce que ça fait** : une étape déterministe après le dessin transforme les zones grises en trame
  de points régulière, comme à l'impression d'un manga.
- **Aujourd'hui dans l'appli** : la trame est demandée en mots (pack de rendu `nb-trames`) ; Qwen la
  dessine de façon irrégulière, souvent grise et boueuse (problème de tonalité mesuré le
  11/10/2026).
- **Ce qu'il faudrait** : un nœud ComfyUI de trame (halftone) ou un traitement d'image côté moteur
  (seuils de gris → motifs de points), à choisir et vérifier sur la GX10 avant installation.
- **Priorité proposée** : 2 (touche toutes les séries en N&B à trames, le rendu par défaut).
- **Statut** : à décider.

## Colorisation

- **Ce que ça fait** : à partir d'une planche N&B déjà validée, produire une version couleur fidèle
  à l'encrage, sans la redessiner (par ex. une version couleur des chapitres qui marchent bien).
- **Aujourd'hui dans l'appli** : la couleur se choisit à la création de la série
  (`style_renderings/couleur`, `style_renderings/couleur-douce`) et la case est dessinée directement
  en couleur.
- **Ce qu'il faudrait** : un modèle de colorisation guidée par le trait (ControlNet lineart ou
  colorisation dédiée), à identifier et vérifier sur la GX10 avant installation.
- **Priorité proposée** : 4 (utile une fois des chapitres N&B validés).
- **Statut** : à décider.

## Fond transparent (détourage)

- **Ce que ça fait** : suppression automatique du fond pour obtenir des personnages et des objets
  isolés, envoyés comme références sans que le blanc ne déborde dans les cases, et qu'on peut
  composer sur un décor.
- **Aujourd'hui dans l'appli** : les fiches de personnage et d'objet sortent sur fond blanc.
- **Ce qu'il faudrait** : un modèle de détourage (par ex. RMBG ou BiRefNet) et son nœud ComfyUI, à
  vérifier sur la GX10 avant installation.
- **Priorité proposée** : 3.
- **Statut** : à décider.

## Autres idées

<!-- Nouvelles entrées ici, au même format. -->
