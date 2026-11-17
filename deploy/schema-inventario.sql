-- SOMENTE LEITURA. psql -X -v ON_ERROR_STOP=1 -f deploy/schema-inventario.sql
-- Guardar saída protegida e comparar com o MESMO comando em base limpa candidata.
-- Presença de objetos não certifica que a definição seja a revisão atual.
begin read only;
set local statement_timeout = '15s';
select current_setting('server_version') as postgres;
select table_name,column_name,data_type,is_nullable,column_default
from information_schema.columns where table_schema='public' and table_name in
('produtos','produto_aparicoes','filtros','canais','bot_state','oferta_eventos','oferta_midias','oferta_controle')
order by table_name,ordinal_position;
select c.relname as tabela,k.conname,pg_get_constraintdef(k.oid) as definicao
from pg_constraint k join pg_class c on c.oid=k.conrelid join pg_namespace n on n.oid=c.relnamespace
where n.nspname='public' and c.relname in
('produtos','produto_aparicoes','filtros','canais','bot_state','oferta_eventos','oferta_midias','oferta_controle')
order by c.relname,k.conname;
select tablename,indexname,indexdef,i.indisvalid,i.indisready
from pg_indexes x join pg_class c on c.relname=x.indexname
join pg_namespace n on n.oid=c.relnamespace and n.nspname=x.schemaname
join pg_index i on i.indexrelid=c.oid
where x.schemaname='public' and x.tablename in
('produtos','produto_aparicoes','filtros','canais','bot_state','oferta_eventos','oferta_midias','oferta_controle')
order by tablename,indexname;
select p.oid::regprocedure as assinatura,md5(pg_get_functiondef(p.oid)) as definicao_md5,
       p.prosecdef as security_definer,p.proconfig,p.proacl,
       has_function_privilege('service_role',p.oid,'EXECUTE') as service_executa,
       has_function_privilege('anon',p.oid,'EXECUTE') as anon_executa,
       has_function_privilege('authenticated',p.oid,'EXECUTE') as auth_executa
from pg_proc p join pg_namespace n on n.oid=p.pronamespace
where n.nspname='public' and p.proname ~ '^(_?oferta_|midia_)'
order by p.proname,p.oid::regprocedure::text;
select table_name,grantee,privilege_type from information_schema.role_table_grants
where table_schema='public' and table_name in
('produtos','produto_aparicoes','filtros','canais','bot_state','oferta_eventos','oferta_midias','oferta_controle')
order by table_name,grantee,privilege_type;
select tablename,policyname,roles,cmd,qual,with_check from pg_policies
where schemaname='public' order by tablename,policyname;
-- Estado do gate é observado; NUNCA chamar oferta_legado_pronto na pré-checagem.
select id,legado_pronto from public.oferta_controle;
select estado,count(*) as quantidade from public.oferta_midias group by estado order by estado;
select pin,count(*) as quantidade from public.oferta_eventos group by pin order by pin;
rollback;
