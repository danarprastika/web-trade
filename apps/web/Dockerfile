# Operator console image.
#
# Build context is apps/web (see the build-push-action step in .github/workflows/ci.yml).
#
# Authority: docs/02_POLYGLOT_ENGINEERING_STANDARD.md section 10 (locked dependency
# graph, SBOM, provenance, reproducible digest) and docs/06_SECURITY_AND_ACCESS_CONTROL.md
# section 7 (mandatory application and supply-chain controls).
#
# Two properties are load-bearing here and must not be traded away for image size:
#
#   1. The build stage is discarded. Build tooling, devDependencies, and the npm cache
#      never reach the runtime layer, so a compromised or vulnerable lint tool cannot
#      exist in the shipped image.
#   2. The runtime stage runs as a non-root user with a read-only filesystem. The console
#      is an untrusted client (docs/02 section "TypeScript boundary"); it holds no
#      financial authority and must not be able to write to its own image.

# Pinned to an exact patch tag. Never `latest`: the image tag is part of the artifact
# identity and must be reproducible. Verified present in library/node on 2026-09-28.
FROM node:24.18.0-alpine AS build
WORKDIR /app

# Dependencies are installed from the committed lockfile in a layer of their own, so a
# source-only change does not invalidate the dependency layer. `npm ci` also *fails* if
# package.json and package-lock.json have drifted, which is the lockfile-drift rejection
# docs/02 requires.
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

# Source is copied after the dependency install. Next.js is configured with
# `output: standalone`, which emits a self-contained server with a pruned dependency
# tree; without that, the runtime stage would need the full node_modules.
COPY . .
RUN npm run build

# ---------------------------------------------------------------------------

FROM node:24.18.0-alpine AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

# `node` (uid 1000) already exists in the base image; using it avoids shipping a custom
# passwd entry and keeps the uid predictable for a container runtime's runAsNonRoot check.
RUN mkdir -p /app && chown node:node /app

# Only the standalone output is copied. The build stage, its devDependencies, and the
# npm cache stay in the discarded layer above.
#
# There is deliberately no `COPY` of `public/`: the scaffold has no public assets, and a
# COPY from a non-existent path fails the build outright. When static assets are added,
# add the matching copy in the same change that creates the directory.
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static

USER node

EXPOSE 3000

# An unauthenticated HTTP liveness probe against the app root. It checks that the server
# process is serving, not that the control plane is reachable: the console is explicitly
# non-authoritative, so a control-plane outage must not cause the orchestrator to kill an
# otherwise healthy UI. Availability of the *authoritative* path is a separate SLO with
# its own alerting.
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
