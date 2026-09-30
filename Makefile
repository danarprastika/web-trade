# Canonical build, verification, and gate commands.
#
# The workspace root is not itself a Go module, so package patterns are enumerated
# explicitly. Keeping that list in one place is what makes "the build passed" a
# reproducible claim rather than a shell command someone remembered.
#
# docs/02_POLYGLOT_ENGINEERING_STANDARD.md section 10 and docs/09_TESTING_AND_RELEASE_EVIDENCE.md
# define the CI gates. Every-merge runs: format, lint, unit tests, contract validation,
# SAST, dependency scan. Protected branches add integration tests and artifact build.

SHELL := /bin/bash

GO_MODULE_DIRS := \
	./contracts/go/... \
	./services/control-plane/... \
	./components/risk-engine/... \
	./components/oms/... \
	./components/reconciliation/... \
	./adapters/venues/...

.PHONY: help
help:
	@echo "make fmt          format Go sources"
	@echo "make vet          run go vet across the workspace"
	@echo "make test         run the Go unit test suites"
	@echo "make contracts    validate the canonical contract corpus"
	@echo "make verify       the mandatory every-merge gate (fmt-check, vet, test, contracts)"
	@echo "make tidy         tidy and verify every Go module"

.PHONY: fmt
fmt:
	@for d in contracts/go services/control-plane components/risk-engine components/oms components/reconciliation adapters/venues; do \
		(cd $$d && go fmt ./...) || exit 1; \
	done

.PHONY: fmt-check
fmt-check:
	@fail=0; \
	for d in contracts/go services/control-plane components/risk-engine components/oms components/reconciliation adapters/venues; do \
		out=$$(cd $$d && gofmt -l .); \
		if [ -n "$$out" ]; then echo "unformatted in $$d:"; echo "$$out"; fail=1; fi; \
	done; \
	exit $$fail

.PHONY: vet
vet:
	go vet $(GO_MODULE_DIRS)

.PHONY: test
test:
	go test $(GO_MODULE_DIRS)

.PHONY: contracts
contracts:
	python tests/contracts/validate_contracts.py

.PHONY: tidy
tidy:
	@for d in contracts/go services/control-plane components/risk-engine components/oms components/reconciliation adapters/venues; do \
		(cd $$d && go mod tidy && go mod verify) || exit 1; \
	done

# The mandatory every-merge gate (docs/09, "CI gates").
.PHONY: verify
verify: fmt-check vet test contracts
	@echo "OK: every-merge gate passed"
