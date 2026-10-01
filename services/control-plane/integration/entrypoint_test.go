//go:build integration

package integration

import (
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// TestARunningProcessRebuildsItsStackFromPostgreSQLOnStartup is G5.7 as an operating system
// test rather than a Go test.
//
// Everything else in this package proves the same rebuild from inside the test binary, where
// the "first process" and the "second process" are two values of a variable. That is a real
// limitation rather than a technicality: a test binary cannot demonstrate that a *running
// program* rebuilds its state on startup, because it never stops. So this test compiles the
// actual entrypoint, seeds durable state through the real write path, runs the binary as a
// separate OS process, and asks it over HTTP what it recovered.
//
// The assertions are deliberately about the process's own report rather than about the
// database: a rebuilt stack is not observable from outside except by what the process says it
// recovered, so the JSON body is the only evidence that the rebuild ran in that process and
// not in this one.
func TestARunningProcessRebuildsItsStackFromPostgreSQLOnStartup(t *testing.T) {
	db := open(t)
	ctx := ctxFor(t)
	truncate(t, ctx, db)

	databaseURL := databaseURLFromEnv(t)

	// Seed through the production assembly, then drain, so the rows the new process finds are
	// rows a real writer wrote rather than rows this test inserted with SQL.
	owner := uniqueOwner()
	partition := owner
	at := time.Date(2026, 3, 4, 5, 6, 7, 0, time.UTC)

	seed := buildStack(t, ctx, db, partition, at)
	modelID := uniqueModelID()
	if _, err := seed.Journal.RegisterContext(
		ctx,
		entryWithOwner(t, modelID, owner, at).Record,
		contracts.ActorSystem,
		"author-identity",
	); err != nil {
		t.Fatalf("seeding a model through the write path: %v", err)
	}
	drain(t, ctx, seed)

	// A revocation the new process can report back, minted and revoked through the real paths
	// so the audit link constraint has an issuance to point at.
	revoked := mintIdentity(t, ctx, seed.Registry, "wld-entrypoint-revoked", at)
	if _, err := seed.Registry.RevokeContext(
		ctx, revoked.Identity,
		"containment: seeded so the restarted process reports a revocation",
		"forensics/2026-03-04/entrypoint-revoked"); err != nil {
		t.Fatalf("revoking the seeded identity: %v", err)
	}
	_ = seed

	binary := buildEntrypoint(t)

	// Port 0 asks the OS for a free port, and the actual port is read from the process's own
	// listener. Hardcoding one would make this test collide with whatever else is running.
	addr := freeAddr(t)
	proc, _ := startEntrypoint(t, binary, databaseURL, addr, partition, t.Logf)
	defer stopEntrypoint(t, proc)

	ready := waitForReady(t, addr, 30*time.Second)

	if got := ready.Partitions; len(got) != 1 || got[0] != partition {
		t.Errorf("the process reports partitions %v, expected exactly [%s]; it was started "+
			"with CONTROL_PLANE_PARTITIONS=%s, so a different answer means the process "+
			"ignored its own configuration", got, partition, partition)
	}
	if ready.Models < 1 {
		t.Errorf("the process recovered %d models from a database holding one registered "+
			"model; a control plane that started with an empty registry would report "+
			"already-registered models as unknown", ready.Models)
	}
	if ready.Revocations < 1 {
		t.Errorf("the process recovered %d revocations from a database holding one; the "+
			"restart would drop the enforcement half of containment", ready.Revocations)
	}
	if ready.Environment != "SIMULATION" {
		t.Errorf("the process reports environment %q, expected SIMULATION; audit records "+
			"were placed there by the writer and must be restored into that placement",
			ready.Environment)
	}
	if !ready.JournalDurable || !ready.RegistryDurable {
		t.Errorf("the process reports journal_durable=%t registry_durable=%t; a process "+
			"serving from memory rather than from PostgreSQL has not rebuilt anything",
			ready.JournalDurable, ready.RegistryDurable)
	}
	// Stated as a field rather than left implicit, because it is the honest limit of this
	// gate: the process rebuilt and reports, but exposes no write path yet.
	if ready.WritePathExposed {
		t.Error("the process reports its write path as exposed; no registration or " +
			"transition handler exists, and claiming otherwise would misreport the gate")
	}

	// Liveness must be independent of dependency state.
	code, body := get(t, "http://"+addr+"/healthz")
	if code != http.StatusOK {
		t.Errorf("GET /healthz returned %d (%s), expected 200", code, body)
	}

	// A wrong method is refused rather than served.
	code, _ = get(t, "http://"+addr+"/readyz")
	if code != http.StatusOK {
		t.Errorf("GET /readyz returned %d before any assertion below, expected 200", code)
	}
	code, _ = post(t, "http://"+addr+"/readyz")
	if code != http.StatusMethodNotAllowed {
		t.Errorf("POST /readyz returned %d, expected 405; the endpoint accepts only reads",
			code)
	}

	// The chain the process rehydrated must be the chain that was written, which is
	// verifiable from outside through the audit rows themselves.
	var auditRows int
	if err := db.QueryRowContext(ctx,
		`SELECT count(*) FROM public.audit_records WHERE partition = $1;`,
		partition).Scan(&auditRows); err != nil {
		t.Fatalf("counting audit rows: %v", err)
	}
	if auditRows == 0 {
		t.Fatal("no audit rows exist for the seeded partition, so the process reported " +
			"having rebuilt from rows that do not exist")
	}
}

// TestTheEntrypointRefusesToStartWithoutItsConfiguration covers the refusals that matter most,
// because a control plane that starts with guessed configuration looks healthy while doing the
// wrong thing.
func TestTheEntrypointRefusesToStartWithoutItsConfiguration(t *testing.T) {
	databaseURL := databaseURLFromEnv(t)
	binary := buildEntrypoint(t)

	for _, tc := range []struct {
		name string
		env  []string
		want string
	}{
		{
			name: "no database url",
			env:  []string{"DATABASE_URL="},
			want: "DATABASE_URL is not set",
		},
		{
			name: "no environment",
			env:  []string{"CONTROL_PLANE_ENVIRONMENT="},
			want: "CONTROL_PLANE_ENVIRONMENT is not set",
		},
		{
			name: "an unbounded guard limit",
			env: []string{
				"DATABASE_URL=" + databaseURL,
				"CONTROL_PLANE_ENVIRONMENT=SIMULATION",
				"CONTROL_PLANE_GUARD_LIMIT=0",
			},
			want: "CONTROL_PLANE_GUARD_LIMIT",
		},
		{
			name: "a non-numeric guard limit",
			env: []string{
				"DATABASE_URL=" + databaseURL,
				"CONTROL_PLANE_ENVIRONMENT=SIMULATION",
				"CONTROL_PLANE_GUARD_LIMIT=lots",
			},
			want: "CONTROL_PLANE_GUARD_LIMIT",
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			addr := freeAddr(t)
			proc, output := startEntrypoint(t, binary, databaseURL, addr, "", t.Logf, tc.env...)

			// The process is expected to exit on its own, so waiting is the assertion rather
			// than a race: if it serves instead, Wait blocks until the test's own deadline and
			// the failure is a timeout with the output attached.
			_ = proc.Wait()
			if code := exitCode(proc.ProcessState); code != 2 {
				t.Errorf("the process exited with code %d, expected 2 (could not start)\n%s",
					code, output.String())
			}
			if !strings.Contains(output.String(), tc.want) {
				t.Errorf("the refusal did not mention %q; it said:\n%s",
					tc.want, output.String())
			}
			// Nothing may be listening: a process that printed a refusal and then served
			// anyway would be worse than one that refused.
			if conn, err := net.DialTimeout("tcp", addr, 200*time.Millisecond); err == nil {
				conn.Close()
				t.Errorf("the process refused to start but something is listening on %s", addr)
			}
		})
	}
}

// TestTheEntrypointRefusesToStartOnARegistryThatHasDriftedFromItsAuditChain pins the
// fail-closed behaviour of the startup path.
//
// The seeded database holds a registered model whose audit record lives in one partition. This
// test starts the process configured for a *different* partition, so it rehydrates a chain that
// does not contain that model's evidence. The journal verifies every model against the chain
// before restoring it, so the rebuild must fail and the process must exit rather than serve a
// registry it could not corroborate.
//
// A process that started anyway would report the model as unregistered, and the caller's
// natural response - register it again - would write a second SUCCEEDED audit record for a
// registration that already happened. This is the failure G5.7 exists to prevent, so it is
// worth a test of its own rather than only the happy path.
func TestTheEntrypointRefusesToStartOnARegistryThatHasDriftedFromItsAuditChain(t *testing.T) {
	db := open(t)
	ctx := ctxFor(t)
	truncate(t, ctx, db)

	databaseURL := databaseURLFromEnv(t)

	owner := uniqueOwner()
	at := time.Date(2026, 3, 4, 5, 6, 7, 0, time.UTC)

	seed := buildStack(t, ctx, db, owner, at)
	if _, err := seed.Journal.RegisterContext(
		ctx,
		entryWithOwner(t, uniqueModelID(), owner, at).Record,
		contracts.ActorSystem,
		"author-identity",
	); err != nil {
		t.Fatalf("seeding: %v", err)
	}
	drain(t, ctx, seed)

	binary := buildEntrypoint(t)
	addr := freeAddr(t)

	// A partition nobody wrote to. The chain comes back empty, the registry does not.
	proc, output := startEntrypoint(t, binary, databaseURL, addr,
		uniqueOwner(), t.Logf)
	_ = proc.Wait()

	if code := exitCode(proc.ProcessState); code != 2 {
		t.Errorf("the process exited with code %d, expected 2; it should refuse to start "+
			"when the registry cannot be corroborated against the audit chain\n%s",
			code, output.String())
	}
	if !strings.Contains(output.String(), "not in the chain") &&
		!strings.Contains(output.String(), "drifted") {
		t.Errorf("the refusal did not name the drift between the registry and the audit "+
			"chain; it said:\n%s", output.String())
	}
	if conn, err := net.DialTimeout("tcp", addr, 200*time.Millisecond); err == nil {
		conn.Close()
		t.Errorf("the process refused to start but something is listening on %s", addr)
	}
}

// The process's own account of what it recovered on startup.
type readyReport struct {
	Status             string   `json:"status"`
	Environment        string   `json:"environment"`
	Models             int      `json:"models"`
	Partitions         []string `json:"partitions"`
	WorkloadIdentities int      `json:"workload_identities"`
	Revocations        int      `json:"revocations"`
	JournalDurable     bool     `json:"journal_durable"`
	RegistryDurable    bool     `json:"registry_durable"`
	WritePathExposed   bool     `json:"write_path_exposed"`
}

// buildEntrypoint compiles cmd/control-plane into the test's own temporary directory.
//
// go build rather than a prebuilt binary from PATH, because the point of this test is that the
// binary is built from the source in this repository. A binary left lying around from an
// earlier run would let a broken source tree pass.
func buildEntrypoint(t *testing.T) string {
	t.Helper()

	out := filepath.Join(t.TempDir(), "control-plane")
	if runtime.GOOS == "windows" {
		out += ".exe"
	}

	// Run from the package directory so the module context resolves without a go.work file.
	cmd := exec.Command("go", "build", "-o", out, "./cmd/control-plane")
	cmd.Dir = ".."
	combined, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("building cmd/control-plane: %v\n%s", err, combined)
	}
	return out
}

// freeAddr reserves a loopback port and reports the address it was given.
//
// The listener is closed before the address is handed on, which leaves a small window in which
// something else could take it. That is accepted rather than worked around: the alternative is
// a fixed port that fails the moment two tests run at once, and this suite is parallel-safe by
// construction elsewhere.
func freeAddr(t *testing.T) string {
	t.Helper()

	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("reserving a port: %v", err)
	}
	addr := listener.Addr().String()
	if err := listener.Close(); err != nil {
		t.Fatalf("releasing the reserved port: %v", err)
	}
	return addr
}

// startEntrypoint runs the binary as a separate OS process, returning it and the buffer its
// output is written to.
//
// The buffer is returned rather than swallowed because the refusals are asserted against what
// the process printed: "it did not start" is only useful evidence if the reason is also
// visible, and a silent exit code 2 would be a worse failure than a crash.
func startEntrypoint(
	t *testing.T,
	binary, databaseURL, addr, partition string,
	logf func(string, ...any),
	overrides ...string,
) (*exec.Cmd, *strings.Builder) {
	t.Helper()

	cmd := exec.Command(binary)
	cmd.Env = append(
		// Stripped rather than appended-to. os.Environ() already carries the suite's own
		// DATABASE_URL and CONTROL_PLANE_* values, and on Windows a duplicated variable does
		// not override the earlier one the way it does on POSIX - so appending "DATABASE_URL="
		// to *unset* it left the child with a working database, and two refusal cases
		// silently tested the wrong thing.
		withoutEnv(os.Environ(), "DATABASE_URL", "CONTROL_PLANE_ENVIRONMENT",
			"CONTROL_PLANE_ADDR", "CONTROL_PLANE_GUARD_LIMIT",
			"CONTROL_PLANE_PARTITIONS", "CONTROL_PLANE_STARTUP_TIMEOUT",
			"CONTROL_PLANE_SHUTDOWN_TIMEOUT"),
		"DATABASE_URL="+databaseURL,
		"CONTROL_PLANE_ENVIRONMENT=SIMULATION",
		"CONTROL_PLANE_ADDR="+addr,
	)
	if partition != "" {
		cmd.Env = append(cmd.Env, "CONTROL_PLANE_PARTITIONS="+partition)
	}
	// Overrides are applied by re-filtering, so a case that replaces a variable this helper
	// already set genuinely replaces it rather than depending on append-order precedence. An
	// override with an empty value unsets the variable entirely, which is what the "missing
	// configuration" cases need: the child must see it absent, not set to "".
	for _, override := range overrides {
		name, value, _ := strings.Cut(override, "=")
		cmd.Env = withoutEnv(cmd.Env, name)
		if value != "" {
			cmd.Env = append(cmd.Env, override)
		}
	}

	output := &strings.Builder{}
	cmd.Stdout = output
	cmd.Stderr = output
	if err := cmd.Start(); err != nil {
		t.Fatalf("starting the entrypoint: %v", err)
	}

	t.Cleanup(func() {
		if s := output.String(); s != "" {
			logf("entrypoint output:\n%s", s)
		}
	})
	return cmd, output
}

// waitForReady polls /readyz until the process reports readiness, then returns its report.
//
// Polling rather than sleeping a fixed interval: the process must not be assumed to have
// finished starting when the test begins looking, or the test would be asserting about a
// process that had not rehydrated yet.
func waitForReady(t *testing.T, addr string, within time.Duration) readyReport {
	t.Helper()

	deadline := time.Now().Add(within)
	var last string
	for time.Now().Before(deadline) {
		code, body := get(t, "http://"+addr+"/readyz")
		if code == http.StatusOK {
			var report readyReport
			if err := json.Unmarshal([]byte(body), &report); err != nil {
				t.Fatalf("readiness body is not the expected JSON: %v\n%s", err, body)
			}
			return report
		}
		last = fmt.Sprintf("status %d: %s", code, body)
		time.Sleep(100 * time.Millisecond)
	}

	t.Fatalf("the entrypoint did not become ready within %s; last response was %s", within, last)
	return readyReport{}
}

// get issues a GET and returns the status code and body.
func get(t *testing.T, url string) (int, string) {
	t.Helper()
	return do(t, http.MethodGet, url)
}

// post issues a POST and returns the status code and body.
func post(t *testing.T, url string) (int, string) {
	t.Helper()
	return do(t, http.MethodPost, url)
}

func do(t *testing.T, method, url string) (int, string) {
	t.Helper()

	req, err := http.NewRequest(method, url, nil)
	if err != nil {
		t.Fatalf("building %s %s: %v", method, url, err)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return 0, err.Error()
	}
	defer resp.Body.Close()

	buf := make([]byte, 8192)
	n, _ := resp.Body.Read(buf)
	return resp.StatusCode, string(buf[:n])
}

// stopEntrypoint terminates a process started by this test.
//
// Kill rather than an interrupt signal, so the graceful drain is not what is being exercised
// here. That limitation is real and is not papered over: on Windows os.Process.Signal does not
// deliver os.Interrupt to another process, so the SIGTERM drain path cannot be proven by a test
// on this platform and is exercised only by an operator's actual shutdown.
func stopEntrypoint(t *testing.T, cmd *exec.Cmd) {
	t.Helper()

	if cmd.Process == nil {
		return
	}
	_ = cmd.Process.Kill()
	_, _ = cmd.Process.Wait()
}

// withoutEnv returns env with every entry for the named variable removed.
//
// Used instead of relying on append-order precedence when building a child's environment,
// because that precedence differs between Windows and POSIX and a test that depends on it
// passes on one platform and silently asserts nothing on the other.
func withoutEnv(env []string, names ...string) []string {
	drop := make(map[string]bool, len(names))
	for _, n := range names {
		drop[n] = true
	}

	out := make([]string, 0, len(env))
	for _, entry := range env {
		name, _, _ := strings.Cut(entry, "=")
		if !drop[name] {
			out = append(out, entry)
		}
	}
	return out
}

// exitCode extracts a process exit code from a finished process.
//
// A nil state means the process was never reaped, which is reported as -1 rather than 0: the
// two mean opposite things here, and collapsing them would let an unreaped process read as a
// clean exit.
func exitCode(state *os.ProcessState) int {
	if state == nil {
		return -1
	}
	return state.ExitCode()
}

// databaseURLFromEnv returns the DSN this suite is already using.
func databaseURLFromEnv(t *testing.T) string {
	t.Helper()

	url := strings.TrimSpace(os.Getenv("DATABASE_URL"))
	if url == "" {
		t.Skip("DATABASE_URL is not set; this suite requires a live PostgreSQL")
	}
	return url
}
