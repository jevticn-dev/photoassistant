-- Runs once, when Postgres initialises an empty data directory.
--
-- pgvector must exist before EF Core migrations create vector columns, and a
-- migration cannot install it on a database it is already connected to in the
-- same transaction. The EF model also declares HasPostgresExtension("vector")
-- so that a database created outside this compose file still gets it.

CREATE EXTENSION IF NOT EXISTS vector;
