# Évaluation

Hors CI. Objectif : **comparer des modèles** (Ollama 8B vs Haiku 4.5 vs Sonnet 5)
et détecter les régressions de prompt. Voir `docs/ARCHITECTURE.md` §14.

Le contenu arrive en **phase 2**, avec le workflow semaine réel. Ce dossier est
créé dès la phase 0 pour que les fixtures aient une place évidente et ne
finissent pas éparpillées dans les tests.

## Ce qui vivra ici

```
eval/
├── fixtures/          jeu de données FIGÉ et commité
│   ├── catalogue.yaml
│   └── households/    bébé seul, allergie sévère, intolérance forçant
│                      un 2ᵉ plat, ado + jeune enfant, sans contrainte
├── cases/             un fichier par cas, à trois sections
└── run.py             exécute, agrège, produit le tableau comparatif
```

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
