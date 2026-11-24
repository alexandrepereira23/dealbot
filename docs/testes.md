# Testes e validação do Dealbot

[Visão geral](../README.md) · [Execução local](uso-local.md) · [Implantação em VPS](deploy-vps.md)

Escolha o escopo conforme a mudança. Ao relatar uma falha, informe a revisão
testada, o sistema operacional, a versão do Compose e o resultado observado.
Não inclua JWTs, imagens privadas, dumps ou textos de mensagens.

| Verificação | Escopo |
| --- | --- |
| `docker compose … config --quiet` | Estática: configuração resolve, sem mostrar segredos. Não testa build, rede, soquetes, volumes ou aplicação. |
| [Ensaio automatizado Docker/Linux](#ensaio-automatizado-dockerlinux) | Sintético: bot e API não root, UID/GID e modos, criação WebP, leitura/remoção sob reserva, bloqueio de coletor concorrente, saída graciosa, retomada com foto pendente, SQLite e JSON persistentes, pré-checagem 0/2/1 sem token em logs. Inclui UI automatizada e suíte SQL com PostgreSQL real e papéis fictícios. |
| [Demonstração manual](#demonstração-manual) | Navegador de uso com CA confiável, login fictício, oferta antes da foto, atualização por polling e cópia de `LAB10`. |
| [Modo B real](#validação-do-modo-b) | Supabase Auth, acesso ao schema e, somente se autorizado, uma sessão Telegram que leia canais autorizados. Não é comprovado pelo laboratório. |

## Demonstração manual

1. Siga o [roteiro da demonstração](uso-local.md#modo-a--demonstração-sem-credenciais)
   sem reutilizar o projeto ou os volumes reais.
2. Confie na CA no perfil de teste. Abra `https://localhost:18443`, verifique que
   não há alerta TLS e entre com o login sintético.
3. Rode `oferta`. Com a aba visível, confirme card e link de compra antes da
   imagem. Clique em **Copiar cupom** e cole em campo local: deve resultar em
   `LAB10`. Confira em desktop e em viewport móvel; emulação de largura não é
   teste em aparelho físico. Não publique o laboratório na LAN para testá-lo.
4. Só então rode `foto`. O mesmo card deve atualizar sem F5 e apresentar seu WebP.
5. Pare e recrie sem `-v` e verifique que a oferta e a foto continuam. Para provar
   a retomada do job **antes** da foto, o bloqueio de segunda instância e os
   checkpoints, execute o ensaio automatizado abaixo.

## Ensaio automatizado Docker/Linux

Na raiz, com engine Linux, Python 3.12 no host, Node 24 e Playwright com Chromium
instalado. Substitua os dois caminhos de exemplo pelos absolutos do seu ambiente.
O ensaio usa um projeto novo e as portas 18443/54329; pare a demonstração manual
antes de executá-lo. Não precisa dos envs privados ou de contas reais.

```bash
python -B deploy/lab/validar-compose.py \
  --node /caminho/absoluto/ao/node \
  --playwright /caminho/absoluto/ao/playwright/index.mjs
```

O runner usa a CA exportada para o ensaio, sem instalação automática no host.
Ele deve parar apenas o próprio projeto e preservar os volumes do ensaio. A suíte
SQL separada, descrita no [guia de VPS](deploy-vps.md#9-reproduzir-laboratório),
não substitui a validação real de Auth, PostgREST e Storage do Supabase.

## Validação do modo B

- **Sem credenciais reais:** execute `config --quiet` com os arquivos de exemplo
  e mantenha o serviço `bot` fora de uma subida normal. Valide o inicializador
  compartilhado em volumes novos e sintéticos; ele é o mesmo executado pelo
  modo A. Não inicialize a aplicação com envs de produção em ensaio sintético.
- **Com Supabase de teste:** inicie só `api`, `painel` e `caddy`, confira a origem
  e a CA, saúde (`/api/health`), 401 em lista sem JWT e a pré-checagem com limpeza
  suspensa. Faça login com seu usuário de teste e verifique polling; teste cópia
  em oferta de teste que tenha cupom. Confirme que `bot` não foi iniciado.
- **Com autorização de coleta:** use o [opt-in explícito](uso-local.md#habilitar-a-coleta-telegram-opcional)
  em uma conta que tenha acesso aos canais escolhidos. Confirme que há um único
  coletor, que a fila avança e que não há erro de permissões. Ensaie exportação e
  recuperação em destino descartável antes de depender das cópias locais.

## Suítes por componente

Use ambiente de teste sem `.env` real; `npm ci` usa os lockfiles e requer rede
para baixar dependências. Para o bot, instale as dependências em um ambiente
virtual Python 3.12 com `bot/requirements.txt`; os testes POSIX precisam de
Linux/WSL e os contratos de SDK precisam das dependências instaladas.

```bash
# Raiz
python -B -m unittest discover -s deploy/tests -v

# Pasta bot/
python -B -m unittest discover -s tests -v
python -m pip check

# Pasta backend/, Node 24 LTS
npm ci
npm test

# Pasta frontend/, Node 24 LTS
npm ci
npm test
npm run lint
npm run typecheck
NEXT_PUBLIC_SUPABASE_URL=https://teste.example.invalid \
  NEXT_PUBLIC_SUPABASE_ANON_KEY=anon-sintetica NEXT_PUBLIC_API_URL=/api npm run build
```

### Testes SQL

O ensaio Docker inclui seu próprio PostgreSQL descartável. Para rodar as suítes
SQL separadamente em `backend/`, consulte os requisitos dos runners
[`npm run test:sql`](../backend/tests/sql-etapa2.local.mjs) e
[`npm run test:sql:etapa3`](../backend/tests/sql-etapa3.local.mjs).
Use apenas um banco **local, vazio e descartável**, não um projeto Supabase.
