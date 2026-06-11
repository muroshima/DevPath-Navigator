# DevPath Navigator frontend container (Next.js standalone build).

FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev=false

FROM node:22-slim AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-slim AS runner
# The `node` user (uid 1000) ships in the base image; reuse it instead of
# running the Next.js server as root. Cloud Run's sandbox already constrains
# the process, but dropping privileges removes one privileged-by-default
# layer at no operational cost.
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=builder --chown=node:node /app/public ./public
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
USER node
ENV PORT=8080
EXPOSE 8080
CMD ["node", "server.js"]
