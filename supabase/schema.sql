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

-- Unicidade textual legada e numérica são instaladas juntas no bloco etapa 3.
-- Não recriar aqui o índice global antigo: reaplicação pode conter usernames
-- reutilizados legítimos entre canais numéricos distintos.
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

-- Ver índices de evento/compatibilidade legada no bloco etapa 3 abaixo.
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

-- ETAPA 2 FILTROS: início do bloco aditivo/idempotente.
-- Aplicar primeiro; depois bot/backend compatíveis e, por último, frontend.
-- Falha no preflight aborta o bloco inteiro. Não limpa/reinterpreta dados legados.
do $etapa2_filtros$
begin
    alter table public.filtros
        add column if not exists tipo_regra text not null default 'interesse',
        add column if not exists modo_palavras text not null default 'qualquer';

    if exists (
        select 1 from public.filtros
        where tipo_regra is null or tipo_regra not in ('interesse', 'bloqueio_global')
           or modo_palavras is null or modo_palavras not in ('qualquer', 'todas')
           or (tipo_regra = 'bloqueio_global' and (
               coalesce(cardinality(palavras_bloqueio), 0) = 0
               or palavras_chave is distinct from '{}'::text[]
               or categoria is not null or preco_max is not null
           ))
    ) then
        raise exception 'Etapa 2: filtros incompatíveis; migração interrompida sem alterar regras'
            using hint = 'Inspecione tipos/modos e inclusões de bloqueios globais; corrija somente com autorização e execute novamente.';
    end if;

    alter table public.filtros
        alter column tipo_regra set default 'interesse',
        alter column tipo_regra set not null,
        alter column modo_palavras set default 'qualquer',
        alter column modo_palavras set not null;

    if not exists (select 1 from pg_constraint
                   where conrelid = 'public.filtros'::regclass and conname = 'filtros_tipo_regra_check') then
        alter table public.filtros add constraint filtros_tipo_regra_check
            check (tipo_regra in ('interesse', 'bloqueio_global'));
    end if;
    if not exists (select 1 from pg_constraint
                   where conrelid = 'public.filtros'::regclass and conname = 'filtros_modo_palavras_check') then
        alter table public.filtros add constraint filtros_modo_palavras_check
            check (modo_palavras in ('qualquer', 'todas'));
    end if;
    if not exists (select 1 from pg_constraint
                   where conrelid = 'public.filtros'::regclass and conname = 'filtros_global_consistente_check') then
        alter table public.filtros add constraint filtros_global_consistente_check
            check (tipo_regra <> 'bloqueio_global' or (
                coalesce(cardinality(palavras_bloqueio), 0) > 0
                and palavras_chave is not null and palavras_chave = '{}'::text[]
                and categoria is null and preco_max is null
            ));
    end if;
end
$etapa2_filtros$;
-- ETAPA 2 FILTROS: fim. Rollback preserva colunas/dados; código antigo não entende globais/todas.

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

-- ETAPA 3 OFERTAS: início do bloco aditivo/idempotente.
-- Aplicação futura: parar bot/limpador antigos, aplicar este bloco e só então
-- habilitar escritores compatíveis. Nunca executar remotamente sem autorização.
-- Um único advisory lock transacional (730030003) serializa TODOS os efeitos
-- destas RPCs, inclusive limpeza/foto. Custo: uma transação de escrita por vez;
-- não há rede/Storage dentro da transação. Escrita direta legada não participa.
-- Não há backfill de confiança, índice temporal volátil ou mudança de policies.
-- Pins não têm TTL: confirmar SOMENTE após jobs locais de mídia/enriquecimento
-- e suas compensações estarem duravelmente terminais. Sem ack, não há purga.
-- Depois da purga não se promete idempotência eterna de replay arbitrário.
do $etapa3_ofertas$
declare v_funcao regprocedure; v_coluna record; v_indice text;
begin
    perform pg_advisory_xact_lock(730030003::bigint);
    if to_regclass('public.produtos') is null
       or to_regclass('public.produto_aparicoes') is null
       or not exists (select 1 from pg_roles where rolname = 'service_role')
       or not exists (select 1 from pg_roles where rolname = 'anon')
       or not exists (select 1 from pg_roles where rolname = 'authenticated') then
        raise exception 'Etapa 3: schema/papéis base ausentes; migração interrompida';
    end if;

    alter table public.produtos
        add column if not exists canal_id bigint,
        add column if not exists identidade_versao integer,
        add column if not exists identidade_chave text,
        add column if not exists identidade_dados jsonb,
        add column if not exists estado_oferta text not null default 'ativa',
        add column if not exists canonico_id bigint references public.produtos(id),
        add column if not exists inicio_em timestamptz,
        add column if not exists ultima_aparicao_em timestamptz,
        add column if not exists expira_em timestamptz,
        add column if not exists janela_horas numeric,
        add column if not exists preco_observado_em timestamptz,
        add column if not exists preco_canal_id bigint,
        add column if not exists preco_msg_id bigint,
        add column if not exists preco_anterior_atualizacao numeric,
        add column if not exists atualizado_em timestamptz,
        add column if not exists terminal_em timestamptz;
    -- Preflight também rejeita instalação parcial com tipos incompatíveis.
    for v_coluna in select * from (values
        ('canal_id','bigint'),
        ('identidade_versao','integer'), ('identidade_chave','text'),
        ('identidade_dados','jsonb'), ('estado_oferta','text'), ('canonico_id','bigint'),
        ('inicio_em','timestamp with time zone'), ('ultima_aparicao_em','timestamp with time zone'),
        ('expira_em','timestamp with time zone'), ('janela_horas','numeric'),
        ('preco_observado_em','timestamp with time zone'), ('preco_canal_id','bigint'),
        ('preco_msg_id','bigint'), ('preco_anterior_atualizacao','numeric'),
        ('atualizado_em','timestamp with time zone'), ('terminal_em','timestamp with time zone')
    ) as esperado(nome,tipo) loop
        if not exists (select 1 from pg_attribute where attrelid = 'public.produtos'::regclass
            and attname = v_coluna.nome and not attisdropped
            and format_type(atttypid,atttypmod) = v_coluna.tipo) then
            raise exception 'Etapa 3: coluna incompatível: %', v_coluna.nome;
        end if;
    end loop;
    if exists (select 1 from public.produtos where estado_oferta is null
        or estado_oferta not in ('ativa','fundida','removida','expirada')
        or (identidade_versao is not null and identidade_versao <> 2)) then
        raise exception 'Etapa 3: dados incompatíveis; migração interrompida';
    end if;
    alter table public.produtos alter column estado_oferta set default 'ativa',
        alter column estado_oferta set not null;
    if not exists (select 1 from pg_constraint where conrelid = 'public.produtos'::regclass
        and conname = 'produtos_etapa3_check') then
        alter table public.produtos add constraint produtos_etapa3_check check (
            estado_oferta in ('ativa','fundida','removida','expirada')
            and (identidade_versao is null or identidade_versao = 2)
            and ((estado_oferta = 'fundida' and canonico_id is not null and canonico_id < id)
                or (estado_oferta <> 'fundida' and canonico_id is null))
            and (janela_horas is null or (janela_horas > 0 and janela_horas < 'Infinity'::numeric))
        );
    end if;
    alter table public.produto_aparicoes
        add column if not exists canal_id bigint,
        add column if not exists data_origem timestamptz,
        add column if not exists recebido_em timestamptz;
    if not exists(select 1 from pg_attribute where attrelid='public.produto_aparicoes'::regclass
        and attname='canal_id' and not attisdropped and atttypid='bigint'::regtype) then
        raise exception 'Etapa 3: coluna incompatível: produto_aparicoes.canal_id';
    end if;

    execute $ddl$
    create or replace function public._oferta_verificar_indices(p_transicao boolean default false)
    returns void language plpgsql security invoker set search_path=pg_catalog,public as $fn$
    declare v record; v_oid regclass; v_predicado text;
    begin
        for v in select * from (values
            ('produtos','uq_produto_msg','canal_origem','(canal_id IS NULL)',true),
            ('produto_aparicoes','uq_aparicao_canal_msg','canal_origem','(canal_id IS NULL)',true),
            ('produtos','uq_produto_evento_etapa3','canal_id','(canal_id IS NOT NULL)',false),
            ('produto_aparicoes','uq_aparicao_evento_etapa3','canal_id','(canal_id IS NOT NULL)',false)
        ) as esperado(tabela,nome,coluna,predicado,legado) loop
            v_oid := to_regclass(format('public.%I',v.nome));
            if v_oid is null then
                if p_transicao then continue; end if;
                raise exception 'Etapa 3: índice incompatível: %',v.nome;
            end if;
            if not exists(select 1 from pg_index i join pg_class c on c.oid=i.indexrelid
                join pg_am am on am.oid=c.relam where i.indexrelid=v_oid
                and i.indrelid=to_regclass(format('public.%I',v.tabela))
                and i.indisunique and i.indisvalid and i.indisready and not i.indnullsnotdistinct
                and i.indnkeyatts=2 and i.indnatts=2 and i.indexprs is null and am.amname='btree'
                and pg_get_indexdef(i.indexrelid,1,false)=v.coluna
                and pg_get_indexdef(i.indexrelid,2,false)='telegram_msg_id'
                and not exists(select 1 from pg_constraint k where k.conindid=i.indexrelid)) then
                raise exception 'Etapa 3: índice incompatível: %',v.nome;
            end if;
            select pg_get_expr(i.indpred,i.indrelid) into v_predicado from pg_index i where i.indexrelid=v_oid;
            if v_predicado is distinct from v.predicado
                and not (p_transicao and v.legado and v_predicado is null) then
                raise exception 'Etapa 3: índice incompatível: %',v.nome;
            end if;
        end loop;
    end $fn$ $ddl$;
    -- Validar ANTES de substituir apenas os índices globais conhecidos. DDL e
    -- criação dos novos índices são atômicos; duplicidade/tipo inesperado aborta,
    -- sem CASCADE, sem apagar linhas e sem atribuir canal numérico ao histórico.
    perform public._oferta_verificar_indices(true);
    foreach v_indice in array array['uq_produto_msg','uq_aparicao_canal_msg'] loop
        if exists(select 1 from pg_index i where i.indexrelid=to_regclass(format('public.%I',v_indice))
            and i.indpred is null) then
            execute format('drop index public.%I',v_indice);
        end if;
    end loop;
    create unique index if not exists uq_produto_msg
        on public.produtos(canal_origem,telegram_msg_id) where canal_id is null;
    create unique index if not exists uq_aparicao_canal_msg
        on public.produto_aparicoes(canal_origem,telegram_msg_id) where canal_id is null;
    create unique index if not exists uq_produto_evento_etapa3
        on public.produtos(canal_id,telegram_msg_id) where canal_id is not null;
    create unique index if not exists uq_aparicao_evento_etapa3
        on public.produto_aparicoes(canal_id,telegram_msg_id) where canal_id is not null;
    perform public._oferta_verificar_indices();
    create index if not exists idx_oferta_identidade_etapa3
        on public.produtos(identidade_chave,inicio_em,expira_em) where identidade_versao = 2;
    -- Assinatura de cópia não atribui equivalência comercial ao legado.
    create index if not exists idx_produtos_copia_etapa3
        on public.produtos((identidade_dados->'copia'->>'chave'))
        where identidade_versao=2 and canonico_id is null;
    create index if not exists idx_oferta_alias_etapa3 on public.produtos(canonico_id)
        where canonico_id is not null;
    create index if not exists idx_oferta_expiracao_etapa3 on public.produtos(estado_oferta,expira_em);

    -- Uma observação por evento; decisão inicial e enriquecimento independentes.
    -- FK sem CASCADE: apagar card não pode apagar trabalho recuperável.
    create table if not exists public.oferta_eventos (
        canal_id bigint not null, msg_id bigint not null check (msg_id > 0),
        produto_id bigint not null references public.produtos(id),
        decisao_hash text not null, identidade_inicial jsonb,
        identidade_enriquecida jsonb, observacao jsonb,
        data_origem timestamptz, recebido_em timestamptz not null,
        motivo_data text, pin boolean not null default true,
        confirmado_em timestamptz, criado_em timestamptz not null default now(),
        primary key(canal_id,msg_id),
        check ((pin and confirmado_em is null) or (not pin and confirmado_em is not null))
    );
    alter table public.oferta_eventos add column if not exists resultado_inicial text;
    create index if not exists idx_oferta_eventos_produto on public.oferta_eventos(produto_id);
    create index if not exists idx_oferta_eventos_pin on public.oferta_eventos(criado_em) where pin;
    -- A própria foto_url do card é a referência. A reserva é um tombstone que
    -- proíbe novos vínculos, inclusive depois do DELETE no Storage confirmado.
    create table if not exists public.oferta_midias (
        url text primary key, estado text not null check (estado in ('reservada','removida')),
        pedido_em timestamptz not null default now(), confirmado_em timestamptz
    );
    create table if not exists public.oferta_controle (
        id integer primary key check (id=1), legado_pronto boolean not null default false
    );
    insert into public.oferta_controle(id) values(1) on conflict do nothing;
    alter table public.oferta_eventos enable row level security;
    alter table public.oferta_midias enable row level security;
    alter table public.oferta_controle enable row level security;
    revoke all on public.oferta_eventos,public.oferta_midias from public,anon,authenticated;
    revoke all on public.oferta_controle from public,anon,authenticated;
    grant select,update on public.oferta_controle to service_role;
    grant select,insert,update,delete on public.oferta_eventos,public.oferta_midias to service_role;
    -- Supabase já concede estes privilégios; explicitar o mínimo usado pelo invoker.
    grant select,insert,update,delete on public.produtos,public.produto_aparicoes to service_role;
    grant usage,select on sequence public.produtos_id_seq,public.produto_aparicoes_id_seq to service_role;

    execute $ddl$
    create or replace function public._oferta_validar_identidade(p_identidade jsonb)
    returns void language plpgsql security invoker set search_path = pg_catalog,public as $fn$
    begin
        if jsonb_typeof(p_identidade) is distinct from 'object'
           or p_identidade->'versao' is distinct from '2'::jsonb
           or not (p_identidade ?& array['chave','componentes','motivo','url_identidade'])
           or jsonb_typeof(p_identidade->'componentes') is distinct from 'object'
           or jsonb_typeof(p_identidade->'chave') not in ('string','null')
           or jsonb_typeof(p_identidade->'motivo') is distinct from 'string'
           or jsonb_typeof(p_identidade->'url_identidade') not in ('string','null')
           or (p_identidade->>'chave' is not null and (
                p_identidade->>'chave' !~ '^[0-9a-f]{64}$'
                or p_identidade->'componentes'->>'confianca' is distinct from 'forte'
                or jsonb_typeof(p_identidade->'componentes'->'comparacao') is distinct from 'object'
                or not (p_identidade->'componentes'->'comparacao' ?& array['regra','campos','url'])
                or jsonb_typeof(p_identidade->'componentes'->'comparacao'->'campos') is distinct from 'object'
                or jsonb_typeof(p_identidade->'componentes'->'comparacao'->'url') is distinct from 'object'
                or p_identidade->'componentes'->'comparacao'->'regra'
                    is distinct from p_identidade->'componentes'->'regra'
                or p_identidade->'componentes'->'comparacao'->'campos'
                    is distinct from p_identidade->'componentes'->'campos'
                or p_identidade->'componentes'->'conflitos' is distinct from '[]'::jsonb
                or p_identidade->'componentes'->'incertezas' is distinct from '[]'::jsonb
                or p_identidade->'componentes'->'desconhecidos' is distinct from '[]'::jsonb)) then
            raise exception 'Etapa 3: identidade inválida' using errcode = '22023';
        end if;
        -- Confiança/completude são produzidas pelo extrator versionado, não
        -- inferidas de título/URL/preço aqui. Hash sozinho nunca basta: comparar
        -- TODO componentes.comparacao (regra/campos/url). Proveniência/URLs
        -- originais externas à comparação podem divergir sem diferença comercial.
        if p_identidade ? 'copia' and p_identidade->'copia' <> 'null'::jsonb then
            if jsonb_typeof(p_identidade->'copia') is distinct from 'object'
                or p_identidade->'copia'->'versao' is distinct from '1'::jsonb
                or coalesce(p_identidade->'copia'->>'chave','') !~ '^[0-9a-f]{64}$'
                or jsonb_typeof(p_identidade->'copia'->'comparacao') is distinct from 'object'
                or not (p_identidade->'copia'->'comparacao' ?& array['destino','conteudo','preco_centavos'])
                or jsonb_typeof(p_identidade->'copia'->'comparacao'->'conteudo') is distinct from 'string'
                or coalesce(p_identidade->'copia'->'comparacao'->>'preco_centavos','') !~ '^[0-9]+$' then
                raise exception 'Etapa 3: assinatura de cópia inválida' using errcode='22023';
            end if;
        end if;
    end $fn$ $ddl$;

    execute $ddl$
    create or replace function public._oferta_equivalentes(p_a jsonb,p_b jsonb)
    returns boolean language sql immutable security invoker set search_path=pg_catalog,public as $fn$
        select coalesce(
            (p_a->>'chave' is not null and p_b->>'chave' is not null
                and p_a->>'chave'=p_b->>'chave'
                and p_a->'componentes'->'comparacao'=p_b->'componentes'->'comparacao')
            or (p_a->>'chave' is null and p_b->>'chave' is null
                and p_a->'copia'->>'chave' is not null
                and p_a->'copia'->>'chave'=p_b->'copia'->>'chave'
                and p_a->'copia'->'comparacao'=p_b->'copia'->'comparacao'),false);
        -- Cópias nunca ligam forte↔fraca ou fortes incompatíveis. Promover
        -- evidência forte não permite apagá-la com enriquecimento de cópia.
    $fn$ $ddl$;

    execute $ddl$
    create or replace function public._oferta_canonico(p_id bigint)
    returns bigint language plpgsql security invoker set search_path = pg_catalog,public as $fn$
    declare v_id bigint := p_id; v_proximo bigint;
    begin
        for i in 1..32 loop
            select p.canonico_id into v_proximo from public.produtos p where p.id = v_id;
            if not found then return null; end if;
            if v_proximo is null then return v_id; end if;
            if v_proximo >= v_id then raise exception 'Etapa 3: alias inválido'; end if;
            v_id := v_proximo;
        end loop;
        raise exception 'Etapa 3: limite de aliases excedido';
    end $fn$ $ddl$;

    execute $ddl$
    create or replace function public._oferta_resumir(p_id bigint)
    returns void language plpgsql security invoker set search_path = pg_catalog,public as $fn$
    declare v_evento public.oferta_eventos%rowtype; v_preco_anterior numeric;
        v_produto public.produtos%rowtype;
    begin
        perform pg_advisory_xact_lock(730030003::bigint);
        select p.* into strict v_produto from public.produtos p where p.id = p_id;
        select e.* into v_evento from public.oferta_eventos e
            where e.produto_id = p_id and e.data_origem is not null
                and e.motivo_data is null and e.observacao is not null
            order by e.data_origem desc,e.canal_id desc,e.msg_id desc limit 1;
        if not found then return; end if;
        if (v_produto.preco_observado_em,v_produto.preco_canal_id,v_produto.preco_msg_id)
            is not distinct from (v_evento.data_origem,v_evento.canal_id,v_evento.msg_id) then return; end if;
        select (e.observacao->>'preco')::numeric into v_preco_anterior
            from public.oferta_eventos e where e.produto_id = p_id and e.motivo_data is null
                and e.data_origem is not null and e.observacao is not null
                and (e.data_origem,e.canal_id,e.msg_id)
                    < (v_evento.data_origem,v_evento.canal_id,v_evento.msg_id)
            order by e.data_origem desc,e.canal_id desc,e.msg_id desc limit 1;
        update public.produtos set
            titulo = coalesce(nullif(v_evento.observacao->>'titulo',''),titulo),
            preco = (v_evento.observacao->>'preco')::numeric,
            preco_original = (v_evento.observacao->>'preco_original')::numeric,
            preco_anterior_atualizacao = case
                when v_evento.observacao->>'preco' is not null
                    and v_preco_anterior is distinct from (v_evento.observacao->>'preco')::numeric
                then v_preco_anterior else null end,
            cupom = coalesce(v_evento.observacao->>'cupom',cupom),
            link = coalesce(v_evento.observacao->>'link',link),
            categoria = coalesce(v_evento.observacao->>'categoria',categoria),
            raw_text = coalesce(left(v_evento.observacao->>'raw_text',2000),raw_text),
            preco_observado_em = v_evento.data_origem,
            preco_canal_id = v_evento.canal_id, preco_msg_id = v_evento.msg_id,
            data_oferta = v_evento.data_origem,
            atualizado_em = case when v_produto.preco_observado_em is not null
                then clock_timestamp() else null end
        where public.produtos.id = p_id;
    end $fn$ $ddl$;

    execute $ddl$
    create or replace function public.oferta_registrar(p_evento jsonb,p_produto jsonb,
        p_identidade jsonb,p_janela_horas numeric default 48)
    returns table(id bigint,status text,foto_url text)
    language plpgsql security invoker set search_path = pg_catalog,public as $fn$
    declare v_canal bigint; v_msg bigint; v_recebido timestamptz; v_data timestamptz;
        v_motivo text; v_hash text; v_observacao jsonb; v_id bigint;
        v_evento public.oferta_eventos%rowtype; v_card public.produtos%rowtype;
        v_status text := 'novo'; v_vencedor boolean; v_campo text;
    begin
        perform pg_advisory_xact_lock(730030003::bigint);
        perform public._oferta_validar_identidade(p_identidade);
        if p_janela_horas is null or not (p_janela_horas > 0 and p_janela_horas < 'Infinity'::numeric)
            or jsonb_typeof(p_evento) is distinct from 'object'
            or jsonb_typeof(p_produto) is distinct from 'object'
            or jsonb_typeof(p_evento->'canal_id') is distinct from 'number'
            or jsonb_typeof(p_evento->'msg_id') is distinct from 'number'
            or (p_evento->>'canal_id') !~ '^-?[0-9]+$'
            or (p_evento->>'msg_id') !~ '^[0-9]+$'
            or jsonb_typeof(p_evento->'tem_foto') is distinct from 'boolean'
            or jsonb_typeof(p_evento->'enriquecer') is distinct from 'boolean'
            or nullif(p_evento->>'canal_origem','') is null
            or nullif(p_produto->>'titulo','') is null then
            raise exception 'Etapa 3: evento/produto/janela inválidos' using errcode = '22023';
        end if;
        v_canal := (p_evento->>'canal_id')::bigint;
        v_msg := (p_evento->>'msg_id')::bigint;
        if v_canal = 0 or v_msg <= 0 then
            raise exception 'Etapa 3: identificador de evento inválido' using errcode = '22023';
        end if;
        foreach v_campo in array array['preco','preco_original'] loop
            if p_produto ? v_campo and (jsonb_typeof(p_produto->v_campo) not in ('number','null')
                or (p_produto->>v_campo)::numeric < 0
                or (p_produto->>v_campo)::numeric <> round((p_produto->>v_campo)::numeric,2)) then
                raise exception 'Etapa 3: preço inválido' using errcode = '22023';
            end if;
        end loop;
        if p_identidade->'copia'->>'chave' is not null and (
            p_produto->>'preco' is null or
            (p_identidade->'copia'->'comparacao'->>'preco_centavos')::numeric
                is distinct from (p_produto->>'preco')::numeric*100) then
            raise exception 'Etapa 3: preço incompatível com assinatura de cópia' using errcode='22023';
        end if;
        if coalesce(p_evento->>'recebido_em','') !~
            '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]{1,6})?(Z|[+]00:00)$' then
            raise exception 'Etapa 3: recepção exige ISO UTC' using errcode = '22023';
        end if;
        v_recebido := (p_evento->>'recebido_em')::timestamptz;
        if v_recebido is null or not isfinite(v_recebido) then
            raise exception 'Etapa 3: recepção inválida' using errcode = '22023';
        end if;
        begin
            if coalesce(p_evento->>'data_origem','') ~
                '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]{1,6})?(Z|[+]00:00)$' then
                v_data := (p_evento->>'data_origem')::timestamptz;
            end if;
        exception when invalid_datetime_format or datetime_field_overflow then
            v_data := null;
        end;
        if v_data is null or not isfinite(v_data) then
            v_data := null; v_motivo := 'data_ausente_invalida';
        elsif v_data > v_recebido or v_data > clock_timestamp() then
            v_motivo := 'data_futura';
        end if;
        -- Whitelist pública atual. Nenhum campo interno de p_produto é gravado.
        select coalesce(jsonb_object_agg(k,v),'{}'::jsonb) into v_observacao
            from jsonb_each(p_produto) as x(k,v)
            where k = any(array['titulo','preco','preco_original','cupom','link','categoria','raw_text']);
        v_observacao := jsonb_set(v_observacao,'{raw_text}',
            coalesce(to_jsonb(left(v_observacao->>'raw_text',2000)),'null'::jsonb));
        -- Username/recepção podem mudar no retry; decisão e data original não.
        v_hash := encode(sha256(convert_to(jsonb_build_object('produto',v_observacao,
            'identidade',p_identidade,'data_origem',p_evento->'data_origem',
            'tem_foto',p_evento->'tem_foto','enriquecer',p_evento->'enriquecer')::text,'UTF8')),'hex');
        select e.* into v_evento from public.oferta_eventos e
            where e.canal_id = v_canal and e.msg_id = v_msg;
        if found then
            v_id := public._oferta_canonico(v_evento.produto_id);
            select p.* into strict v_card from public.produtos p where p.id = v_id;
            return query select v_id,case
                when v_card.estado_oferta = 'removida' then 'removido'
                 when v_evento.decisao_hash <> v_hash then 'conflito'
                 when v_evento.resultado_inicial in ('reutilizado','atualizado','duplicado') then 'duplicado'
                 else 'retomado' end,v_card.foto_url;
            return;
        end if;
        if (p_identidade->>'chave' is not null or p_identidade->'copia'->>'chave' is not null)
            and v_motivo is null then
            select p.* into v_card from public.produtos p
                where p.identidade_versao = 2
                    and ((p_identidade->>'chave' is not null and p.identidade_chave=p_identidade->>'chave')
                        or (p_identidade->>'chave' is null and p.identidade_chave is null
                            and p.identidade_dados->'copia'->>'chave'=p_identidade->'copia'->>'chave'))
                    and public._oferta_equivalentes(p.identidade_dados,p_identidade)
                    and (p_identidade->>'chave' is not null or p.preco*100=
                        (p_identidade->'copia'->'comparacao'->>'preco_centavos')::numeric)
                    and p.estado_oferta in ('ativa','expirada','removida') and p.canonico_id is null
                    and (v_data >= p.inicio_em or (p.estado_oferta = 'ativa'
                        and p.expira_em >= clock_timestamp()
                        and v_data >= p.ultima_aparicao_em - p.janela_horas * interval '1 hour'
                        -- Não estender início para trás cruzando uma instância
                        -- anterior conhecida; incerteza histórica fica separada.
                        and not exists (select 1 from public.produtos anterior
                            where anterior.identidade_versao = 2
                                and ((p.identidade_chave is not null and anterior.identidade_chave=p.identidade_chave)
                                    or (p.identidade_chave is null and anterior.identidade_chave is null
                                        and anterior.identidade_dados->'copia'->>'chave'=p.identidade_dados->'copia'->>'chave'))
                                and public._oferta_equivalentes(anterior.identidade_dados,p.identidade_dados)
                                and anterior.canonico_id is null and anterior.inicio_em < p.inicio_em)))
                    and v_data <= p.expira_em
                -- Contenção temporal comprovada precede extensão retroativa.
                order by case when v_data >= p.inicio_em then 0 else 1 end,p.id limit 1;
            v_id := v_card.id;
        end if;
        if v_id is null then
            insert into public.produtos(titulo,preco,preco_original,cupom,link,categoria,raw_text,
                canal_origem,telegram_msg_id,canal_id,identidade_versao,identidade_chave,identidade_dados,
                inicio_em,ultima_aparicao_em,expira_em,janela_horas,estado_oferta,terminal_em)
            values(p_produto->>'titulo',(p_produto->>'preco')::numeric,
                (p_produto->>'preco_original')::numeric,p_produto->>'cupom',p_produto->>'link',
                coalesce(p_produto->>'categoria','outros'),left(p_produto->>'raw_text',2000),
                p_evento->>'canal_origem',v_msg,v_canal,2,p_identidade->>'chave',p_identidade,
                case when v_motivo is null then v_data end,
                case when v_motivo is null then v_data end,
                case when v_motivo is null then v_data + p_janela_horas * interval '1 hour' end,
                p_janela_horas,case when v_motivo is null and
                    v_data + p_janela_horas * interval '1 hour' > clock_timestamp()
                    then 'ativa' else 'expirada' end,
                case when v_motivo is not null or
                    v_data + p_janela_horas * interval '1 hour' <= clock_timestamp()
                    then clock_timestamp() end)
            returning public.produtos.id into v_id;
        else
            v_vencedor := (v_data,v_canal,v_msg) >
                (v_card.preco_observado_em,v_card.preco_canal_id,v_card.preco_msg_id);
            v_status := case when v_card.estado_oferta = 'removida' then 'removido'
                when coalesce(v_vencedor,false) then 'atualizado' else 'reutilizado' end;
            -- Uma observação válida ainda dentro da janela temporal da instância
            -- pode estendê-la até o presente, mesmo se histórico/limpeza já a
            -- marcaram expirada. Não reabrir remoção manual, atravessar lacuna,
            -- nem competir com uma instância posterior conhecida. Retry sai antes.
            if v_card.estado_oferta in ('ativa','expirada')
                and v_data > v_card.ultima_aparicao_em
                and v_data + v_card.janela_horas * interval '1 hour' > clock_timestamp()
                and not exists(select 1 from public.produtos posterior
                    where posterior.identidade_versao=2 and posterior.canonico_id is null
                        and posterior.id<>v_id and posterior.inicio_em>v_card.inicio_em
                        and ((p_identidade->>'chave' is not null and posterior.identidade_chave=p_identidade->>'chave')
                            or (p_identidade->>'chave' is null and posterior.identidade_chave is null
                                and posterior.identidade_dados->'copia'->>'chave'=p_identidade->'copia'->>'chave'))
                        and public._oferta_equivalentes(posterior.identidade_dados,p_identidade)) then
                update public.produtos set estado_oferta='ativa',terminal_em=null,
                    ultima_aparicao_em=v_data,expira_em=v_data+janela_horas*interval '1 hour'
                    where public.produtos.id=v_id;
            end if;
            if v_card.estado_oferta = 'ativa'
                and v_card.expira_em >= clock_timestamp() then
                update public.produtos set inicio_em = least(inicio_em,v_data)
                    where public.produtos.id = v_id;
            end if;
            -- Histórico contido em instância fechada registra observação, não
            -- reabre a validade nem atravessa a lacuna para uma instância nova.
            if v_card.estado_oferta = 'ativa' and v_data > v_card.ultima_aparicao_em
                and v_card.expira_em >= clock_timestamp() then
                update public.produtos set ultima_aparicao_em = v_data,
                    expira_em = v_data + janela_horas * interval '1 hour' where public.produtos.id = v_id;
            end if;
        end if;
        insert into public.oferta_eventos(canal_id,msg_id,produto_id,decisao_hash,identidade_inicial,
            observacao,data_origem,recebido_em,motivo_data,resultado_inicial)
            values(v_canal,v_msg,v_id,v_hash,p_identidade,v_observacao,v_data,v_recebido,v_motivo,v_status);
        insert into public.produto_aparicoes(produto_id,canal_origem,telegram_msg_id,canal_id,
            data_origem,recebido_em,visto_em)
            values(v_id,p_evento->>'canal_origem',v_msg,v_canal,v_data,v_recebido,v_recebido);
        if v_status <> 'removido' then perform public._oferta_resumir(v_id); end if;
        -- Foto inicial só passa pelo mesmo protocolo atômico usado pelos jobs.
        if nullif(p_produto->>'foto_url','') is not null then
            perform public.oferta_foto(v_id,p_produto->>'foto_url');
        end if;
        return query select p.id,v_status,p.foto_url from public.produtos p where p.id = v_id;
    end $fn$ $ddl$;

    execute $ddl$
    create or replace function public.oferta_legado_registrar(p_evento jsonb,p_produto jsonb,p_hash text)
    returns table(id bigint,status text,foto_url text)
    language plpgsql security invoker set search_path = pg_catalog,public as $fn$
    declare v_canal bigint; v_msg bigint; v_id bigint; v_ids bigint[]; v_aliases text[];
        v_origens bigint[]; v_aparicoes bigint[]; v_aparicao bigint; v_ap_produto bigint;
        v_card public.produtos%rowtype; v_evento public.oferta_eventos%rowtype;
        v_decisao text; v_status text := 'novo';
    begin
        perform pg_advisory_xact_lock(730030003::bigint);
        if p_hash is null or p_hash !~ '^[0-9a-f]{32}$'
            or nullif(p_produto->>'titulo','') is null
            or jsonb_typeof(p_evento->'aliases') is distinct from 'array' then
            raise exception 'Etapa 3: decisão legada inválida' using errcode='22023';
        end if;
        v_canal := (p_evento->>'canal_id')::bigint; v_msg := (p_evento->>'msg_id')::bigint;
        if v_canal is null or v_canal=0 or v_msg is null or v_msg<=0 then
            raise exception 'Etapa 3: evento legado inválido' using errcode='22023';
        end if;
        v_decisao := encode(sha256(convert_to(jsonb_build_object('produto',p_produto,
            'hash_legado',p_hash,'data_origem',p_evento->'data_origem')::text,'UTF8')),'hex');
        select * into v_evento from public.oferta_eventos e where e.canal_id=v_canal and e.msg_id=v_msg;
        if found then
            v_id := public._oferta_canonico(v_evento.produto_id);
            select * into strict v_card from public.produtos p where p.id=v_id;
            return query select v_id,case when v_card.estado_oferta='removida' then 'removido'
                when v_evento.decisao_hash<>v_decisao then 'conflito'
                when v_evento.resultado_inicial='duplicado' then 'duplicado' else 'retomado' end,v_card.foto_url;
            return;
        end if;
        select array_agg(lower(ltrim(x,'@'))) into v_aliases
            from jsonb_array_elements_text(p_evento->'aliases') x;
        -- Texto é somente compatibilidade de evidência legada ainda sem dono.
        -- Uma aparição numerada de outro canal não pode ser adotada por alias.
        -- Mapas retidos também protegem a origem quando a coluna antiga é null.
        -- Outro nome pode ser renomeação do dono original, não prova de que o
        -- texto ficou disponível: na dúvida não atribuir posse por alias.
        -- Checkpoint explícito e par numérico continuam sendo prova independente.
        with origens as (
            select p.id as produto_id,p.canal_id,p.telegram_msg_id,
                lower(ltrim(p.canal_origem,'@')) as nome,'produto' as tipo,p.id as linha_id
                from public.produtos p where p.identidade_versao is null
            union all
            select a.produto_id,a.canal_id,a.telegram_msg_id,
                lower(ltrim(a.canal_origem,'@')),'aparicao',a.id
                from public.produto_aparicoes a join public.produtos p on p.id=a.produto_id
                where p.identidade_versao is null
        ), candidatas as (
            select o.*,public._oferta_canonico(o.produto_id) as canonico from origens o
            where o.telegram_msg_id=v_msg and (o.canal_id=v_canal or (
                o.canal_id is null and o.nome=any(v_aliases)
                and not exists(select 1 from origens n
                    where public._oferta_canonico(n.produto_id)=public._oferta_canonico(o.produto_id)
                    and n.telegram_msg_id=o.telegram_msg_id and n.nome=o.nome and n.canal_id<>v_canal)
                and not exists(select 1 from public.oferta_eventos e
                    where public._oferta_canonico(e.produto_id)=public._oferta_canonico(o.produto_id)
                        and e.msg_id=o.telegram_msg_id and e.canal_id<>v_canal)
            ))
        )
        select array_agg(distinct c.canonico),
            array_agg(distinct c.produto_id) filter(where c.tipo='produto'),
            array_agg(c.linha_id) filter(where c.tipo='aparicao')
            into v_ids,v_origens,v_aparicoes from candidatas c;
        if coalesce(cardinality(v_ids),0)>1 then raise exception 'Etapa 3: vínculo legado conflitante'; end if;
        v_id := v_ids[1];
        if p_evento->>'produto_id' is not null then
            if v_id is not null and public._oferta_canonico(v_id)<>public._oferta_canonico((p_evento->>'produto_id')::bigint) then
                raise exception 'Etapa 3: checkpoint legado conflitante';
            end if;
            v_id := public._oferta_canonico((p_evento->>'produto_id')::bigint);
            if v_id is null then raise exception 'Etapa 3: checkpoint legado removido; preservar para diagnóstico'; end if;
        end if;
        if v_id is null then
            select p.id into v_id from public.produtos p where p.identidade_versao is null
                and p.estado_oferta='ativa' and p.dedup_hash=p_hash and p.criado_em>=clock_timestamp()-interval '48 hours'
                order by p.criado_em desc,p.id limit 1;
        end if;
        if v_id is null then
            insert into public.produtos(titulo,preco,preco_original,cupom,link,categoria,raw_text,
                canal_origem,telegram_msg_id,canal_id,data_oferta,dedup_hash)
            values(p_produto->>'titulo',(p_produto->>'preco')::numeric,(p_produto->>'preco_original')::numeric,
                p_produto->>'cupom',p_produto->>'link',coalesce(p_produto->>'categoria','outros'),
                left(p_produto->>'raw_text',2000),p_evento->>'canal_origem',v_msg,v_canal,
                (p_evento->>'data_origem')::timestamptz,p_hash) returning public.produtos.id into v_id;
        else
            v_id := public._oferta_canonico(v_id);
            select * into strict v_card from public.produtos p where p.id=v_id;
            if v_card.identidade_versao is not null then
                raise exception 'Etapa 3: checkpoint legado incompatível com oferta versionada';
            end if;
            if v_card.canal_id is null and v_id=any(v_origens) then
                -- Claim pontual do próprio evento reconciliado; não é backfill.
                update public.produtos set canal_id=v_canal where public.produtos.id=v_id;
                v_card.canal_id := v_canal;
            end if;
            v_status := case when v_card.estado_oferta='removida' then 'removido'
                when v_card.telegram_msg_id=v_msg and v_card.canal_id=v_canal
                then 'retomado' else 'duplicado' end;
        end if;
        select a.id,public._oferta_canonico(a.produto_id) into v_aparicao,v_ap_produto
            from public.produto_aparicoes a where a.canal_id=v_canal and a.telegram_msg_id=v_msg;
        if found then
            if v_ap_produto<>v_id then raise exception 'Etapa 3: aparição numérica legada conflitante'; end if;
        else
            select a.id into v_aparicao from public.produto_aparicoes a
                where a.id=any(v_aparicoes) and public._oferta_canonico(a.produto_id)=v_id and a.canal_id is null
                order by a.id limit 1;
            if found then
                update public.produto_aparicoes set canal_id=v_canal where public.produto_aparicoes.id=v_aparicao;
            else
                insert into public.produto_aparicoes(produto_id,canal_origem,telegram_msg_id,canal_id,
                    data_origem,recebido_em)
                    values(v_id,p_evento->>'canal_origem',v_msg,v_canal,
                        (p_evento->>'data_origem')::timestamptz,(p_evento->>'recebido_em')::timestamptz);
            end if;
        end if;
        if not exists(select 1 from public.produto_aparicoes a where public._oferta_canonico(a.produto_id)=v_id
            and a.telegram_msg_id=v_msg and a.canal_id=v_canal) then
            raise exception 'Etapa 3: aparição legada não confirmada';
        end if;
        insert into public.oferta_eventos(canal_id,msg_id,produto_id,decisao_hash,observacao,data_origem,recebido_em,resultado_inicial)
            values(v_canal,v_msg,v_id,v_decisao,p_produto,(p_evento->>'data_origem')::timestamptz,
                (p_evento->>'recebido_em')::timestamptz,v_status);
        return query select p.id,v_status,p.foto_url from public.produtos p where p.id=v_id;
    end $fn$ $ddl$;

    execute $ddl$
    create or replace function public.oferta_legado_pronto()
    returns table(status text) language plpgsql security invoker set search_path=pg_catalog,public as $fn$
    begin
        perform pg_advisory_xact_lock(730030003::bigint);
        perform public._oferta_verificar_indices();
        update public.oferta_controle set legado_pronto=true where public.oferta_controle.id=1;
        if not found then raise exception 'Etapa 3: controle de prontidão ausente'; end if;
        return query select 'confirmado'::text;
    end $fn$ $ddl$;

    execute $ddl$
    create or replace function public.oferta_enriquecer(p_canal_id bigint,p_msg_id bigint,p_identidade jsonb)
    returns table(id bigint,status text,foto_url text)
    language plpgsql security invoker set search_path = pg_catalog,public as $fn$
    declare v_id bigint; v_outro bigint; v_menor bigint; v_maior bigint;
        v_card public.produtos%rowtype; v_perdedor public.produtos%rowtype;
        v_fundiu boolean := false;
    begin
        perform pg_advisory_xact_lock(730030003::bigint);
        perform public._oferta_validar_identidade(p_identidade);
        select public._oferta_canonico(e.produto_id) into v_id from public.oferta_eventos e
            where e.canal_id = p_canal_id and e.msg_id = p_msg_id;
        if v_id is null then return query select null::bigint,'ausente'::text,null::text; return; end if;
        select p.* into strict v_card from public.produtos p where p.id = v_id;
        if v_card.estado_oferta = 'removida' then
            return query select v_id,'removido'::text,null::text; return;
        end if;
        if v_card.identidade_chave is not null and p_identidade->>'chave' is not null
            and (v_card.identidade_chave <> p_identidade->>'chave'
                or v_card.identidade_dados->'componentes'->'comparacao'
                    <> p_identidade->'componentes'->'comparacao') then
            return query select v_id,'conflito'::text,v_card.foto_url; return;
        end if;
        if p_identidade->>'chave' is null and p_identidade->'copia'->>'chave' is not null
            and (v_card.identidade_versao is distinct from 2 or
                (p_identidade->'copia'->'comparacao'->>'preco_centavos')::numeric
                    is distinct from v_card.preco*100 or
                not exists(select 1 from public.oferta_eventos e where e.canal_id=p_canal_id and e.msg_id=p_msg_id
                    and (e.observacao->>'preco')::numeric*100=
                        (p_identidade->'copia'->'comparacao'->>'preco_centavos')::numeric)) then
            return query select v_id,'conflito'::text,v_card.foto_url; return;
        end if;
        if p_identidade->>'chave' is null and v_card.identidade_chave is not null then
            return query select v_id,'incerto'::text,v_card.foto_url; return;
        end if;
        update public.oferta_eventos set identidade_enriquecida = p_identidade
            where canal_id = p_canal_id and msg_id = p_msg_id;
        if p_identidade->>'chave' is null and (p_identidade->'copia'->>'chave' is null
            or v_card.identidade_chave is not null) then
            return query select v_id,'incerto'::text,v_card.foto_url; return;
        end if;
        update public.produtos set identidade_chave = p_identidade->>'chave',
            identidade_dados = p_identidade where public.produtos.id = v_id;
        loop
            select p.* into strict v_card from public.produtos p where p.id = v_id;
            exit when v_card.estado_oferta <> 'ativa' or v_card.expira_em is null
                or v_card.expira_em <= clock_timestamp();
            select p.id into v_outro from public.produtos p where p.id <> v_id
                and p.identidade_versao = 2
                and ((p_identidade->>'chave' is not null and p.identidade_chave=p_identidade->>'chave')
                    or (p_identidade->>'chave' is null and p.identidade_chave is null
                        and p.identidade_dados->'copia'->>'chave'=p_identidade->'copia'->>'chave'))
                and public._oferta_equivalentes(p.identidade_dados,p_identidade)
                and (p_identidade->>'chave' is not null or p.preco*100=
                    (p_identidade->'copia'->'comparacao'->>'preco_centavos')::numeric)
                and p.estado_oferta = 'ativa' and p.canonico_id is null
                and p.expira_em > clock_timestamp() and p.janela_horas = v_card.janela_horas
                and p.inicio_em <= v_card.expira_em and v_card.inicio_em <= p.expira_em
                order by p.id limit 1;
            exit when v_outro is null;
            v_menor := least(v_id,v_outro); v_maior := greatest(v_id,v_outro);
            select p.* into strict v_perdedor from public.produtos p where p.id = v_maior;
            -- Transferir explicitamente ANTES de aposentar. Aliases sempre apontam
            -- direto ao menor ID; todos os pins e observações acompanham o sobrevivente.
            update public.oferta_eventos set produto_id = v_menor where produto_id = v_maior;
            update public.produto_aparicoes set produto_id = v_menor where produto_id = v_maior;
            update public.produtos set canonico_id = v_menor where canonico_id = v_maior;
            update public.produtos set foto_url = coalesce(public.produtos.foto_url,v_perdedor.foto_url),
                inicio_em = least(inicio_em,v_perdedor.inicio_em),
                ultima_aparicao_em = greatest(ultima_aparicao_em,v_perdedor.ultima_aparicao_em),
                expira_em = greatest(expira_em,v_perdedor.expira_em),
                cupom = coalesce(cupom,v_perdedor.cupom), link = coalesce(link,v_perdedor.link)
                where public.produtos.id = v_menor;
            update public.produtos set estado_oferta = 'fundida',canonico_id = v_menor,
                foto_url = null,terminal_em = clock_timestamp() where public.produtos.id = v_maior;
            -- Foto não adotada vira candidata conhecida; a reserva revalida referências.
            if v_perdedor.foto_url is not null then
                perform public.midia_reservar_remocao(v_perdedor.foto_url);
            end if;
            v_id := v_menor; v_fundiu := true;
            perform public._oferta_resumir(v_id);
        end loop;
        return query select p.id,case when v_fundiu then 'fundido' else 'enriquecido' end,p.foto_url
            from public.produtos p where p.id = v_id;
    end $fn$ $ddl$;

    execute $ddl$
    create or replace function public.oferta_buscar(p_id bigint)
    returns setof public.produtos language sql stable security invoker
    set search_path = pg_catalog,public as $fn$
        select p.* from public.produtos p where p.id = public._oferta_canonico(p_id)
            and p.estado_oferta = 'ativa' and p.canonico_id is null
            and (p.identidade_versao is null or p.expira_em > now());
    $fn$ $ddl$;

    execute $ddl$
    create or replace function public.oferta_foto(p_id bigint,p_url text)
    returns table(status text) language plpgsql security invoker set search_path = pg_catalog,public as $fn$
    declare v_id bigint; v_card public.produtos%rowtype;
    begin
        perform pg_advisory_xact_lock(730030003::bigint);
        if nullif(btrim(p_url),'') is null then
            raise exception 'Etapa 3: foto inválida' using errcode = '22023';
        end if;
        v_id := public._oferta_canonico(p_id);
        select p.* into v_card from public.produtos p where p.id = v_id;
        if not found or v_card.estado_oferta in ('removida','expirada')
            or (v_card.identidade_versao = 2 and coalesce(v_card.expira_em <= clock_timestamp(),true)) then
            return query select 'removida'::text; return;
        end if;
        if v_card.foto_url is not null then return query select 'existente'::text; return; end if;
        if exists (select 1 from public.oferta_midias m where m.url = p_url) then
            return query select 'remocao_reservada'::text; return;
        end if;
        update public.produtos set foto_url = p_url where public.produtos.id = v_id;
        return query select 'atualizada'::text;
    end $fn$ $ddl$;

    execute $ddl$
    create or replace function public.oferta_confirmar(p_canal_id bigint,p_msg_id bigint)
    returns table(status text) language plpgsql security invoker set search_path = pg_catalog,public as $fn$
    begin
        perform pg_advisory_xact_lock(730030003::bigint);
        update public.oferta_eventos set pin = false,confirmado_em = clock_timestamp()
            where canal_id = p_canal_id and msg_id = p_msg_id and pin;
        if found then return query select 'confirmado'::text;
        elsif exists (select 1 from public.oferta_eventos where canal_id = p_canal_id and msg_id = p_msg_id)
            then return query select 'confirmado'::text;
        else return query select 'ausente'::text; end if;
    end $fn$ $ddl$;

    execute $ddl$
    create or replace function public.midia_reservar_remocao(p_url text)
    returns table(permitido boolean) language plpgsql security invoker set search_path = pg_catalog,public as $fn$
    begin
        perform pg_advisory_xact_lock(730030003::bigint);
        if nullif(btrim(p_url),'') is null then
            raise exception 'Etapa 3: mídia inválida' using errcode = '22023';
        end if;
        if exists (select 1 from public.produtos p where p.foto_url = p_url) then
            return query select false; return;
        end if;
        insert into public.oferta_midias(url,estado) values(p_url,'reservada')
            on conflict(url) do update set estado = 'reservada',confirmado_em = null,
                pedido_em = case when public.oferta_midias.estado = 'removida'
                    then clock_timestamp() else public.oferta_midias.pedido_em end;
        -- Um job antigo pode ter repetido o upload DEPOIS do DELETE confirmado.
        -- Reabrir a intenção permite compensá-lo; DELETE de chave ausente é idempotente.
        -- O tombstone continua proibindo vínculo em qualquer um dos estados.
        return query select true;
    end $fn$ $ddl$;

    execute $ddl$
    create or replace function public.midia_confirmar_remocao(p_url text)
    returns table(status text) language plpgsql security invoker set search_path = pg_catalog,public as $fn$
    begin
        perform pg_advisory_xact_lock(730030003::bigint);
        update public.oferta_midias set estado = 'removida',confirmado_em = coalesce(confirmado_em,clock_timestamp())
            where url = p_url;
        return query select case when found then 'confirmado' else 'ausente' end;
    end $fn$ $ddl$;

    execute $ddl$
    create or replace function public.oferta_remover(p_id bigint)
    returns table(id bigint,status text,foto_url text)
    language plpgsql security invoker set search_path = pg_catalog,public as $fn$
    declare v_id bigint; v_foto text;
    begin
        perform pg_advisory_xact_lock(730030003::bigint);
        v_id := public._oferta_canonico(p_id);
        if v_id is null then return query select p_id,'ausente'::text,null::text; return; end if;
        select p.foto_url into v_foto from public.produtos p where p.id = v_id;
        update public.produtos set estado_oferta = 'removida',foto_url = null,
            terminal_em = coalesce(terminal_em,clock_timestamp()) where public.produtos.id = v_id;
        if v_foto is not null then perform public.midia_reservar_remocao(v_foto); end if;
        return query select v_id,'removido'::text,v_foto;
    end $fn$ $ddl$;

    execute $ddl$
    create or replace function public.oferta_limpar(p_retencao_horas numeric default 48,
        p_retencao_dias numeric default 7,p_lote integer default 100)
    returns table(id bigint,status text,url text)
    language plpgsql security invoker set search_path = pg_catalog,public as $fn$
    declare v_card record; v_midia record; v_corte timestamptz;
    begin
        perform pg_advisory_xact_lock(730030003::bigint);
        if p_retencao_horas is null or not (p_retencao_horas > 0 and p_retencao_horas < 'Infinity'::numeric)
            or p_retencao_dias is null or not (p_retencao_dias >= 7 and p_retencao_dias < 'Infinity'::numeric)
            or p_lote is null or p_lote < 1 or p_lote > 1000 then
            raise exception 'Etapa 3: retenção/lote inválidos' using errcode = '22023';
        end if;
        v_corte := clock_timestamp() - p_retencao_dias * interval '1 day';
        for v_card in select p.id from public.produtos p where p.estado_oferta = 'ativa'
            and p.canonico_id is null and ((p.identidade_versao = 2 and p.expira_em <= clock_timestamp())
                or (p.identidade_versao is null and (select c.legado_pronto from public.oferta_controle c where c.id=1) and p.criado_em <=
                    clock_timestamp() - p_retencao_horas * interval '1 hour'))
            order by p.id limit p_lote loop
            update public.produtos set estado_oferta = 'expirada',terminal_em = clock_timestamp()
                where public.produtos.id = v_card.id;
            return query select v_card.id,'expirado'::text,null::text;
        end loop;
        -- Não há TTL de pin. A retenção começa depois de AMBOS terminalização/ack.
        for v_card in select p.id,p.foto_url from public.produtos p
            where p.canonico_id is null and p.estado_oferta in ('removida','expirada')
                and (p.identidade_versao is not null or (select c.legado_pronto from public.oferta_controle c where c.id=1))
                and p.terminal_em < v_corte
                and not exists (select 1 from public.oferta_eventos e where e.produto_id = p.id
                    and (e.pin or e.confirmado_em >= v_corte))
                and not exists (select 1 from public.produtos a where a.canonico_id = p.id
                    and (a.terminal_em is null or a.terminal_em >= v_corte))
            order by p.id limit p_lote loop
            delete from public.oferta_eventos where produto_id = v_card.id;
            delete from public.produto_aparicoes where produto_id = v_card.id
                or produto_id in (select a.id from public.produtos a where a.canonico_id = v_card.id);
            delete from public.produtos where canonico_id = v_card.id;
            delete from public.produtos where public.produtos.id = v_card.id;
            if v_card.foto_url is not null then perform public.midia_reservar_remocao(v_card.foto_url); end if;
            return query select v_card.id,'purgado'::text,null::text;
        end loop;
        -- Purgar eventos/aparições confirmados antigos sem histórico infinito.
        -- A observação vencedora sustenta resumo/preço; pins não são elegíveis.
        delete from public.produto_aparicoes a where (a.canal_id,a.telegram_msg_id) in (
            select x.canal_id,x.msg_id from public.oferta_eventos x join public.produtos p on p.id=x.produto_id
            where not x.pin and x.confirmado_em<v_corte and
                (x.canal_id,x.msg_id) is distinct from (p.preco_canal_id,p.preco_msg_id)
            order by x.confirmado_em limit p_lote);
        delete from public.oferta_eventos e where (e.canal_id,e.msg_id) in (
                select x.canal_id,x.msg_id from public.oferta_eventos x
                join public.produtos p on p.id = x.produto_id
                where not x.pin and x.confirmado_em < v_corte
                    and (x.canal_id,x.msg_id) is distinct from (p.preco_canal_id,p.preco_msg_id)
                 order by x.confirmado_em limit p_lote);
        delete from public.produtos a where a.id in (select x.id from public.produtos x
            where x.estado_oferta='fundida' and x.terminal_em<v_corte
                and not exists(select 1 from public.oferta_eventos e where e.produto_id=x.canonico_id
                    and (e.pin or e.confirmado_em>=v_corte))
            order by x.id limit p_lote);
        -- Tombstones só podem sair quando nenhum job recuperável pode repetir upload.
        delete from public.oferta_midias m where m.url in (select x.url from public.oferta_midias x
            where x.estado='removida' and x.confirmado_em<v_corte
                and not exists(select 1 from public.oferta_eventos e where e.pin)
            order by x.confirmado_em limit p_lote);
        -- Repetir lote após falha Storage devolve a MESMA intenção durável.
        for v_midia in select m.url from public.oferta_midias m where m.estado = 'reservada'
            order by m.pedido_em,m.url limit p_lote loop
            return query select null::bigint,'midia_pendente'::text,v_midia.url;
        end loop;
    end $fn$ $ddl$;

    -- Inclui auxiliares: nenhuma função nova herda EXECUTE de PUBLIC.
    for v_funcao in select p.oid::regprocedure from pg_proc p join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'public' and p.proname = any(array[
            '_oferta_validar_identidade','_oferta_canonico','_oferta_resumir','_oferta_verificar_indices','_oferta_equivalentes',
            'oferta_registrar','oferta_enriquecer','oferta_buscar','oferta_foto','oferta_confirmar',
            'oferta_remover','oferta_limpar','oferta_legado_registrar','oferta_legado_pronto',
            'midia_reservar_remocao','midia_confirmar_remocao']) loop
        execute format('revoke all on function %s from public,anon,authenticated',v_funcao);
        execute format('grant execute on function %s to service_role',v_funcao);
    end loop;
end
$etapa3_ofertas$;
-- ETAPA 3 OFERTAS: fim. Rollback conserva schema/pins; nunca reativar limpador antigo.
