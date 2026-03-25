"""
Compatibility shim — real schema is in api/graphql_schema.py.

The graphql/ directory name shadows graphql-core when imported directly,
so the schema was moved to api/graphql_schema.py. This file re-exports
for any code that still imports from graphql.schema.
"""
# Do NOT import strawberry here — this module is loaded as part of the
# graphql package namespace which conflicts with graphql-core.
# Import from api.graphql_schema instead.
