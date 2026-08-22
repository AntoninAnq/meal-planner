# Two targets from one file: `dev` is what Compose runs locally, `runner` is
# what a host builds. Same base image, same lock file, one place to change.
#
# Compose names its target explicitly, so `docker build` with no `--target`
# gives the production image — the safer default of the two to get by accident.

FROM node:22-alpine AS deps

WORKDIR /app

# `npm ci` rather than `npm install`: it installs exactly the lock file, which
# is what makes the container and the CI agree on versions.
COPY package.json package-lock.json ./
RUN npm ci


# --- Local development ------------------------------------------------------
# Sources arrive through a bind mount, so none are copied here.

FROM deps AS dev

EXPOSE 3000

CMD ["npm", "run", "dev"]


# --- Build ------------------------------------------------------------------

FROM deps AS build

COPY . .

# `output: "standalone"` (next.config.ts) makes this emit a self-contained
# server plus only the node_modules it actually reached — the difference
# between an image of a few hundred megabytes and one of a few tens.
RUN npm run build


# --- Production -------------------------------------------------------------

FROM node:22-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production

# Not root. A Next.js server that never writes anything has no business owning
# its own files either.
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001

COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
# `static` is NOT inside `standalone` and must be copied beside it, or the page
# is served with no CSS and no JavaScript — a 200 that looks like a broken
# stylesheet rather than a missing file.
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static

# No `public/` directory in this project — there is nothing to serve statically
# that the build does not already emit. Add the COPY back the day one appears;
# without the directory the line fails the build, which is the right way round.

USER nextjs

EXPOSE 3000

# `HOSTNAME` and `PORT` are read by the standalone server itself, so the
# deployment sets them and nothing here needs a shell.
#
# HOSTNAME MUST BE `::` ON A HOST WHOSE PRIVATE NETWORK IS IPv6-ONLY — Railway
# is one. `0.0.0.0` binds IPv4 only, so the container starts, answers its own
# health check, and is unreachable from every other service: a failure that
# reads as "the proxy is misconfigured" and is not. `::` accepts both families.
ENV HOSTNAME=0.0.0.0 PORT=3000

CMD ["node", "server.js"]
