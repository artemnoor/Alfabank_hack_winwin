-- Run once per local application database as its administrator.
-- This script defines Documents-only roles; it never embeds credentials.

DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'documents_owner') THEN
        CREATE ROLE documents_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'documents_migrator') THEN
        CREATE ROLE documents_migrator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END
$roles$;

ALTER ROLE documents_owner WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
ALTER ROLE documents_migrator WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;

DO $schema$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'documents') THEN
        CREATE SCHEMA documents AUTHORIZATION documents_migrator;
    ELSIF (SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'documents')
          <> 'documents_migrator' THEN
        RAISE EXCEPTION 'documents schema has an unexpected owner';
    END IF;
END
$schema$;

REVOKE ALL ON SCHEMA documents FROM PUBLIC;
GRANT USAGE ON SCHEMA documents TO documents_owner;
DO $memberships$
DECLARE
    profile_role text;
BEGIN
    FOREACH profile_role IN ARRAY ARRAY['alfalab_development', 'alfalab_testing'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = profile_role) THEN
            EXECUTE format('GRANT documents_owner TO %I', profile_role);
        END IF;
    END LOOP;
END
$memberships$;
