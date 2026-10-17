/* Exemple FACTICE (base inventée par tests/base_factice.py) : chiffres plausibles, pas mesurés. Régénérer : python3 mangaka-tuto/tests/base_factice.py /tmp/f.db && python3 mangaka-tuto/mesurer.py /tmp/f.db --exemple --sortie mangaka-tuto/data/mesures.exemple.js */
window.MESURES = {
 "version": 1,
 "genere_le": "2026-10-17T13:17:58Z",
 "base": "base factice (tests/base_factice.py)",
 "commande": "python3 mangaka-tuto/mesurer.py <chemin-base>",
 "vide": false,
 "raison": "",
 "periode": {
  "debut": "2026-10-05T09:00:00Z",
  "fin": "2026-10-09T03:26:19Z"
 },
 "totaux": {
  "jobs": 180,
  "echecs": 3,
  "annules": 0,
  "en_cours": 0,
  "chapitres": 3
 },
 "goulot": "generation",
 "etapes": [
  {
   "etape": "generation",
   "file_comfy": true,
   "jobs": 81,
   "statuts": {
    "succeeded": 79,
    "failed": 2
   },
   "taux_echec": 0.0247,
   "duree_ms": {
    "n": 79,
    "mediane": 40591,
    "p90": 208099,
    "max": 229564,
    "total": 7220082
   },
   "attente_ms": {
    "n": 81,
    "mediane": 81315,
    "p90": 1684778,
    "max": 2210929,
    "total": 41249814
   },
   "part_attente": 0.667,
   "erreurs": [
    {
     "message": "ComfyUI n'a pas terminé la génération en # s (délai réglable : timeout_s du preset qwen-image-base-qualite)",
     "n": 1
    },
    {
     "message": "Interrompu par un redémarrage du moteur",
     "n": 1
    }
   ],
   "cout_ms": 48469896
  },
  {
   "etape": "qc",
   "file_comfy": true,
   "jobs": 36,
   "statuts": {
    "succeeded": 36
   },
   "taux_echec": 0.0,
   "duree_ms": {
    "n": 36,
    "mediane": 3448,
    "p90": 17338,
    "max": 36310,
    "total": 241657
   },
   "attente_ms": {
    "n": 36,
    "mediane": 1273541,
    "p90": 2183954,
    "max": 2391858,
    "total": 45914274
   },
   "part_attente": 0.9973,
   "erreurs": [],
   "cout_ms": 46155931
  },
  {
   "etape": "finishing",
   "file_comfy": true,
   "jobs": 36,
   "statuts": {
    "succeeded": 36
   },
   "taux_echec": 0.0,
   "duree_ms": {
    "n": 36,
    "mediane": 35662,
    "p90": 41384,
    "max": 43809,
    "total": 1248313
   },
   "attente_ms": {
    "n": 36,
    "mediane": 187528,
    "p90": 356435,
    "max": 408142,
    "total": 6899275
   },
   "part_attente": 0.8402,
   "erreurs": [],
   "cout_ms": 8147588
  },
  {
   "etape": "reference",
   "file_comfy": true,
   "jobs": 8,
   "statuts": {
    "succeeded": 8
   },
   "taux_echec": 0.0,
   "duree_ms": {
    "n": 8,
    "mediane": 34982,
    "p90": 41986,
    "max": 44045,
    "total": 284900
   },
   "attente_ms": {
    "n": 8,
    "mediane": 407112,
    "p90": 506284,
    "max": 528029,
    "total": 3241375
   },
   "part_attente": 0.9209,
   "erreurs": [],
   "cout_ms": 3526275
  },
  {
   "etape": "style_board",
   "file_comfy": true,
   "jobs": 4,
   "statuts": {
    "succeeded": 4
   },
   "taux_echec": 0.0,
   "duree_ms": {
    "n": 4,
    "mediane": 68120,
    "p90": 79110,
    "max": 83364,
    "total": 280479
   },
   "attente_ms": {
    "n": 4,
    "mediane": 116893,
    "p90": 198851,
    "max": 219606,
    "total": 453392
   },
   "part_attente": 0.6318,
   "erreurs": [],
   "cout_ms": 733871
  },
  {
   "etape": "cover",
   "file_comfy": true,
   "jobs": 2,
   "statuts": {
    "succeeded": 2
   },
   "taux_echec": 0.0,
   "duree_ms": {
    "n": 2,
    "mediane": 232365,
    "p90": 238950,
    "max": 240596,
    "total": 464730
   },
   "attente_ms": {
    "n": 2,
    "mediane": 112067,
    "p90": 201721,
    "max": 224135,
    "total": 224135
   },
   "part_attente": 0.3254,
   "erreurs": [],
   "cout_ms": 688865
  },
  {
   "etape": "script",
   "file_comfy": false,
   "jobs": 4,
   "statuts": {
    "succeeded": 3,
    "failed": 1
   },
   "taux_echec": 0.25,
   "duree_ms": {
    "n": 3,
    "mediane": 152185,
    "p90": 156383,
    "max": 157432,
    "total": 411791
   },
   "attente_ms": {
    "n": 4,
    "mediane": 24,
    "p90": 30,
    "max": 30,
    "total": 95
   },
   "part_attente": 0.0002,
   "erreurs": [
    {
     "message": "Le LLM n'a pas pu répondre : DeepSeek n'a pas répondu à temps",
     "n": 1
    }
   ],
   "cout_ms": 411886
  },
  {
   "etape": "art_direction",
   "file_comfy": false,
   "jobs": 3,
   "statuts": {
    "succeeded": 3
   },
   "taux_echec": 0.0,
   "duree_ms": {
    "n": 3,
    "mediane": 51599,
    "p90": 63833,
    "max": 66892,
    "total": 163774
   },
   "attente_ms": {
    "n": 3,
    "mediane": 9,
    "p90": 26,
    "max": 30,
    "total": 45
   },
   "part_attente": 0.0002,
   "erreurs": [],
   "cout_ms": 163819
  },
  {
   "etape": "scenes",
   "file_comfy": false,
   "jobs": 3,
   "statuts": {
    "succeeded": 3
   },
   "taux_echec": 0.0,
   "duree_ms": {
    "n": 3,
    "mediane": 39409,
    "p90": 42312,
    "max": 43038,
    "total": 118931
   },
   "attente_ms": {
    "n": 3,
    "mediane": 22,
    "p90": 24,
    "max": 25,
    "total": 50
   },
   "part_attente": 0.0006,
   "erreurs": [],
   "cout_ms": 118981
  },
  {
   "etape": "export",
   "file_comfy": false,
   "jobs": 3,
   "statuts": {
    "succeeded": 3
   },
   "taux_echec": 0.0,
   "duree_ms": {
    "n": 3,
    "mediane": 21473,
    "p90": 24707,
    "max": 25515,
    "total": 62196
   },
   "attente_ms": {
    "n": 3,
    "mediane": 18,
    "p90": 20,
    "max": 20,
    "total": 51
   },
   "part_attente": 0.0008,
   "erreurs": [],
   "cout_ms": 62247
  }
 ],
 "chapitres": [
  {
   "chapitre_id": 1,
   "numero": 1,
   "titre": "Le départ",
   "jobs": 54,
   "debut": "2026-10-05T10:09:25Z",
   "fin": "2026-10-05T14:52:31Z",
   "duree_totale_ms": 16986222,
   "temps_machine_ms": {
    "generation": 2466630,
    "finishing": 378756,
    "script": 157432,
    "qc": 93896,
    "art_direction": 51599,
    "scenes": 43038,
    "export": 15208
   },
   "temps_humain_ms": 13779552,
   "absences": 0,
   "transitions": [
    {
     "passage": "finishing → export",
     "n": 1,
     "mediane_ms": 5254951
    },
    {
     "passage": "qc → generation",
     "n": 1,
     "mediane_ms": 2225266
    },
    {
     "passage": "scenes → script",
     "n": 1,
     "mediane_ms": 1439662
    },
    {
     "passage": "script → art_direction",
     "n": 1,
     "mediane_ms": 1195454
    },
    {
     "passage": "art_direction → generation",
     "n": 1,
     "mediane_ms": 1031693
    },
    {
     "passage": "generation → finishing",
     "n": 1,
     "mediane_ms": 535765
    }
   ]
  },
  {
   "chapitre_id": 2,
   "numero": 2,
   "titre": "La fuite",
   "jobs": 55,
   "debut": "2026-10-06T11:26:24Z",
   "fin": "2026-10-06T15:58:30Z",
   "duree_totale_ms": 16325802,
   "temps_machine_ms": {
    "generation": 2479674,
    "finishing": 436570,
    "script": 152185,
    "qc": 76705,
    "art_direction": 45283,
    "scenes": 39409,
    "export": 25515
   },
   "temps_humain_ms": 13070324,
   "absences": 0,
   "transitions": [
    {
     "passage": "finishing → export",
     "n": 1,
     "mediane_ms": 3633945
    },
    {
     "passage": "script → art_direction",
     "n": 1,
     "mediane_ms": 2145777
    },
    {
     "passage": "qc → generation",
     "n": 1,
     "mediane_ms": 1535164
    },
    {
     "passage": "art_direction → generation",
     "n": 1,
     "mediane_ms": 1017604
    },
    {
     "passage": "scenes → script",
     "n": 1,
     "mediane_ms": 936144
    },
    {
     "passage": "generation → finishing",
     "n": 1,
     "mediane_ms": 434755
    }
   ]
  },
  {
   "chapitre_id": 3,
   "numero": 3,
   "titre": "Le marché aux lanternes",
   "jobs": 57,
   "debut": "2026-10-07T18:21:33Z",
   "fin": "2026-10-07T22:03:03Z",
   "duree_totale_ms": 13289571,
   "temps_machine_ms": {
    "generation": 2632009,
    "finishing": 432987,
    "script": 197174,
    "qc": 71056,
    "art_direction": 66892,
    "scenes": 36484,
    "export": 21473
   },
   "temps_humain_ms": 9831409,
   "absences": 0,
   "transitions": [
    {
     "passage": "finishing → export",
     "n": 1,
     "mediane_ms": 2529091
    },
    {
     "passage": "qc → generation",
     "n": 1,
     "mediane_ms": 1774014
    },
    {
     "passage": "script → art_direction",
     "n": 1,
     "mediane_ms": 1348163
    },
    {
     "passage": "scenes → script",
     "n": 1,
     "mediane_ms": 892914
    },
    {
     "passage": "generation → finishing",
     "n": 1,
     "mediane_ms": 544421
    },
    {
     "passage": "art_direction → generation",
     "n": 1,
     "mediane_ms": 478737
    }
   ]
  }
 ],
 "cases": {
  "cases": 36,
  "images_par_case": {
   "n": 36,
   "mediane": 3,
   "p90": 6,
   "max": 7,
   "total": 118
  },
  "regenerations_par_case": {
   "n": 36,
   "mediane": 2,
   "p90": 4,
   "max": 6,
   "total": 82
  },
  "versions_finales_presentes": {
   "n": 36,
   "mediane": 2,
   "p90": 4,
   "max": 5,
   "total": 68
  },
  "croquis_presents": 45,
  "histogramme": [
   0,
   14,
   8,
   9,
   1,
   4
  ],
  "cases_3_regenerations_ou_plus": 14
 },
 "qc": {
  "images_controlees": 68,
  "verdicts": {
   "reject": 4,
   "ok": 55,
   "review": 9
  },
  "taux_rejet": 0.0588,
  "taux_a_revoir": 0.1324,
  "valides_quand_meme": 2,
  "couches": [
   {
    "couche": "detectors",
    "passees": 68,
    "sautees": 0,
    "en_erreur": 0,
    "indisponibles": 0,
    "rejet": 5,
    "a_revoir": 9,
    "taux_rejet": 0.0735,
    "taux_a_revoir": 0.1324,
    "duree_ms": {
     "n": 68,
     "mediane": 20,
     "p90": 28,
     "max": 30,
     "total": 1319
    },
    "statuts": {
     "done": 68
    }
   },
   {
    "couche": "identity",
    "passees": 32,
    "sautees": 36,
    "en_erreur": 0,
    "indisponibles": 0,
    "rejet": 0,
    "a_revoir": 9,
    "taux_rejet": 0.0,
    "taux_a_revoir": 0.2812,
    "duree_ms": {
     "n": 32,
     "mediane": 377,
     "p90": 556,
     "max": 600,
     "total": 12693
    },
    "statuts": {
     "skipped": 36,
     "done": 32
    }
   },
   {
    "couche": "vision",
    "passees": 46,
    "sautees": 22,
    "en_erreur": 0,
    "indisponibles": 0,
    "rejet": 18,
    "a_revoir": 9,
    "taux_rejet": 0.3913,
    "taux_a_revoir": 0.1957,
    "duree_ms": {
     "n": 46,
     "mediane": 27002,
     "p90": 32350,
     "max": 34099,
     "total": 1226827
    },
    "statuts": {
     "skipped": 22,
     "done": 46
    }
   }
  ]
 },
 "reparations": {
  "generations_journalisees": 133,
  "par_sorte": {
   "croquis": 45,
   "panel": 68,
   "inpaint": 20
  },
  "sortes": [
   {
    "sorte": "croquis",
    "n": 45,
    "echecs": 0,
    "duree_ms": {
     "n": 45,
     "mediane": 117486,
     "p90": 201152,
     "max": 219486,
     "total": 5186105
    }
   },
   {
    "sorte": "inpaint",
    "n": 20,
    "echecs": 2,
    "duree_ms": {
     "n": 18,
     "mediane": 39960,
     "p90": 49045,
     "max": 49776,
     "total": 720854
    }
   },
   {
    "sorte": "panel",
    "n": 68,
    "echecs": 0,
    "duree_ms": {
     "n": 68,
     "mediane": 105730,
     "p90": 204803,
     "max": 219887,
     "total": 7831026
    }
   }
  ],
  "reparations": 20,
  "reparations_statuts": {
   "succeeded": 18,
   "failed": 2
  },
  "reparations_duree_ms": {
   "n": 18,
   "mediane": 39960,
   "p90": 49045,
   "max": 49776,
   "total": 720854
  },
  "cases_reparees": 14,
  "evenements_auteur": {
   "actions": {
    "repair": 20
   },
   "verdicts": {
    "edited": 20
   }
  }
 },
 "signaux": {
  "interrompus_redemarrage": 1,
  "llm_sans_reponse": 1,
  "comfy_delai_depasse": 1,
  "comfy_injoignable": 0,
  "vision_sautee_comfy_occupe": 6,
  "vision_en_erreur": 0,
  "relances_auto_qc": 0,
  "jobs_annules": 0
 },
 "exemple": true
};
