"""« La petite île » et « La crique au pirate » : les textes de lieu des cases, tels que mesurés le 14/10 (#170).

Le lieu n'était qu'un texte libre recopié sur chaque case : « la petite île » comptait 24 « lieux » pour 38 cases,
« la crique au pirate » 24 pour 40 — des variantes de rédaction d'une poignée d'endroits. Les textes ci-dessous
reprennent ces variantes (même nombre de cases, même nombre de textes distincts) ; une case sur dix n'a pas de
texte du tout (cases de réaction écrites sans lieu).
"""

from __future__ import annotations

# 38 cases, 24 textes distincts (et 3 cases sans texte) ; 5 endroits réels.
PETITE_ILE: list[str] = [
    "plage, à l'aube, mer calme",
    "plage de l'île, sable blanc, barque échouée",
    "Plage, à l'aube, mer calme",  # même texte, autre casse : une seule variante
    "plage, matin, mouettes",
    "",
    "clairière",
    "clairière au centre de l'île",
    "Clairière au centre de l'île, herbes hautes",
    "clairière, midi, soleil vertical",
    "la clairière, des papillons",
    "",
    "clairière au centre de l'île",
    "forêt, sous-bois dense",
    "forêt de l'île, lianes",
    "la forêt, pénombre verte",
    "forêt, sentier étroit",
    "forêt, sous-bois dense",
    "grotte, entrée sombre",
    "grotte, stalactites, eau qui goutte",
    "la grotte, au fond, une lueur",
    "Grotte, entrée sombre",
    "grotte, galerie basse",
    "",
    "grotte, stalactites, eau qui goutte",
    "cabane, intérieur, lampe à huile",
    "cabane du vieux pêcheur, filets aux murs",
    "la cabane, devant la porte",
    "cabane, intérieur, lampe à huile",
    "cabane, soir, fenêtre éclairée",
    "plage de l'île, sable blanc, barque échouée",
    "plage, crépuscule, feu de camp",
    "plage, crépuscule, feu de camp",
    "clairière, nuit, étoiles",
    "clairière, nuit tombante",
    "forêt, au bord du ruisseau",
    "plage, à l'aube, mer calme",
    "cabane, soir, fenêtre éclairée",
    "plage, matin, mouettes",
]

# 40 cases, 24 textes distincts (et 4 cases sans texte) ; 5 endroits réels.
CRIQUE: list[str] = [
    "crique, eau turquoise, rochers noirs",
    "la crique, au pied de la falaise",
    "Crique, eau turquoise, rochers noirs",
    "",
    "crique au pirate, épave à demi enfouie",
    "crique, marée basse",
    "navire pirate, pont principal",
    "navire pirate, pont principal, voiles gonflées",
    "navire pirate, cale, tonneaux",
    "le navire pirate, à la proue",
    "",
    "navire pirate, cale, tonneaux",
    "falaise, sentier escarpé",
    "falaise au-dessus de la crique, vent fort",
    "la falaise, au sommet, vue sur la mer",
    "falaise, sentier escarpé",
    "taverne du port, comptoir",
    "taverne, salle enfumée",
    "taverne du port, comptoir",
    "la taverne, une table au fond",
    "",
    "taverne, salle enfumée",
    "taverne, nuit, chandelles",
    "port, quai, caisses empilées",
    "port, filets de pêche qui sèchent",
    "le port, au loin, les mâts",
    "port, quai, caisses empilées",
    "port, matin brumeux",
    "",
    "crique, marée haute",
    "crique, coucher de soleil",
    "crique, nuit sans lune",
    "navire pirate, cabine du capitaine",
    "falaise, à pic sur la mer",
    "taverne, nuit, chandelles",
    "port, matin brumeux",
    "crique au pirate, épave à demi enfouie",
    "la crique, au pied de la falaise",
    "navire pirate, cale, tonneaux",
    "crique, eau turquoise, rochers noirs",
]


def distinct(settings: list[str]) -> int:
    """Nombre de textes de lieu distincts (sans casse ni espaces en trop), comme mesuré sur les chapitres."""
    return len({" ".join(s.casefold().split()) for s in settings if s.strip()})


def pages(settings: list[str], per_page: int = 5) -> list[dict]:
    """Découpage (PUT /chapters/{id}/pages) : une case par texte, un personnage sur deux cases."""
    out = []
    for start in range(0, len(settings), per_page):
        out.append(
            {
                "panels": [
                    {
                        "description": f"Case {start + i + 1}",
                        "setting": text,
                        "characters": ["Lilo"] if (start + i) % 2 == 0 else [],
                    }
                    for i, text in enumerate(settings[start : start + per_page])
                ]
            }
        )
    return out
