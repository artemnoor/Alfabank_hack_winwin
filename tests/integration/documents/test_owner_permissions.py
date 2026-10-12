from __future__ import annotations

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy import text


def test_documents_api_role_is_distinct_and_cannot_mutate_immutable_tables(documents_engine):
    with documents_engine.connect() as connection:
        role, session_role, owner_can_update_versions, owner_can_update_documents, owner_can_update_pointer, owner_can_update_identity, owner_can_create_schema = (
            connection.execute(
                text(
                    "SELECT current_user, session_user, "
                    "has_table_privilege('documents_owner', 'documents.versions', 'UPDATE'), "
                    "has_table_privilege('documents_owner', 'documents.documents', 'UPDATE'), "
                    "has_column_privilege('documents_owner', 'documents.documents', 'current_revision', 'UPDATE'), "
                    "has_column_privilege('documents_owner', 'documents.documents', 'tenant_id', 'UPDATE'), "
                    "has_schema_privilege('documents_owner', 'documents', 'CREATE')"
                )
            ).one()
        )
        owner_login, owner_superuser, owner_createdb, owner_createrole, owner_bypassrls, migrator_login, migrator_superuser, schema_owner = connection.execute(
            text(
                "SELECT (SELECT rolcanlogin FROM pg_roles WHERE rolname='documents_owner'), "
                "(SELECT rolsuper FROM pg_roles WHERE rolname='documents_owner'), "
                "(SELECT rolcreatedb FROM pg_roles WHERE rolname='documents_owner'), "
                "(SELECT rolcreaterole FROM pg_roles WHERE rolname='documents_owner'), "
                "(SELECT rolbypassrls FROM pg_roles WHERE rolname='documents_owner'), "
                "(SELECT rolcanlogin FROM pg_roles WHERE rolname='documents_migrator'), "
                "(SELECT rolsuper FROM pg_roles WHERE rolname='documents_migrator'), "
                "(SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='documents')"
            )
        ).one()

    assert role == "documents_owner"
    assert session_role != "documents_owner"
    assert owner_can_update_versions is False
    assert owner_can_update_documents is False
    assert owner_can_update_pointer is True
    assert owner_can_update_identity is False
    assert owner_can_create_schema is False
    assert owner_login is False
    assert owner_superuser is False
    assert owner_createdb is False
    assert owner_createrole is False
    assert owner_bypassrls is False
    assert migrator_login is False
    assert migrator_superuser is False
    assert schema_owner == "documents_migrator"

    with pytest.raises(DBAPIError):
        with documents_engine.begin() as connection:
            connection.execute(text("UPDATE documents.versions SET kind = 'raw' WHERE false"))

    with pytest.raises(DBAPIError):
        with documents_engine.begin() as connection:
            connection.execute(
                text("UPDATE documents.documents SET tenant_id = tenant_id WHERE false")
            )

    with pytest.raises(DBAPIError):
        with documents_engine.begin() as connection:
            connection.execute(text("CREATE TABLE documents.forbidden_by_owner (id integer)"))
