"""The live database package — the one package that speaks SQL.

The concepts are `docs/TECHSPEC/05-schema.md`; the SQL is `schema/truth.sql`
and `schema/projections.sql`. This package owns the connection, the schema
application and the verification; the store facade and the write seam land in
A2 of `docs/PLAN/REWRITE-PLAN.md`.
"""
