-- ============================================================
-- DEALBOT - Schema do Supabase
-- Rode no SQL Editor do painel do Supabase
-- ============================================================

-- 1. PRODUTOS (ofertas capturadas pelo bot)
create table if not exists public.produtos (
    id              bigint generated always as identity primary key,
    titulo          text not null,
    preco           numeric(10,2),
    preco_original  numeric(10,2),
    cupom           text,
    link            text,
    foto_url        text,
    categoria       text default 'outros',
    canal_origem    text,
    telegram_msg_id bigint,
    raw_text        text,
    criado_em       timestamptz default now(),
    data_oferta     timestamptz
);

-- Migração para bancos já existentes (idempotente)
alter table public.produtos
    add column if not exists data_oferta timestamptz;
alter table public.produtos
    add column if not exists dedup_hash text;

create unique index if not exists uq_produto_msg
    on public.produtos (canal_origem, telegram_msg_id);
create index if not exists idx_produtos_categoria on public.produtos (categoria);
create index if not exists idx_produtos_criado_em on public.produtos (criado_em desc);
create index if not exists idx_produtos_data_oferta on public.produtos (data_oferta desc);
create index if not exists idx_produtos_dedup_hash
    on public.produtos (dedup_hash, criado_em desc);

-- 1b. APARICOES (cada vez que a mesma promo aparece num canal)
create table if not exists public.produto_aparicoes (
    id              bigint generated always as identity primary key,
    produto_id      bigint not null references public.produtos(id) on delete cascade,
    canal_origem    text not null,
    telegram_msg_id bigint,
    visto_em        timestamptz default now()
);

create unique index if not exists uq_aparicao_canal_msg
    on public.produto_aparicoes (canal_origem, telegram_msg_id);
create index if not exists idx_aparicoes_produto
    on public.produto_aparicoes (produto_id);

-- 2. FILTROS (regras editáveis pela web)
create table if not exists public.filtros (
    id                bigint generated always as identity primary key,
    nome              text not null,
    palavras_chave    text[] default '{}',
    palavras_bloqueio text[] default '{}',
    categoria         text,
    preco_max         numeric(10,2),
    ativo             boolean default true,
    criado_em         timestamptz default now()
);

-- 3. CANAIS monitorados
create table if not exists public.canais (
    id        bigint generated always as identity primary key,
    username  text not null unique,
    ativo     boolean default true,
    criado_em timestamptz default now()
);

-- 4. STATE do bot (modo polling, se usado)
create table if not exists public.bot_state (
    canal_username text primary key,
    last_msg_id    bigint default 0,
    atualizado_em  timestamptz default now()
);

-- 5. RLS — o backend usa a service role (ignora RLS).
--    Estas policies valem se o front falar direto com o Supabase.
alter table public.produtos          enable row level security;
alter table public.produto_aparicoes enable row level security;
alter table public.filtros           enable row level security;
alter table public.canais            enable row level security;
alter table public.bot_state         enable row level security;

-- create policy não aceita "if not exists" antes do Postgres 17.
-- Drop-then-create torna o script idempotente em qualquer versão.
drop policy if exists "auth_read_produtos"  on public.produtos;
drop policy if exists "auth_read_aparicoes" on public.produto_aparicoes;
drop policy if exists "auth_all_filtros"    on public.filtros;
drop policy if exists "auth_all_canais"     on public.canais;

create policy "auth_read_produtos" on public.produtos
    for select using (auth.role() = 'authenticated');
create policy "auth_read_aparicoes" on public.produto_aparicoes
    for select using (auth.role() = 'authenticated');
create policy "auth_all_filtros" on public.filtros
    for all using (auth.role() = 'authenticated')
    with check (auth.role() = 'authenticated');
create policy "auth_all_canais" on public.canais
    for all using (auth.role() = 'authenticated')
    with check (auth.role() = 'authenticated');

-- 6. Bucket de storage para fotos
insert into storage.buckets (id, name, public)
values ('produtos', 'produtos', true)
on conflict (id) do nothing;
