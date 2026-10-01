# G5 Gate Report - AI Company OS

**Verdict: PASS**

- Executed at: `2026-10-01T02:34:00Z`
- Executed by: `scripts/generate_g5_gate_report.py`
- Commit: `ca4eacfa7d1f3c6f481a37fff66ffa83f7a07fa0`
- Human reviewer: `None`
- Criterion source: docs/11_EXECUTION_GATES.md, G5: identity, model registry, decision ledger, tool permissions, and governance workflows operate with complete audit trails.

## Why this verdict

All seven criteria pass. G5.1 through G5.6 cover identity, the model registry, the decision ledger, tool permissions, the governance workflows, and the rebuild of a stack over persisted state. G5.7 was the last to close and closes on evidence rather than on argument: a running OS process rebuilds its stack from a live PostgreSQL on startup, and refuses to start when it cannot. This report previously recorded FAIL on G5.7 for two reasons - there was no process entrypoint, and the modules carried no PostgreSQL driver - and both are now closed. The driver is github.com/lib/pq v1.10.9, admitted without weakening the pinning gate; the entrypoint is services/control-plane/cmd/control-plane, whose startup rehydration is asserted over HTTP from a separate process. Two boundaries are stated rather than left implicit, because a PASS that hides them would be the same defect this gate exists to catch: the process exposes no write path yet, and the audit-acceptance and registry-persistence guarantees named in docs/22 remain assigned to WI-120 and WI-121, so this gate does not claim cross-store atomicity between a registry write and its audit record. Neither is within G5.7's wording, which asks whether a running process performs the rebuild on startup against a live database.

## Attestation

human_reviewer is null. An automated agent recording itself as the reviewer would satisfy the field and none of its purpose, so this field is left for a named human. The commit field records the baseline this gate's work was built on, which is the right thing for a reviewer to diff against: it is the tree of specification paths that preceded the work, so `git diff` from it shows every file below. It cannot record the commit that contains the work, because a commit cannot contain its own SHA, so a reader wanting the exact tree these digests were taken from should regenerate the report and read the commit field again. The report is not a snapshot of a moment: `--check` fails if it differs from a fresh regeneration, and that check runs in CI and in tests/ci, so a report cannot go stale without a gate failing.

## Criteria

| ID | Subsystem | Result | Mechanically verified |
| --- | --- | --- | --- |
| G5.1 | identity | **PASS** | yes |
| G5.2 | model registry | **PASS** | yes |
| G5.3 | decision ledger | **PASS** | yes |
| G5.4 | tool permissions | **PASS** | yes |
| G5.5 | governance workflows | **PASS** | yes |
| G5.6 | rebuild from persisted state | **PASS** | yes |
| G5.7 | startup in a running process | **PASS** | yes |

### G5.1 identity - PASS

Workload identity operates with a complete audit trail: short-lived issuance bound to one exact model version, immediate revocation carrying reason and evidence, and no re-minting of a revoked name.

Issuance and revocation are both persisted before in-memory state changes, and revocation carries its reason and evidence. Covered by TestARevokedIdentityCannotBeReMintedAfterARestart, TestALiveIdentitySurvivesARestart, TestARevokedIdentityIsNotRestoredLive, and the containment widening tests.

### G5.2 model registry - PASS

The model registry operates with a complete audit trail, and the journal is its only write path: lifecycle state is written only after the audit chain accepts the record describing it.

TestDurableWriteHappensAfterTheAuditAppend and TestARefusedDurableWriteIsCorrectedInTheAuditChain prove the ordering; TestRefusedTransitionLeavesTheModelWhereItWas proves a refused durable write changes no in-memory state. The refusal correction is closed by a resolution record, so the chain's last word on a retried transition is SUCCEEDED.

### G5.3 decision ledger - PASS

The decision ledger records prompt, tool call, retrieved context, and lineage, including refusals with their reason.

TestRefusedToolCallsAreRecordedWithTheirReason proves a refused call is recorded with its reason rather than dropped; TestRestoreRecoversTheIdempotencyLedger proves the ledger survives rehydration of in-process state.

### G5.4 tool permissions - PASS

Tool permissions deny by default: an allowlist that is empty, absent, or names an unlisted tool denies, and a financial tool is refused on the direct path.

TestAnEmptyAllowlistDeniesEverything, TestNilAllowlistDeniesEverything, TestUnnamedToolsAreDenied, and TestFinancialToolIsRefusedOnTheDirectPath. Denial is the default rather than the failure mode, so a missing configuration fails closed.

### G5.5 governance workflows - PASS

Governance workflows operate with a complete audit trail: monitoring pause, containment, rollback, and retirement each record what they did, and no model authorizes its own execution.

TestContainPerformsTheRevocationRatherThanAssertingIt proves containment performs the revocation instead of asserting it; TestContainmentWidensToEveryWorkloadServingTheCompromisedVersion proves the blast radius widens to every workload serving the same exact model version; TestCompromiseMustNameWhatItQuarantines proves the response cannot proceed without naming its target.

### G5.6 rebuild from persisted state - PASS

A stack rebuilt over persisted state rehydrates the audit chain, the model registry and the workload registry, rather than starting empty.

services/control-plane/bootstrap composes the durable stack and is the first code in the repository to construct an audit Exporter or a rehydrated journal. TestARebuiltStackRecoversWhatTheFirstStackRegistered builds a stack, registers a model, exports its audit trail, then builds a second stack over the same durable state and requires the model to come back with its owner intact - which is what a restarted control plane depends on and what no code could previously demonstrate. Two mutations confirm the test has teeth: building the journal empty instead of rehydrating it, and skipping the chain rehydration, each fail by name. The second fails on the registry's own corroboration check - 'the registry has drifted from the evidence' - which is the integrity guarantee doing its job on an assembly order mistake rather than on corrupt data.

### G5.7 startup in a running process - PASS

A running control plane performs that rebuild on startup, against a live database, with the SQL adapters behind the durable ports.

Mechanically established against a real OS process and a real PostgreSQL 17.11. EV-060 established the driver (github.com/lib/pq v1.10.9, empty transitive closure, unmodified toolchain gate) and it is adopted; this criterion records the work that made it sufficient, since a permitted driver alone is not a running process. Three things were built. First, services/control-plane/migrate/store_sql.go implements migrate.Store over database/sql, owning the outer transaction and stripping BEGIN/COMMIT from each migration body so the schema change and the applied-set record commit together; integration tests prove a failed migration commits neither and a failed revert preserves both. Second, services/control-plane/cmd/migrate is the operator CLI, ported from the parked pgx version; it was exercised through a full up/down/up cycle against the live database and CI now applies it to the integration database, which the disposable rehearsal container cannot do because it discards its own. Third, services/control-plane/cmd/control-plane is the process entrypoint: it reads its configuration from the environment, opens and pings the database, assembles the SQL adapters behind every durable port, calls bootstrap.Build to rehydrate, binds a socket only after the rebuild succeeds, and serves /healthz and /readyz. TestARunningProcessRebuildsItsStackFromPostgreSQLOnStartup compiles that binary, seeds a model, an audit trail and a revocation through the real write paths, runs the binary as a separate process, and asserts over HTTP that it recovered the model, the partition and the revocation from PostgreSQL. The in-process tests cannot establish this: their first and second stacks are two values of a variable, and a test binary never stops. Fail-closed behaviour is asserted too, not just the happy path. TestTheEntrypointRefusesToStartOnARegistryThatHasDriftedFromItsAuditChain starts the process against a partition it was not configured for, so the registry cannot be corroborated against the chain, and requires exit code 2 and nothing listening; a process that started anyway would report the model as unregistered and invite a second SUCCEEDED registration. TestTheEntrypointRefusesToStartWithoutItsConfiguration covers the missing DSN, the missing environment, and a non-positive or non-numeric backlog limit. Identity is covered on the same footing: TestWorkloadIdentitySurvivesAProcessRestart requires an issued identity to come back and authenticate, and a revoked one to come back revoked, excluded from the live registry, with its reason and evidence intact. One limit is stated rather than glossed. The process exposes no write path: audit records reach storage through a caller-driven accept-then-export pair, and no background loop can substitute because the chain does not record which of its records were exported, so re-exporting one violates the audit table's unique constraint. The write path is the next step and /readyz reports write_path_exposed as false rather than implying a drain that is not happening. G5.7 asks whether a running process performs the rebuild on startup against a live database, and it now demonstrably does.

## Evidence artifacts

87 files, 1034522 bytes, digest `sha256`.

Every path is relative to the repository root and every digest is over the exact bytes at the commit above. A criterion cannot be re-verified without these.

| Path | SHA-256 | Bytes |
| --- | --- | --- |
| `db/migrations/0004_model_registry.sql` | `fe17a1ab2695c79e605b5f485605a0f6cc5532e3d375156b32e0fc1af31a6e18` | 21579 |
| `scripts/generate_g5_gate_report.py` | `f250894b8d358b70fd6d4b8ce21bf0204e80188eb90ffee0b118d9a033302b34` | 23043 |
| `services/control-plane/audit/anchor_test.go` | `01a7715670311388a597adf1c2fbe17ff03fe2a2a01cab6a189c1f606b530865` | 15997 |
| `services/control-plane/audit/chain.go` | `5e703062fd2910db6673aecac189090facddf0cc5b676aee8b717c3d14e3cb20` | 9549 |
| `services/control-plane/audit/chain_test.go` | `a19f009ff13dbddf4d97ea5e059b6929ab92a7d0cc8f5d9976036e43980b962f` | 11284 |
| `services/control-plane/audit/checkpoint.go` | `995283806fa757acdd3cd34d3c1d27bb5af59c6343eb4bfa50bad2783ad7b541` | 4761 |
| `services/control-plane/audit/checkpoint_test.go` | `8233919582d28a4daecaff54751ebf2571ccd8a528b186e1ae32b1f7aaf8b3f7` | 7858 |
| `services/control-plane/audit/doc.go` | `e29d3b71d05985c5a0a93d589a0bbd38bb23ebdc29bca3b9cd5165fa0c22ab00` | 1757 |
| `services/control-plane/audit/errors.go` | `305aa945b5debde85023d7aa9baf162877fac9e2d515a1985d12183cfc8831ee` | 4367 |
| `services/control-plane/audit/guard.go` | `f76b015783bc5b78e0374a2d6ba1614ae5d28b11b146a2d6af0869caa2bd60d9` | 8369 |
| `services/control-plane/audit/guard_test.go` | `248dc74eaf933ee442626fc55b27a4e1b3dbe078b86ff587f865a16033a94b68` | 7613 |
| `services/control-plane/audit/keys.go` | `435dedefb60dc2438cb2da54810eb876c6df4b32b6f48ee9fe8b88fe632d0579` | 8806 |
| `services/control-plane/audit/migration_contract_test.go` | `dffa964a77a4107c2184f08d0c37c200677dc282d55c91deaed56300e539a6ef` | 6982 |
| `services/control-plane/audit/reader.go` | `d8ee9654096fab567125f8e0009772330a43223b03f5f35561137bab8469d10b` | 16916 |
| `services/control-plane/audit/reader_path_test.go` | `4a99f8c22ebebfdb2220683e925a535cb377da8db2d59efcf45a35238ead0f67` | 8497 |
| `services/control-plane/audit/reader_test.go` | `a1386b1f2c8a7a22fab513e2549c6520a2d729298a9e44916f3ebfe6026609a7` | 12445 |
| `services/control-plane/audit/record.go` | `5c4a6d681aa83a218faee2a9db2033e70bb99076368b6e862297400ceb9362c5` | 14269 |
| `services/control-plane/audit/record_test.go` | `10f1b24b11d8e45f5a6727722487ae43132ac3e3173176d59506e734f9deaed7` | 8927 |
| `services/control-plane/audit/restore.go` | `27b85d9c88770c5abce6d185a207be8b84e7d6789cc0af8b875ff53120bb06a8` | 9962 |
| `services/control-plane/audit/restore_test.go` | `0f445302c6a20765621f44eb8bb0e9d079cde02db45d097cf9b85133fadf6bd6` | 11002 |
| `services/control-plane/audit/retention.go` | `3da295128848fd33a46f1b0020067b1093189e5964459669fac3b90a7a1ab96e` | 3921 |
| `services/control-plane/audit/sink.go` | `ae4b9e18c1cf9c111ff2c4aaa5a817dc2ba9e9d5e7f2bd9e7b28df5f3bfd3dfa` | 11279 |
| `services/control-plane/audit/sink_test.go` | `03b7130ba96541cf18a200c649bae10b73ea3aa54e9de7dbdc5ced605523c95a` | 16327 |
| `services/control-plane/audit/verify.go` | `99ad8860381547f350c1ae842b8bc2d712615e4263bc878863ecb67a87644ffb` | 8202 |
| `services/control-plane/audit/verify_test.go` | `adbe1227fa0351864d53539ea4e29685a1a0c401e57174c1fe009833af1e23df` | 9011 |
| `services/control-plane/bootstrap/bootstrap.go` | `8ca4e59d452ce5339e8d619663f8f8aee7f401c8a399049ba8bc2892eee2f508` | 9673 |
| `services/control-plane/bootstrap/bootstrap_test.go` | `31e7a3f55bbd498a603158e5df2d720f3da5b82e07e2f66ac85e715fa77aadcb` | 12000 |
| `services/control-plane/cmd/control-plane/main.go` | `4fa55ad0c56615817a9972920c53b9c2fae88d35273cb5cbb5079ab9e8940acd` | 18214 |
| `services/control-plane/cmd/control-plane/main_test.go` | `64a7420c8bcec3cc5a19d9299dbbfc59952827ffe68ea6648f1ef11cea899390` | 12084 |
| `services/control-plane/cmd/migrate/main.go` | `7e256beb715e8509d5207f1369158a570e88cbd37247c4432ce90b236a71d8f8` | 8745 |
| `services/control-plane/cmd/migrate/main_test.go` | `e8bed87001e2b1c04b6a7a7061e5d6c50a795e85c51eebcef89a572f4332fe8e` | 15428 |
| `services/control-plane/db/dbgen/model_registry.sql.go` | `861d197d54d606c089908dc22302531375adc195ed816198539646b552306878` | 33754 |
| `services/control-plane/db/queries/model_registry.sql` | `91d164b872fb2bdae97bc11219453914e76341ca35aa43d92b916909d6bf5763` | 13907 |
| `services/control-plane/go.mod` | `b9f11a0ba71bb93e27752d41734781c9dd2f390d82b3cd6796b48a826d8b652a` | 1258 |
| `services/control-plane/go.sum` | `90f48a605768fc3f5813e27cd5c63e854f07b8d1d92a5f6d7f9b9862e02ea445` | 155 |
| `services/control-plane/integration/atomicity_test.go` | `45ec96cd8a1223d0025552ea39595bf7edf591fa65cb83e485e008b0f772e4d7` | 5260 |
| `services/control-plane/integration/audit_test.go` | `ce2a1d3fedee2b84e271d26adc6264787aee7b1d044e56f9d0cf59ea6211b6bf` | 13547 |
| `services/control-plane/integration/destructive_guard_test.go` | `8e259a02c811925f7b606593fca96225e4db1fbc6a2010f7b164b880cd03d210` | 12001 |
| `services/control-plane/integration/entrypoint_test.go` | `77d1eaf821e4bbca4eaf76c03f7799d53fdca68f4884ba3e351e7bce63d914d8` | 17974 |
| `services/control-plane/integration/harness_test.go` | `7be7599615133ae23f8a9615ec91b9c88bb807bc8ba26cc9ecffdb15bcc1e6bc` | 13597 |
| `services/control-plane/integration/identity_test.go` | `eefc72f46903ab30d63175e43a1387a178f504c064a321d5e62494f7ca366f26` | 10270 |
| `services/control-plane/integration/migrator_test.go` | `f842dc3a7ad27b851b1cb5dde4308e54058c2a513b748311fa79c9ac863c3afc` | 6742 |
| `services/control-plane/integration/model_store_test.go` | `41fba578bbf0b1060f9ae1e9a1f413dd42bbd873036a5ad25ffb99ba3ccc08b0` | 10264 |
| `services/control-plane/integration/restart_test.go` | `d2d2c29e915037e88778639acb773a583a0b2e24ca35fb78d15e876a7618b7ee` | 11229 |
| `services/control-plane/migrate/live_test.go` | `4968d75d221d4edfd4360453f291c1eca354fa635a2c611eb4a53606853f142f` | 13759 |
| `services/control-plane/migrate/lock_test.go` | `f386db01558d3fbe9e6fbe8117005366e87ac1b52adcaac7044538ae137f0f33` | 9021 |
| `services/control-plane/migrate/migrate.go` | `e27ec916de880e67edc4863b4933614178a48dd2a09ed1459b860b3b9403e34b` | 17852 |
| `services/control-plane/migrate/migrate_test.go` | `3484a96ea8003aac8e19b15d06f1680f2058dcc18a742fe2313fefa9363dbc56` | 9988 |
| `services/control-plane/migrate/plan_target_test.go` | `af40a5c68abd62a0c4686c5d1982b4da50888c7fe2a89d1891aeac6acce5c196` | 7112 |
| `services/control-plane/migrate/real_migrations_test.go` | `a65a46d8bae8c1a737403e6956958b04fc8969e8fd694f91074f88fc7d4c5eda` | 6193 |
| `services/control-plane/migrate/runner.go` | `5866aee6344bdf967955793366ea4640d3fc79adc2a5c34f3eb5cc44a97723a5` | 6266 |
| `services/control-plane/migrate/store.go` | `354b3159e2a48342ee56c8c57cea71842c81a6c9c8a7479add83e57cc267c36d` | 5228 |
| `services/control-plane/migrate/store_sql.go` | `0b561116b84b359ec8cead3a363611bdcb9e5b82965c1d8b98b0c44c86b4aac5` | 12917 |
| `services/control-plane/migrate/store_sql_test.go` | `fd933bd49b7db2874d24844ddaa39268908dad01ae3eb1b43bf186d951e5cd91` | 3814 |
| `services/control-plane/model/compromise.go` | `71347be3fa1ca20d9290f0480a0477c014345c6ad2dbf9fbc8cf4fc0bf014d9e` | 13697 |
| `services/control-plane/model/compromise_test.go` | `04f2abb7a9e9f17aecd738cf6947c4e0a6306722d814f187a75eb34f9a1f2eb1` | 15890 |
| `services/control-plane/model/decision.go` | `748af05a5e3368876e56952c5ccc1ef27ae510c5ef8e8956dcc1d14c516e6cbd` | 11160 |
| `services/control-plane/model/decision_test.go` | `22b44f20fa92e2ee1798d20287a00c721e68c0501147388a12c4b31601764803` | 8853 |
| `services/control-plane/model/declaration_test.go` | `4646ffd8fae526ae8bf2682459ccdfb0689b4ecfc7aae8700e5afb9a321ba64a` | 7514 |
| `services/control-plane/model/identity.go` | `8d6a7499262589baf28803b0a6376210a84941497e9efe892c04e554bc6fcb3c` | 23735 |
| `services/control-plane/model/identity_read.go` | `b72426a11a4ce8aa27e5117c7cc32c6ccf5c09c000275123c1cf9312a4cdb814` | 6982 |
| `services/control-plane/model/identity_restore.go` | `ffe38d24bf0b374f6d611cd58addd4423fb387950d29e5665d56ff78da136a19` | 5202 |
| `services/control-plane/model/identity_restore_test.go` | `a74c7514503e92b02f1fbad012168c2865985652a62cecd9ad6e687230e1564f` | 21778 |
| `services/control-plane/model/identity_store.go` | `7eeb516eb1b2b4ed18761e0791acc352209da5c568f21d339c29d3d08bac4b94` | 10141 |
| `services/control-plane/model/identity_store_test.go` | `23be08ff8a2d9bbae4a1fb103cabdc3f329f25bc7e7e1b0b941f36feb1dec189` | 17693 |
| `services/control-plane/model/identity_test.go` | `160fcc1e765f50473a5a53e8ed73233741df48f5f7b8e11361737577ad9f1004` | 18508 |
| `services/control-plane/model/journal.go` | `f028da5f6421ee64970dd65a746a8425b7e85d698d0f5df86a7ea33c11cac36e` | 27956 |
| `services/control-plane/model/journal_test.go` | `475110679e5211389e61ff4f2019a95bab30cff6a37dc884061e93a98e98d802` | 22937 |
| `services/control-plane/model/lifecycle.go` | `1dbda61b5a62b89d20f57953bec30e3fb6fe93119296cce26f164de2d2239fde` | 39031 |
| `services/control-plane/model/lifecycle_test.go` | `84c67fa30063cbefb23feac1839d8282a8f802320637d959fb3ebeb9fe67494e` | 14934 |
| `services/control-plane/model/monitoring.go` | `43e0be8a60ffa0062ca5ce83add184a0dfcb552af7b46f932f74241c2b5eecb4` | 9677 |
| `services/control-plane/model/monitoring_test.go` | `f2bcab289850aa54597c5eeef722b5770b9443ec4e640a275026d0caa0b20d68` | 8451 |
| `services/control-plane/model/quarantine_test.go` | `9dcd5af9f81d7ccd689e2c59258f72121cfa9f2ba8a39425ef5f505dc5cf3b0f` | 5477 |
| `services/control-plane/model/record.go` | `05d8e961a8dae7d599e2f1879b5b46210ecd0b2388d31f805d93240b39c9ea71` | 13980 |
| `services/control-plane/model/record_test.go` | `3e7f70d2f5514f3237b2d951d1df5dacc2350b1125199728dcb9b9e80f44750d` | 6974 |
| `services/control-plane/model/restore.go` | `15ee03ca92cc3c6edf5f5943011fa3d136bf6567655285ae03cbfd9d201fb8f2` | 7908 |
| `services/control-plane/model/restore_test.go` | `a38251e30344a8c6f8adf604a6d32b48cd535a12660e7c39a70d0b3fb687c273` | 23819 |
| `services/control-plane/model/rollback_test.go` | `8b40eacee114fe09a9141ccb8c3f128ad4e8fc0d2d9b4d8c4ef80737dd3fc08a` | 6497 |
| `services/control-plane/model/store.go` | `a1623c4df36516e527d2acca460933cb0af469fb10ddc2b2cf41ec2ebe333095` | 9659 |
| `services/control-plane/model/store_read.go` | `02747ff8c849febde7c85774b88d12a5dcb37d4e8e92a50c10999ae6d50acaec` | 10816 |
| `services/control-plane/model/store_read_bulk_test.go` | `8bf29a6d09a263c3d33f85a16af473643c57a253d3fa421e88e4ba4c8235334c` | 8930 |
| `services/control-plane/model/store_sql.go` | `740ab7cf22bcebdc20733fe71065a3ef2f6bcbb6799320792ff82456ec7d9247` | 9149 |
| `services/control-plane/model/store_test.go` | `7e7c027a25ec73bae8aee4f1e7b03e68ee61a8a05440237babb9631f5953139d` | 33778 |
| `services/control-plane/model/structure_test.go` | `fee1d5c9cb37ee83673e4627fea9d3266849ebfe673e59cf6c9897ca4011ccd4` | 9744 |
| `services/control-plane/model/tools.go` | `968a6bc09caece8110238b2526035cb9ebc3e8d47e556cf65c7f54a7de43fc1d` | 10724 |
| `services/control-plane/model/tools_test.go` | `55c7981037298c650896d435075be4324fc09c670bdc96e2443072e0d9cc759d` | 10373 |
| `sqlc.yaml` | `c70093329584775bc14429a6517a3f2f574498cfcfa78892ea751b3090fd58ac` | 1580 |
