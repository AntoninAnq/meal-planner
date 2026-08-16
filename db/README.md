# Base de données

Le schéma est géré **exclusivement par Alembic** (`backend/migrations/`). Aucune
écriture de structure ne passe par un script ad hoc : les phases 1 et 2
modifieront le schéma, et une base créée à la main devient impossible à faire
évoluer une fois qu'elle contient de l'historique de repas réel.

```bash
docker compose exec api alembic upgrade head
docker compose exec api alembic revision -m "add recipe catalogue"
docker compose exec api alembic downgrade -1
```

## Ce dossier

Réservé au **seed du référentiel d'ingrédients** de la phase 1 : ~300-400
ingrédients courants de la cuisine familiale française, chacun mappé vers les 14
allergènes INCO et vers ses catégories alimentaires.

Ce seed est une **condition d'existence du filtre de sécurité**, pas un confort.
Il ne peut pas être amorcé par le scraper : le scraping arrive en phase 1 mais le
référentiel est nécessaire au premier CRUD de recettes. Le scraping **enrichit**
le référentiel, il ne le crée pas.

Extensions Postgres requises à ce moment-là : `unaccent` et `pg_trgm`
(normalisation et similarité trigramme du matching d'ingrédients, `docs/ARCHITECTURE.md` §I4).
