# Meal Planner

Planification de repas pour les foyers où **tout le monde ne mange pas la même
chose** — typiquement de jeunes enfants qui ne mangent pas le plat des adultes.

> **Lis `docs/ARCHITECTURE.md` avant de toucher au code.** C'est la colonne
> vertébrale du projet : décisions, justifications, et neuf invariants
> non négociables. Une décision qui contredit ce document doit d'abord modifier
> ce document.

**Statut : phase 0 — fondations.**

## Démarrer

```bash
cp .env.example .env
# Renseigner SESSION_SECRET, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
docker compose up --build
```

Puis <http://localhost:8080>.

Deux préalables :

1. **Ollama tourne sur l'hôte**, pas dans un conteneur (`docs/ARCHITECTURE.md`
   §7.3) — le relancer en conteneur dupliquerait un modèle de 5 Go et la RAM qui
   va avec. `ollama pull qwen3:8b` suffit pour le développement.
2. **Client OAuth Google** (Google Cloud Console → APIs & Services →
   Credentials → OAuth client ID, type Web). URI de redirection autorisée,
   exactement : `http://localhost:8080/api/auth/callback`.

Générer le secret de session :

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Tests

La CI ne contient que deux couches, et **aucun appel LLM réel** — c'est lent,
coûteux, instable, et ça ne teste rien de reproductible.

```bash
cd api
poetry install
poetry run pytest
```

| Couche | Contenu |
|---|---|
| Noyau déterministe | Stades de vie, portions, minimisation des prompts |
| Enveloppe | Le LLM est remplacé par `FakeLLMClient`, qui renvoie des sorties **hostiles** |

`FakeLLMClient` est la **troisième implémentation réelle** de l'interface LLM, au
même titre qu'Ollama et l'API cloud — pas un bouchon ajouté après coup. Sans
tests qui injectent des sorties invalides, le code de re-validation n'est jamais
exécuté avant le jour où il compte, et il sera faux.

## Structure

```
meal-planner/
├── docker-compose.yml     db / api / llm (hôte) / web + proxy
├── Caddyfile              origine unique : / → Next.js, /api → FastAPI
├── docs/ARCHITECTURE.md   ← la colonne vertébrale
├── api/
│   ├── app/domain/        entités et règles pures — ni SQL, ni HTTP, ni LLM
│   ├── app/llm/           l'interface unique et ses trois implémentations
│   ├── app/auth/          OAuth Google, cookie de session, foyer courant
│   ├── app/routers/       façade HTTP
│   ├── migrations/        Alembic
│   └── tests/
├── web/                   Next.js App Router, i18n-ready (fr par défaut)
├── db/                    seed du référentiel d'ingrédients (phase 1)
└── eval/                  fixtures figées + banc d'essai (phase 2)
```

## Les neuf invariants

Détail et justification dans `docs/ARCHITECTURE.md` §5.

| # | Invariant |
|---|---|
| I1 | Aucune décision de sécurité n'est prise par un LLM |
| I2 | Le filtre allergène porte sur des tags vérifiables, jamais sur du texte libre |
| I3 | `allergens_verified` est dérivé, jamais déclaré |
| I4 | Le matching approché ne s'applique jamais sans confirmation humaine |
| I5 | Le constructeur de prompt ne reçoit jamais l'entité `member` |
| I6 | `household_id` est dérivé de l'identité authentifiée |
| I7 | Aucun contenu généré par IA n'entre au catalogue |
| I8 | Aucune dépendance technique n'est codée en dur |
| I9 | Aucune republication de contenu externe |

## Phasage

| Phase | Contenu | Sortie |
|---|---|---|
| **0** | Fondations | *(en cours)* |
| **0-bis — V0** | Graphe agentic à coutures bouchonnées + conception UX | En ligne, usage interne |
| **1** | Scraper + référentiel + CRUD recettes | 300 recettes résolues |
| **2 — V1** | Workflow semaine réel + harness d'éval | MVP testable |
| **3** | Goûter et invités | |
| **4** | Anti-gaspi, scan frigo | |
| **5** | Polissage du front | |
