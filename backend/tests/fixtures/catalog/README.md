# Fixtures d'extraction

Une page réelle par **forme de balisage** rencontrée sur les sources retenues
(`docs/ARCHITECTURE.md` §11.5). Ce sont les cas qui ont motivé chaque branche de
l'extracteur ; les geler oblige une modification à dire quelle forme réelle elle
cesse de traiter.

| Fichier | Ce qu'il teste |
|---|---|
| `json_ld_invalid_microdata_ingredients.html` | JSON-LD **invalide** (virgule traînante) et **sans ingrédients** ; microdata `recipeIngredient` ; en-têtes de section ; licence `CC0` déclarée ; durée laissée à `?` |
| `selector_durations.html` | Même forme, durées **renseignées** — exerce le sélecteur du descripteur |
| `json_ld_complete.html` | JSON-LD complet et propre |
| `json_ld_multiple_blocks.html` | Trois blocs JSON-LD, un seul est la recette |
| `microdata_legacy_property.html` | Microdata avec `itemprop="ingredients"`, la forme **dépréciée** |
| `not_a_recipe.html` | Page de tag — doit revenir « pas une recette », pas une recette vide |

**Le nom du fichier est la forme, pas la provenance.** Un test qui vérifie que la
propriété dépréciée est lue n'a pas besoin de dire qui l'émet.

## Elles sont expurgées et anonymisées, et c'est vérifiable

Deux règles s'appliquent, pour deux raisons différentes.

**I9 interdit de republier la prose d'un auteur**, et « c'est pour les tests »
n'est pas une licence.

**Ce dépôt est public**, et ces pages viennent de sites dont les auteurs n'ont
rien demandé. Renommer les fichiers seul aurait été du théâtre : une seule page
réduite portait **195 URL absolues** vers son origine.

Les deux passes sont faites par `reduce.py`, donc reproductibles et auditables :

```bash
python reduce.py page_telechargee.html json_ld_complete.html nomdusite "nom du site"
```

### Ce qui est supprimé, élidé, réécrit, conservé

- **Supprimé** — tout `<script>` sauf `application/ld+json`, styles, images,
  iframes.
- **Élidé** — le texte de `recipeInstructions` et de `description`, plus tout
  nœud de texte de plus de 110 caractères hors `itemprop` : c'est là que vivent
  les introductions, les anecdotes et les commentaires.
- **Réécrit** — tout hôte absolu devient `exemple.test`, et les noms passés en
  argument sont remplacés.
- **Conservé** — la structure, les attributs que les sélecteurs utilisent, les
  libellés courts de gabarit (`Durée totale : 55 min` est un champ, pas une
  œuvre), et **`schema.org` comme `creativecommons.org`** : le premier nomme le
  vocabulaire, le second est un fait que l'extracteur lit et stocke. Les réécrire
  ferait des fixtures qui ne testent plus rien.

### Trois subtilités, chacune parce qu'elle a cassé une fixture

1. **La longueur des listes d'instructions est préservée.** `recipeInstructions`
   est presque toujours un tableau, et sa longueur est le nombre d'étapes — un
   fait que l'extracteur lit et que I9 ne protège pas. Remplacer le tableau par
   une chaîne supprimait les mots de l'auteur **et** le nombre.
2. **Un JSON-LD invalide n'est jamais re-sérialisé.** Il reste tel quel, sinon la
   réparation effacerait le défaut que la fixture existe pour reproduire.
3. **Une balise fermante sans ouvrante est ignorée**, jamais dépilée. Les vraies
   pages laissent des `<p>` et des `<li>` ouverts ; dépiler jusqu'à trouver
   fermait `<body>` et `<html>` par anticipation, et la fixture se retrouvait
   tronquée juste avant le balisage intéressant.
