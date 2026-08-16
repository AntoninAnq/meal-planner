# Meal Planner

Planification de repas pour les foyers où **tout le monde ne mange pas la même
chose** — typiquement de jeunes enfants qui ne mangent pas le plat des adultes.

> **Lis `docs/ARCHITECTURE.md` avant de toucher au code.** C'est la colonne
> vertébrale du projet : décisions, justifications, et neuf invariants
> non négociables. Une décision qui contredit ce document doit d'abord modifier
> ce document.

**Statut : phase 1 — catalogue.** La V0 tourne (les six écrans du `UX-V0.md` §14
et le graphe agentic complet) ; ce qu'elle propose n'est vérifié par personne, ce
que l'interface dit elle-même.

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
cd backend
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
├── backend/               tout le Python — pas seulement l'API
│   ├── app/domain/        entités et règles pures — ni SQL, ni HTTP, ni LLM
│   ├── app/llm/           l'interface unique et ses trois implémentations
│   ├── app/auth/          OAuth Google, cookie de session, foyer courant
│   ├── app/routers/       façade HTTP
│   ├── app/catalog/       collecte et résolution du catalogue (phase 1)
│   ├── migrations/        Alembic
│   └── tests/
├── web/                   Next.js App Router, i18n-ready (fr par défaut)
├── db/                    référentiel d'ingrédients, versionné (phase 1)
└── eval/                  fixtures figées + banc d'essai (phase 2)
```

Le dossier s'appelle `backend/` et non `api/` : la façade HTTP n'en est qu'un
sous-dossier. Le service Docker, le hostname `api:8000` et la route `/api`
gardent le nom `api`, eux.

## Catalogue (phase 1)

Le pipeline de collecte tourne dans **sa propre image**, sur un service que
`docker compose up` ne démarre jamais :

```bash
docker compose run --rm catalog ingest --source cuisine-libre
docker compose run --rm catalog resolve          # rejouable, idempotent
docker compose run --rm catalog review           # les propositions I4, à confirmer
```

Il va chercher du contenu chez des tiers qui ne nous ont rien demandé. La
politique qu'on s'impose — cadence, absence de concurrence par domaine, arrêt sur
`429`, refus de contourner une protection anti-bot — est au §11.4 de
`docs/ARCHITECTURE.md`, et les sources testées, retenues **et écartées** sont au
§11.5.
