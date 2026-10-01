// Command control-plane is the process entrypoint for the model governance control plane.
//
// It exists because bootstrap.Build composes the durable stack but is not a process: it reads
// no configuration, opens no socket and starts no server. G5.7 asks whether a *running* control
// plane performs the durable rebuild on startup against a live database, and a composition root
// cannot answer that however thoroughly it is tested.
//
// What this command does on startup, in order:
//
//  1. Reads its configuration from the environment and refuses to start without a database URL
//     and a deployment environment. Both are refused rather than defaulted: a defaulted
//     environment places every audit record somewhere nobody chose.
//  2. Opens the database and pings it. sql.Open alone proves nothing, because it defers every
//     connection, so an unreachable database would otherwise be discovered at the first
//     registration rather than at startup.
//  3. Builds the SQL adapters behind the durable ports and calls bootstrap.Build, which
//     rehydrates the audit chain, then verifies and restores the model journal, then restores
//     the workload registry from persisted issuance and revocation. If any of that fails the
//     process exits non-zero and serves nothing, because a control plane that came up with an
//     empty registry would report already-registered models as unknown and invite the caller to
//     register them again.
//     The audit sink is constructed here with a checkpoint signer rather than left to default,
//     because the signer is what writes audit_checkpoints, and that table is what a later
//     rehydration compares each partition's head against. Neither this process nor bootstrap
//     will build without one.
//  4. Serves liveness and readiness over HTTP until interrupted, then shuts down gracefully.
//
// What this command deliberately does not do is expose the write path over HTTP. The model
// registry's write path is the journal, and the journal's records reach durable storage through
// the guard/exporter pair: a caller accepts a record against the guard and exports it, and the
// exporter's final step releases the backlog. There is no background loop that can do this
// instead, because the chain does not record which of its records have already been exported -
// re-exporting one violates the audit table's unique constraint. So the accept-then-export pair
// is driven by the request that caused it, and no such request handler exists yet. This command
// therefore rehydrates and reports, and readiness reports the guard's true state rather than
// claiming a drain that is not happening. Wiring the write path is the next step, and pretending
// it is already wired would be exactly the kind of claim G5 exists to prevent.
//
// Configuration (all read from the environment):
//
//	DATABASE_URL                    required; PostgreSQL DSN
//	CONTROL_PLANE_ENVIRONMENT       required; places every audit record, e.g. PRODUCTION
//	CONTROL_PLANE_ADDR              listen address; default :8080
//	CONTROL_PLANE_GUARD_LIMIT       bounded audit backlog; default 1000
//	CONTROL_PLANE_PARTITIONS        comma-separated audit partitions to rehydrate; default none
//	CONTROL_PLANE_CHECKPOINT_KEY_ID names the key that signs audit checkpoints; default control-plane-local
//	CONTROL_PLANE_STARTUP_TIMEOUT   how long startup may take; default 30s
//	CONTROL_PLANE_SHUTDOWN_TIMEOUT  how long graceful shutdown may take; default 10s
//
// Exit codes:
//
//	0  the process shut down cleanly after an interrupt
//	1  the server stopped unexpectedly
//	2  the process could not start (bad configuration, unreachable database, failed rehydration)
package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/danarprastika/web-trade/services/control-plane/audit"
	"github.com/danarprastika/web-trade/services/control-plane/bootstrap"
	"github.com/danarprastika/web-trade/services/control-plane/model"

	// Registers the postgres driver with database/sql. It is referenced by name nowhere else
	// in this file, so the import is blank; a named import would be a reference to nothing.
	_ "github.com/lib/pq"
)

func main() { os.Exit(run()) }

func run() int {
	cfg, err := configFromEnv()
	if err != nil {
		fmt.Fprintf(os.Stderr, "control-plane: %v\n", err)
		return 2
	}

	// Bound startup. Without a deadline a database that accepts a connection and then stalls
	// would leave the process sitting in startup indefinitely, which reads as "starting" to
	// every supervisor watching it.
	startupCtx, cancelStartup := context.WithTimeout(context.Background(), cfg.startupTimeout)
	defer cancelStartup()

	db, err := sql.Open("postgres", cfg.databaseURL)
	if err != nil {
		fmt.Fprintf(os.Stderr, "control-plane: opening the database: %v\n", err)
		return 2
	}
	defer db.Close()

	if err := db.PingContext(startupCtx); err != nil {
		fmt.Fprintf(os.Stderr, "control-plane: connecting to the database: %v\n", err)
		return 2
	}

	stack, err := buildStack(startupCtx, db, cfg)
	if err != nil {
		// A failed rebuild is a refusal to start, not a degraded mode. Serving anyway would
		// mean answering "this model is not registered" about models that are, which is the
		// failure mode the rebuild exists to prevent.
		fmt.Fprintf(os.Stderr, "control-plane: rebuilding the durable stack: %v\n", err)
		return 2
	}

	rehydrated := describeStartup(stack, cfg)
	fmt.Printf("control-plane: started in %s; %s\n", cfg.environment, rehydrated)

	server := &http.Server{
		Addr:              cfg.addr,
		Handler:           routes(stack, cfg),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	// Listen before announcing readiness. Binding is the step that can fail for a reason
	// startup cannot otherwise detect - an address already in use - and discovering it after
	// reporting a healthy rebuild would be a lie in the useful direction.
	listener, err := net.Listen("tcp", cfg.addr)
	if err != nil {
		fmt.Fprintf(os.Stderr, "control-plane: listening on %s: %v\n", cfg.addr, err)
		return 2
	}
	fmt.Printf("control-plane: listening on %s\n", listener.Addr())

	interrupts := make(chan os.Signal, 1)
	signal.Notify(interrupts, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(interrupts)

	return serve(server, listener, interrupts, cfg.shutdownTimeout)
}

// serve runs the HTTP server until it is interrupted or the listener fails, then drains it and
// returns the process exit code.
//
// It is a separate function, taking the interrupt channel as an argument, for one reason: the
// drain is the part of this command that no other test reaches. The integration test that runs
// this binary as a real process has to terminate it with Kill, because Windows cannot deliver
// os.Interrupt to another process, so a signal-driven shutdown is unobservable from outside on
// the platform this was developed on. Accepting the channel as a parameter makes the drain
// reachable from a test that can simply close the channel, and so provable everywhere.
//
// The behaviour is unchanged by the extraction: same order, same deadlines, same exit codes.
func serve(server *http.Server, listener net.Listener, interrupts <-chan os.Signal, shutdownTimeout time.Duration) int {
	serveErr := make(chan error, 1)
	go func() { serveErr <- server.Serve(listener) }()

	select {
	case err := <-serveErr:
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			fmt.Fprintf(os.Stderr, "control-plane: server stopped: %v\n", err)
			return 1
		}
		return 0

	case sig := <-interrupts:
		fmt.Printf("control-plane: %s received, draining\n", sig)
	}

	// Stop accepting first, then let in-flight requests finish. The reverse order would drop
	// requests that a client believes were accepted, which for a governance plane means an
	// audit record that was written but never answered.
	shutdownCtx, cancelShutdown := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancelShutdown()

	if err := server.Shutdown(shutdownCtx); err != nil {
		fmt.Fprintf(os.Stderr, "control-plane: shutdown did not complete cleanly: %v\n", err)
		return 1
	}
	if err := <-serveErr; err != nil && !errors.Is(err, http.ErrServerClosed) {
		fmt.Fprintf(os.Stderr, "control-plane: server stopped: %v\n", err)
		return 1
	}
	fmt.Println("control-plane: stopped cleanly")
	return 0
}

// config is the process's startup configuration.
type config struct {
	databaseURL     string
	environment     string
	addr            string
	guardLimit      int
	partitions      []string
	checkpointKeyID string
	startupTimeout  time.Duration
	shutdownTimeout time.Duration
}

// defaultCheckpointKeyID names the checkpoint signing key when an operator has not chosen one.
//
// Defaulted rather than refused, and the reasoning is worth stating because every other
// required value here is refused. The database URL and the environment are guesses about
// facts only the operator has, and a wrong guess writes records in the wrong place. The key id
// is a label: it names the key that signs audit checkpoints so a later reader knows what to
// verify against, and an unnamed key is not an unsafe key - it is an unreadable one. The
// operator who runs more than one control plane against one database sets it so the
// checkpoints from each process are distinguishable, and that is the whole of the choice.
const defaultCheckpointKeyID = "control-plane-local"

// configFromEnv reads and validates the startup configuration.
//
// Every required value is required rather than defaulted. DATABASE_URL and the environment in
// particular: a control plane that starts against a guessed database, or that places its audit
// records in an environment nobody chose, is worse than one that refuses to start, because it
// looks healthy while doing it.
func configFromEnv() (config, error) {
	cfg := config{
		databaseURL:     strings.TrimSpace(os.Getenv("DATABASE_URL")),
		environment:     strings.TrimSpace(os.Getenv("CONTROL_PLANE_ENVIRONMENT")),
		addr:            strings.TrimSpace(os.Getenv("CONTROL_PLANE_ADDR")),
		checkpointKeyID: defaultCheckpointKeyID,
		guardLimit:      1000,
		startupTimeout:  30 * time.Second,
		shutdownTimeout: 10 * time.Second,
	}
	if cfg.addr == "" {
		cfg.addr = ":8080"
	}
	if raw := strings.TrimSpace(os.Getenv("CONTROL_PLANE_CHECKPOINT_KEY_ID")); raw != "" {
		cfg.checkpointKeyID = raw
	}

	if cfg.databaseURL == "" {
		return config{}, errors.New("DATABASE_URL is not set; refusing to guess a database")
	}
	if cfg.environment == "" {
		return config{}, errors.New("CONTROL_PLANE_ENVIRONMENT is not set; every audit record " +
			"must be placed in an environment somebody chose, and a default would choose one " +
			"on the operator's behalf")
	}

	if raw := strings.TrimSpace(os.Getenv("CONTROL_PLANE_GUARD_LIMIT")); raw != "" {
		limit, err := strconv.Atoi(raw)
		if err != nil || limit <= 0 {
			return config{}, fmt.Errorf(
				"CONTROL_PLANE_GUARD_LIMIT is %q; it must be a positive integer, because %q "+
					"would be an unbounded queue wearing the name of a bound", raw, raw)
		}
		cfg.guardLimit = limit
	}

	if raw := strings.TrimSpace(os.Getenv("CONTROL_PLANE_PARTITIONS")); raw != "" {
		for _, p := range strings.Split(raw, ",") {
			if p = strings.TrimSpace(p); p != "" {
				cfg.partitions = append(cfg.partitions, p)
			}
		}
	}
	// An empty partition list is allowed and is a real state: a deployment that has written
	// no audit records yet has nothing to rehydrate. It is logged rather than refused because
	// refusing would make the empty case the only case that cannot start. The cost is stated
	// where an operator will see it, because it is the operator's decision: a partition left
	// out of this list is a partition whose audit trail this process will not restore.

	var err error
	if cfg.startupTimeout, err = durationEnv("CONTROL_PLANE_STARTUP_TIMEOUT", cfg.startupTimeout); err != nil {
		return config{}, err
	}
	if cfg.shutdownTimeout, err = durationEnv("CONTROL_PLANE_SHUTDOWN_TIMEOUT", cfg.shutdownTimeout); err != nil {
		return config{}, err
	}
	return cfg, nil
}

// durationEnv reads a duration from the environment, falling back to a default when unset.
func durationEnv(name string, fallback time.Duration) (time.Duration, error) {
	raw := strings.TrimSpace(os.Getenv(name))
	if raw == "" {
		return fallback, nil
	}
	parsed, err := time.ParseDuration(raw)
	if err != nil {
		return 0, fmt.Errorf("%s is %q, which is not a duration such as 30s or 2m", name, raw)
	}
	if parsed <= 0 {
		return 0, fmt.Errorf("%s is %q; a non-positive timeout would abandon startup before "+
			"it could finish", name, raw)
	}
	return parsed, nil
}

// buildStack assembles the durable stack over the real SQL adapters.
//
// This is the wiring the gate asks about: every port is satisfied by a PostgreSQL
// implementation, and bootstrap.Build performs the rebuild from persisted state.
func buildStack(ctx context.Context, db *sql.DB, cfg config) (*bootstrap.Stack, error) {
	// The checkpoint signer closes every exported batch of audit records, and neither the sink
	// nor bootstrap will be built without one. A deployment that could store evidence without
	// anything saying how far it reaches could have its tail deleted and rehydrate as verified,
	// which is why this is a required construction step rather than an optional hardening.
	//
	// The key is generated in process and does not survive it. That is a real limitation and
	// it is stated here rather than left to be discovered: docs/22 section 3 requires a managed
	// KMS or HSM key in production, and no such client exists in this repository yet. Nothing
	// downstream is affected by it - the anchored restore compares the checkpoint's sequence
	// and hash and leaves authenticity to the Verifier's key ring - and the key id is recorded
	// on every checkpoint, so substituting a KMS-backed signer later needs no schema change.
	signer, err := audit.NewLocalSigner(cfg.checkpointKeyID)
	if err != nil {
		return nil, fmt.Errorf("building the audit checkpoint signer: %w", err)
	}
	anchor, err := audit.NewAnchor(signer, time.Now)
	if err != nil {
		return nil, fmt.Errorf("building the audit checkpoint anchor: %w", err)
	}

	sink, err := audit.NewSQLSink(db, anchor)
	if err != nil {
		return nil, fmt.Errorf("building the audit sink: %w", err)
	}
	chainReader, err := audit.NewSQLChainReader(db)
	if err != nil {
		return nil, fmt.Errorf("building the audit chain reader: %w", err)
	}
	store, err := model.NewSQLStore(db)
	if err != nil {
		return nil, fmt.Errorf("building the model store: %w", err)
	}
	snapshot, err := model.NewSQLSnapshotReader(db)
	if err != nil {
		return nil, fmt.Errorf("building the model snapshot reader: %w", err)
	}
	identity, err := model.NewSQLIdentityStore(db)
	if err != nil {
		return nil, fmt.Errorf("building the identity store: %w", err)
	}
	identityReader, err := model.NewSQLIdentitySnapshotReader(db)
	if err != nil {
		return nil, fmt.Errorf("building the identity snapshot reader: %w", err)
	}

	return bootstrap.Build(ctx, bootstrap.Deps{
		Clock:            time.Now,
		Environment:      cfg.environment,
		GuardLimit:       cfg.guardLimit,
		Partitions:       cfg.partitions,
		Sink:             sink,
		CheckpointSigner: signer,
		ChainReader:      chainReader,
		Store:            store,
		Snapshot:         snapshot,
		Identity:         identity,
		Identities:       identityReader,
	})
}

// describeStartup renders what the rebuild actually recovered.
//
// It is computed from the rehydrated stack rather than written as a fixed string, so the line
// an operator sees on boot is a statement about this database. An empty partition list reports
// zero, which is correct and worth seeing: it means nothing was rehydrated.
func describeStartup(stack *bootstrap.Stack, cfg config) string {
	models := len(stack.Journal.RegisteredModels())
	partitions := stack.Chain.Partitions()

	records := 0
	for _, p := range partitions {
		records += len(stack.Chain.Records(p))
	}

	if len(partitions) == 0 {
		return fmt.Sprintf(
			"rehydrated 0 models and 0 audit records; CONTROL_PLANE_PARTITIONS was not set, " +
				"so no audit partition was restored and any partition omitted from it would " +
				"have an audit trail this process does not hold")
	}
	return fmt.Sprintf(
		"rehydrated %d models and %d audit records across %d partition(s) %v; "+
			"%d active workload identities and %d revocations",
		models, records, len(partitions), partitions,
		len(stack.Registry.ActiveIdentities()), len(stack.Registry.Revocations()))
}

// routes builds the process's HTTP surface.
//
// Two endpoints, both about the process rather than about the domain. There is deliberately no
// registration or transition handler here: the write path needs the accept-then-export pair that
// a request handler owns, and shipping a registration endpoint without it would accept a model
// and leave its audit record undurable, which is the exact state G5.7 exists to rule out.
func routes(stack *bootstrap.Stack, cfg config) http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			methodNotAllowed(w, http.MethodGet, http.MethodHead)
			return
		}
		// Liveness only. It deliberately reports no dependency state, because a liveness probe
		// that fails when the database is unreachable causes a restart, and restarting does
		// not fix an unreachable database.
		writeJSON(w, http.StatusOK, map[string]any{"status": "ok"})
	})

	mux.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			methodNotAllowed(w, http.MethodGet, http.MethodHead)
			return
		}

		guard := stack.Guard
		pending := guard.Pending()
		limit := guard.Limit()
		halted := guard.Halted()

		cause, reason := guard.Reason()

		body := map[string]any{
			"status":              "ready",
			"environment":         cfg.environment,
			"models":              len(stack.Journal.RegisteredModels()),
			"partitions":          stack.Chain.Partitions(),
			"workload_identities": len(stack.Registry.ActiveIdentities()),
			"revocations":         len(stack.Registry.Revocations()),
			"audit_backlog": map[string]any{
				"pending": pending,
				"limit":   limit,
				"halted":  halted,
			},
			"journal_durable":    stack.Journal.Durable(),
			"registry_durable":   stack.Registry.Durable(),
			"write_path_exposed": false,
		}

		// A halted guard is fail-closed by design: the guard latches at its limit because it
		// cannot prove where the backlog went. Reporting readiness as 200 while that is true
		// would tell a supervisor to send traffic to a process that will refuse it, so the
		// halt is reflected in the status code as well as the body.
		if halted {
			body["status"] = "not_ready"
			body["audit_backlog"].(map[string]any)["cause"] = cause
			body["audit_backlog"].(map[string]any)["reason"] = reason
			writeJSON(w, http.StatusServiceUnavailable, body)
			return
		}

		// A guard that is not halted but is at its limit will latch on the next accepted
		// record, and nothing drains it yet because the write path is not exposed. Saying
		// ready here would be true for exactly as long as it takes to accept one more.
		if pending >= limit {
			body["status"] = "not_ready"
			body["audit_backlog"].(map[string]any)["reason"] =
				"the audit backlog is at its limit and nothing is draining it; " +
					"the write path that would accept and export records is not exposed yet"
			writeJSON(w, http.StatusServiceUnavailable, body)
			return
		}

		writeJSON(w, http.StatusOK, body)
	})

	return mux
}

// methodNotAllowed answers a wrong method with the methods that are allowed.
func methodNotAllowed(w http.ResponseWriter, allowed ...string) {
	w.Header().Set("Allow", strings.Join(allowed, ", "))
	writeJSON(w, http.StatusMethodNotAllowed, map[string]any{
		"error":   "method not allowed",
		"allowed": strings.Join(allowed, ", "),
	})
}

// writeJSON writes a response body and sets the content type first.
//
// Setting the header after writing would be too late for it to be sent, and a body served as
// text/plain by a probe client is a small, avoidable way to make an endpoint look wrong.
func writeJSON(w http.ResponseWriter, status int, body map[string]any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	// A probe client that hung up mid-write must not take the server down with it, and the
	// response is already committed at this point, so there is nothing useful to report.
	_ = json.NewEncoder(w).Encode(body)
}
