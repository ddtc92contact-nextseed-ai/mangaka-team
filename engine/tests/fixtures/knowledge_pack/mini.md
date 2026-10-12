---
title: mini — pack de test
version: 1.0
---

# mini

> Chapeau du fichier : jamais importé.

---

## 0.A — Mode d'emploi

Texte d'indexation, ignoré.

## 0.B — Vocabulaire

Échelles : `close_up` (gros plan), `long` (plan d'ensemble).

## 0.C — Format de case

Chaque case sort avec ces champs.

```json
{"panel_id": "p01_c1", "intent": ["fear", "tension"], "shot_scale": "close_up"}
```

---

## 01_cadrages

> Chapeau de section : non importé.

### SHOT_CU_001 — Gros plan (visage)
`path: 01_cadrages/gros_plan.md`

```meta
{"id":"SHOT_CU_001","type":"shot_scale","shot_scale":"close_up","camera_angle":"low","intent":["emotion","decision"],"pairs_with":["EMO_002"]}
```

**Définition.** Le visage remplit la case ; on entre dans la subjectivité du personnage.

**Prompt (EN).** `close-up, face filling the frame`

---

### SHOT_LS_001 — Plan d'ensemble
`path: 01_cadrages/plan_ensemble.md`

```meta
{"id":"SHOT_LS_001","type":"shot_scale","shot_scale":"long","intent":["establish_place"]}
```

**Définition.** Le personnage entier et beaucoup de décor autour de lui.

---

## 07_emotions

### EMO_002 — Colère
`path: 07_emotions/colere.md`

```meta
{"id":"EMO_002","type":"emotion","shot_scale":"variable","camera_angle":"variable","intent":["anger"]}
```

**Principe.** La colère monte : mâchoire serrée, poings fermés, cadre qui se resserre.

---

## Annexe A — Checklist

1. Chaque case a-t-elle une intention ?
2. Aucun plan répété trois fois de suite ?

## Annexe C — Sources

Livres et articles, ignorés.

## Annexe Z — Section oubliée par le manifeste

Ignorée et signalée.
