# Parked: the pgx-backed migration store and `cmd/migrate`

> **SUPERSEDED by EV-060. Kept as the record of a decision that was later shown to rest on an
> untested assumption.**
>
> This document argued that no Go PostgreSQL driver could be added, and used that as the reason
> to park working code. EV-060 tested driver candidates against the unmodified toolchain gate
> instead of reasoning about them, and found `github.com/lib/pq v1.10.9` passes with an empty
> transitive dependency closure. The constraint was real, but it was specific to pgx — the
> reasoning generalised one candidate's property into a claim about all candidates, and nobody
> checked.
>
> What happened as a result:
>
> - `github.com/lib/pq v1.10.9` is now a dependency of `services/control-plane`.
> - The store was ported to `database/sql` as `services/control-plane/migrate/store_sql.go`
>   (`migrate.SQLStore`), replacing `migrate.PgStore`; `pgstore.go` here is not in the build.
> - The CLI was ported to `services/control-plane/cmd/migrate` and runs in CI; the
>   `cmd-migrate/main.go` here is not in the build.
> - `services/control-plane/integration` round-trips the durable adapters against PostgreSQL
>   17.11, and `cmd/control-plane` rebuilds its stack from that database on startup.
>
> The reasoning below is left intact rather than rewritten. It is what the project believed, why
> it believed it, and the fact that a careful argument about one dependency generalised into a
> false claim about all of them is worth more to a later reader than a corrected summary would be.
> Nothing below should be read as current.

These two files are complete and reviewed, and they are not in the build. They are parked here
because the repository's own toolchain gate refuses the dependency they need, and relaxing
that gate to accommodate a dependency chosen during this work item is not a decision the work
item should make for itself.

## What they are

- `pgstore.go` — `migrate.PgStore`, the `migrate.Store` implementation backed by PostgreSQL.
  Records the applied set in `migrate.applied_set`, applies and reverts each migration body in
  the same transaction as its own record, and rolls back on any failure or panic.
- `cmd-migrate/main.go` — the `services/control-plane/cmd/migrate` command that
  `.github/workflows/ci.yml` invokes. Thin by design: flags, connection, and exit codes only.

The rest of the `migrate` package — `Parse`, `Plan`, `CheckDrift`, `Set.Describe`, `Runner` —
is driver-free, fully tested, and **is** in the build. Only the driver-backed store and the CLI
are parked.

## Why they are parked

`docs/00_README.md` names the control-plane stack as "Go, Chi, pgx, sqlc", so pgx is the
documented intent. But pgx cannot satisfy `scripts/verify_toolchain.py`:

```
toolchain gate FAILED (1 of 15 checks):
  - services/control-plane/go.mod: dependency github.com/jackc/pgservicefile uses
    pseudo-version 'v0.0.0-20240606120523-5a60cdf6a761', which does not correspond to a
    tagged release
```

pgx v5.11.0 depends on `github.com/jackc/pgservicefile`, which has no semantic-version tag.
Both of its available versions are pseudo-versions (`v0.0.0-20221227161230-091c0ba34f0a` and
`v0.0.0-20240606120523-5a60cdf6a761`). The gate treats a pseudo-version as an unpinned
reference, and its own comment says this is deliberate:

> Go normally pins to an exact commit, so the failures that matter here are the ones that
> deliberately escape that behaviour: a `latest` keyword, and a `v0.0.0-...` pseudo-version,
> which by definition does not correspond to a tagged release.

That is a considered position rather than an oversight, so it was not weakened. Before this
attempt the repository had **zero** external dependencies and **no `go.sum` in any module**,
which is a supply-chain posture worth noticing before it changes.

Verified: reverting the dependency restores `toolchain gate: 14 checks passed` / `PASS`.

## What is NOT blocked

The WI-106 acceptance criteria are met without a Go driver:

| Criterion | Evidence |
|---|---|
| Expand/contract migrations run up and down against PostgreSQL 17 | `python scripts/rehearse_migrations.py` → `MIGRATION REHEARSAL PASSED`, up → down to a clean catalog → up again, 27 objects verified present/absent/present on PostgreSQL 17.11 |
| sqlc generates accessors; `sqlc vet` passes | `sqlc generate` exit 0, `sqlc vet` exit 0, generated package builds and is gofmt-clean |
| Idempotency uniqueness enforced by a database constraint | `migrate/applied_set` design plus the existing `ledger.idempotency_key` uniqueness; `services/control-plane/db/queries/ledger.sql` uses `ON CONFLICT (idempotency_key)` |
| No migration requires a simultaneous incompatible producer/consumer deployment | Every migration has a real down body; the rehearsal applies the whole set, reverts it, and reapplies it, which is the condition a single-pass runner cannot prove |

## The decision this needs

Three ways forward, none of which is a technical difficulty — all are policy:

1. **Allowlist the pseudo-version.** Add an explicit exception for
   `github.com/jackc/pgservicefile` in `verify_toolchain.py` with the rationale recorded, on
   the argument that a pseudo-version is an immutable commit hash rather than a moving
   reference. This is the narrowest change and it is a real loosening of a supply-chain
   control, so it should be an explicit choice rather than a side effect of adding pgx.

2. **Keep Go driver-free.** The Python rehearsal already proves the migrations apply and
   revert against PostgreSQL 17 with no Go dependency. `cmd/migrate` stays unimplemented and
   CI's migration gate calls the rehearsal. Keeps the zero-dependency posture.

3. **Vendor the driver.** `vendor/` the pgx tree so the resolved code is committed and
   reviewable, and the module graph stops being a supply-chain event. Costs repository size
   and a maintenance burden on every pgx update.

Option 2 is what the repository currently does, because it is the only one that requires
no change to an existing control. This work item made no policy change and took option 2 by
default; switching to 1 or 3 is the project owner's call.

## Related finding, still open

`db/migrations/0002_audit.sql` and `0003_authz.sql` create unqualified tables that land in
`public` and use a name prefix (`audit_records`, `authz_decisions`, …) instead of a namespace,
while `0001_ledger.sql` creates a real `ledger` schema. `docs/05` assigns each schema ownership
of its tables. Moving the nine tables is a breaking change and needs its own
expand/contract migration; it was deliberately left out of WI-106.
