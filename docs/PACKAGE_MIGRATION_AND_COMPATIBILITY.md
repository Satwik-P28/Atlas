# Package migration and compatibility

Schema 10 adds `application_installation`, `application_execution` and
`domain_pack_installation`. The migration is append-only and runs inside SQLite's transaction.
`migrate_safely` checks integrity and foreign keys before upgrading, writes a verified SQLite
backup outside the database, applies the chain, then checks integrity and foreign keys again.

## Rollback

A failed migration is rolled back by SQLite; the pre-upgrade backup is retained. Rolling back a
successful installation is an explicit restore of that backup while Atlas is stopped. Do not point
an older Atlas binary at a schema-10 database: the migration guard refuses a database newer than
the build. Uninstalling an application is not a migration rollback.

## Compatibility checks

Applications declare a minimum Atlas version and an exclusive maximum, a compiler version and
operator names/versions. `dependency_diagnostics` reports `atlas_too_old`, `atlas_too_new`,
`compiler_version_mismatch`, `missing_runtime`, `missing_operator` and
`operator_version_conflict`. Installation records an incompatible package as `inspect_only`;
execution returns diagnostics instead of fabricating a result.

The package format is versioned separately from the application runtime. Format version 1 is the
only accepted format. A future format must use a new schema and a new reader; it must not silently
reinterpret version 1.

## Compatibility of saved research

Package uninstall leaves the application research object and execution rows. A fork is a new
application/version with `source_installation_id`; it does not mutate the source package. Source
revision invalidation remains the Phase 7 economic dependency mechanism and does not silently
rewrite a package.
