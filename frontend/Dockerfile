FROM node:24.22.3-bookworm-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54 AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY
ARG NEXT_PUBLIC_API_URL=/api
ARG NEXT_PUBLIC_POLLING_LISTA_MS=5000
ARG NEXT_PUBLIC_POLLING_STATS_MS=30000
ENV NEXT_PUBLIC_SUPABASE_URL=${NEXT_PUBLIC_SUPABASE_URL} \
    NEXT_PUBLIC_SUPABASE_ANON_KEY=${NEXT_PUBLIC_SUPABASE_ANON_KEY} \
    NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_POLLING_LISTA_MS=${NEXT_PUBLIC_POLLING_LISTA_MS} \
    NEXT_PUBLIC_POLLING_STATS_MS=${NEXT_PUBLIC_POLLING_STATS_MS}
RUN npm run lint && npm run build

FROM node:24.22.3-bookworm-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54 AS producao
ARG FRONTEND_UID=10003
RUN groupadd --gid ${FRONTEND_UID} painel && useradd --uid ${FRONTEND_UID} --gid painel --no-create-home painel
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build --chown=painel:painel /app/.next/standalone ./
COPY --from=build --chown=painel:painel /app/.next/static ./.next/static
COPY --from=build --chown=painel:painel /app/public ./public
USER painel
EXPOSE 3000
CMD ["node", "server.js"]
