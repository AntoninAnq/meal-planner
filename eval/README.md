# Évaluation

Hors CI. Objectif : **comparer des modèles** (Ollama 8B vs Haiku 4.5 vs Sonnet 5)
et détecter les régressions de prompt. Voir `docs/ARCHITECTURE.md` §14.

```bash
docker compose run --rm --no-deps \
    -v "$PWD/eval:/eval" -v "$PWD/db:/db:ro" -w / api \
    python /eval/run.py --runs 5
```

Le modèle vient de l'environnement (`LLM_PROVIDER`, `OLLAMA_MODEL`) : comparer
deux modèles, c'est deux exécutions avec une seule variable changée.

```
eval/
├── generate_fixtures.py   compose le catalogue depuis db/ingredients.yaml
├── fixtures/              FIGÉ et commité — engendré, jamais édité à la main
│   ├── catalogue.yaml     80 recettes
│   └── households.yaml    bébé seul, allergie sévère, intolérance forçant
│                          un 2ᵉ plat, ado + jeune enfant, sans contrainte
├── cases/                 un fichier par cas, à trois sections
└── run.py                 exécute dans une base jetable, agrège, rapporte
```

## Les fixtures sont ENGENDRÉES, pas copiées

C'est la correction la plus importante de ce fichier. Un `catalogue.yaml` figé
contenant trois cents titres et listes d'ingrédients recopiés de blogs, commité
sur un dépôt public, satisferait le §14.1 en violant **I9**.

Le catalogue est donc **composé** depuis `db/ingredients.yaml` — notre propre
fichier, écrit à la main — par `generate_fixtures.py`, avec des titres assemblés
par gabarits. Aucun contenu externe, aucun modèle : ni I9 ni I7 ne sont en jeu.
Les recettes y portent `source_type: user`, ce qui est la vérité.

**Ce dont le banc a besoin est une STRUCTURE réaliste, pas un contenu
authentique** : la distribution des allergènes, des types de plat, du nombre
d'ingrédients et de l'effort. Elles émergent ici comme en production — les
allergènes sont **dérivés** des ingrédients par la vraie passe de résolution,
pas déclarés par la fixture, sinon on testerait la fixture.

Ce que ce choix ne couvre pas : la qualité du parseur et de l'extraction. Elle
se mesure ailleurs, sur les lignes réelles de `test_ingredient_lines.py` — des
fragments de quelques mots, ce qui n'est pas la même chose que publier trois
cents recettes.

## Pourquoi 80 recettes et pas 300

Mesuré sur le vrai catalogue : le lait est porté par 62 % des recettes
éligibles, le gluten par 46 %. Une allergie sévère lait + gluten en laisse
donc ~28 %. À 80 recettes, ce pire cas tombe à une vingtaine de candidats pour
dix-huit plats — **le bord où le pré-filtre doit avoir raison**, et c'est là
qu'un banc d'essai gagne son coût.

Trois cents enterreraient ce cas. Quatre-vingts gardent le fichier lisible, et
**une fixture que personne ne peut lire n'explique aucun échec** : quand un cas
tombe, il faut pouvoir ouvrir le catalogue et comprendre pourquoi le pré-filtre
a rendu ces quatre recettes-là.

## Deux règles à ne pas contourner

**Les fixtures sont figées et commitées.** Un banc d'essai qui tape sur la base
de production ne permet aucune comparaison dans le temps : le catalogue grossit,
l'historique change, et le score d'octobre n'est pas comparable à celui de
décembre. On croirait avoir changé de modèle alors qu'on a changé de données.

**5 runs minimum par cas, des taux jamais un booléen.** Un run par cas ne mesure
rien sur un système stochastique. Un golden qui passe une fois sur deux et qu'on
relance jusqu'au vert est pire que pas de golden — il donne une confiance fausse.

## Structure d'un cas

```yaml
case: household_severe_peanut_allergy
runs: 5

# 1. Noyau déterministe — égalité stricte, un diff, un échec net.
#    C'est ici que les garanties de sécurité sont vérifiées.
expected_exact:
  candidates_after_filters: [r_012, r_037, r_041, r_055]
  portions_monday_dinner: { teen_adult: 1.0, young_child: 0.5 }
  minimum_feasible_clusters: 2

# 2. Couche LLM — invariants durs et taux.
expected_properties:
  allergen_violations: 0          # dur, 0 toléré
  dishes_outside_candidates: 0    # dur, 0 toléré
  distinct_dishes_per_slot: "<= 3"
  legumes_signal_followed: ">= 4/5"

# 3. Référence humaine — ne fait échouer aucun test.
#    Sert de base de comparaison et de repère de lecture pour l'appétence.
human_reference:
  monday_dinner:
    - dish: "…"
      eaters: [m1, m2]
```

## Score de distance à la référence

**Ne jamais scorer l'identité des recettes.** Un plan qui ne partage aucune
recette avec la référence peut être tout aussi bon — c'est même le comportement
souhaité. Un Jaccard sur les identifiants pénaliserait exactement ce qu'on veut
encourager ; il s'affiche, hors score.

Score composite sur trois distances déterministes :

| Distance | Calcul |
|---|---|
| Structurelle | Plats distincts par créneau + motif d'assignation |
| Catégorielle | Distance L1 entre vecteurs de `food_category` sur la semaine |
| Effort | Temps de préparation cumulé, nombre de recettes complexes |

Le **LLM-juge est repoussé** : du non-déterministe qui évalue du
non-déterministe, à valider lui-même, et qui demande un modèle plus gros que
celui testé — donc plus cher que ce qu'il évalue.
