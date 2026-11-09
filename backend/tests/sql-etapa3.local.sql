-- Somente bootstrap SINTÉTICO do runner em banco local vazio descartável.
-- Simula os papéis/schema Supabase, NÃO altera/desabilita RLS para testar.
do $papeis$
begin
    if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
    if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
    if not exists (select 1 from pg_roles where rolname = 'service_role') then
        create role service_role nologin bypassrls;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'service_role' and rolbypassrls) then
        raise exception 'Papel sintético service_role precisa de BYPASSRLS; runner não modifica papel existente';
    end if;
end $papeis$;
create schema auth;
create function auth.role() returns text language sql stable as
    $$select current_setting('request.jwt.claim.role',true)$$;
grant usage on schema auth,public to anon,authenticated,service_role;
create schema storage;
create table storage.buckets(id text primary key,name text,public boolean);
