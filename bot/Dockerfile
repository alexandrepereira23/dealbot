FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS dependencias
WORKDIR /build
COPY requirements.lock ./
# Apenas ferramentas de build; não são copiadas para runtime.
RUN pip install --no-cache-dir setuptools==80.9.0 wheel==0.45.1 && \
    pip install --no-cache-dir --no-build-isolation --require-hashes --target /opt/deps -r requirements.lock

FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS base
ARG BOT_UID=10001
ARG MEDIA_GID=10000
RUN groupadd --gid ${MEDIA_GID} midia && useradd --uid ${BOT_UID} --gid midia --no-create-home bot
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/opt/deps
WORKDIR /app
COPY --from=dependencias /opt/deps /opt/deps
COPY src ./src
USER bot

FROM base AS testes
COPY tests ./tests
COPY simulacao.py simulacao_identidade.py cenarios_identidade.py ./
CMD ["python", "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]

FROM base AS producao
CMD ["python", "-m", "src.main"]
