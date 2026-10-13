-- Run once per local application database as its administrator.
-- Credentials are supplied by the local profiles and are never embedded here.

DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'runs_owner') THEN
        CREATE ROLE runs_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'runs_migrator') THEN
        CREATE ROLE runs_migrator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END
$roles$;

ALTER ROLE runs_owner WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
ALTER ROLE runs_migrator WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;

DO $schema$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'runs') THEN
        CREATE SCHEMA runs AUTHORIZATION runs_migrator;
    ELSIF (SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'runs')
          <> 'runs_migrator' THEN
        RAISE EXCEPTION 'runs schema has an unexpected owner';
    END IF;
END
$schema$;

REVOKE ALL ON SCHEMA runs FROM PUBLIC;
GRANT USAGE ON SCHEMA runs TO runs_owner;
DO $memberships$
DECLARE
    profile_role text;
BEGIN
    FOREACH profile_role IN ARRAY ARRAY['alfalab_development', 'alfalab_testing'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = profile_role) THEN
            EXECUTE format('GRANT runs_owner TO %I', profile_role);
        END IF;
    END LOOP;
END
$memberships$;
