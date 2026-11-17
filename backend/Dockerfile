FROM node:24.22.3-bookworm-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54 AS dependencias
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

FROM dependencias AS testes
COPY src ./src
COPY tests ./tests
USER node
CMD ["node", "--test"]

FROM node:24.22.3-bookworm-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54 AS producao
ARG API_UID=10002
ARG MEDIA_GID=10000
RUN groupadd --gid ${MEDIA_GID} midia && useradd --uid ${API_UID} --gid midia --no-create-home api
WORKDIR /app
ENV NODE_ENV=production
COPY --from=dependencias /app/node_modules ./node_modules
COPY package.json ./
COPY src ./src
USER api
EXPOSE 3333
CMD ["node", "src/server.js"]
