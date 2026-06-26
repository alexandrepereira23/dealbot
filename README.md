# Dealbot

Aplicação web de promoções. Um bot Python captura ofertas de canais do
Telegram, estrutura os dados por regex/heurística e salva no Supabase. Uma API
MVC em Node serve os dados, e um frontend Next.js exibe tudo com login, filtros
por categoria e edição das regras de captura.

```
Telegram → Bot Python (VPS) → Supabase → API MVC (Node) → Next.js (Vercel)
```

## Estrutura

```
dealbot/
├── supabase/schema.sql          # rode no SQL Editor do Supabase
│
├── backend/                     # API REST em camadas (MVC)
│   └── src/
│       ├── config/              # env + clientes Supabase
│       ├── models/              # acesso a dados (produto, filtro, canal)
│       ├── services/            # regras de negócio + validação (Zod)
│       ├── controllers/         # recebem req/res
│       ├── routes/              # rotas + auth aplicada
│       ├── middlewares/         # auth (JWT) e tratamento de erros
│       ├── utils/               # erros HTTP
│       ├── app.js               # monta express
│       └── server.js            # entrypoint
│
├── bot/                         # bot de captura (modo live/persistente)
│   ├── src/
│   │   ├── config.py            # variáveis de ambiente
│   │   ├── db.py                # cliente Supabase
│   │   ├── extractor.py         # estrutura texto via regex/heurística
│   │   ├── filters.py           # aplica as regras cadastradas
│   │   ├── repository.py        # storage de fotos + gravação
│   │   └── main.py              # loop de eventos do Telethon
│   ├── gerar_sessao.py          # gera a session string (rode 1x)
│   └── dealbot.service          # unit do systemd para o VPS
│
└── frontend/                    # Next.js (App Router)
    └── src/
        ├── app/
        │   ├── page.tsx         # dashboard (listagem + stats)
        │   ├── login/page.tsx   # login
        │   └── filtros/page.tsx # CRUD de filtros
        ├── components/          # Header, ProdutoCard, FiltroCategorias
        ├── hooks/useAuth.ts     # proteção de rota
        └── lib/                 # cliente Supabase, cliente da API, tipos
```

## Como a autenticação funciona

1. O usuário loga no frontend via Supabase Auth → recebe um JWT.
2. O frontend manda o JWT no header `Authorization: Bearer` em cada chamada.
3. O middleware `autenticar` do backend valida esse JWT no Supabase.
4. O backend acessa o banco com a `service_role key` (ignora o RLS).

A `service_role key` fica **só no backend e no bot**. A `anon key` fica no
frontend. Nunca troque as duas de lugar.

## Setup

### 1. Supabase
1. Crie um projeto em supabase.com
2. SQL Editor → cole e rode `supabase/schema.sql`
3. Settings → API: copie `URL`, `anon key` e `service_role key`

### 2. Seu usuário (acesso restrito a você)
1. Authentication → Providers → desative "Enable email signups"
2. Authentication → Users → "Add user" → crie seu e-mail e senha

### 3. Bot (no VPS Oracle)
```bash
cd bot
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python gerar_sessao.py          # informe API ID/HASH de my.telegram.org
cp .env.example .env            # preencha as variáveis
python -m src.main              # teste manual

# para rodar como serviço:
sudo cp dealbot.service /etc/systemd/system/
sudo systemctl enable --now dealbot
```
Cadastre os canais a monitorar na tabela `canais` do Supabase.

### 4. Backend
```bash
cd backend
npm install
cp .env.example .env            # preencha as variáveis
npm start                       # sobe na porta 3333
```

### 5. Frontend
```bash
cd frontend
npm install
cp .env.example .env.local      # preencha as variáveis
npm run dev                     # http://localhost:3000
```
Deploy no Vercel: defina as três variáveis `NEXT_PUBLIC_*` no painel.
A `NEXT_PUBLIC_API_URL` deve apontar para a URL pública do backend no VPS.

## Endpoints da API

Todas exigem `Authorization: Bearer <jwt>`, exceto `/health`.

```
GET    /api/health
GET    /api/produtos?categoria=eletronicos
GET    /api/produtos/estatisticas
GET    /api/produtos/:id
DELETE /api/produtos/:id
GET    /api/filtros
POST   /api/filtros
PUT    /api/filtros/:id
DELETE /api/filtros/:id
GET    /api/canais
POST   /api/canais
PUT    /api/canais/:id
DELETE /api/canais/:id
```

## Extração de produtos
O `bot/src/extractor.py` estrutura cada mensagem por regex/heurística (preço,
cupom, link, categoria por palavras-chave). Não há dependência de IA nem chave
externa. As categorias suportadas estão fixas em `extractor.py` e em
`frontend/lib/types.ts` (`CATEGORIAS`) — mantenha as duas em sincronia.
