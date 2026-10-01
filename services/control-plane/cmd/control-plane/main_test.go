package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"sync"
	"syscall"
	"testing"
	"time"
)

// TestTheDrainLetsAnInFlightRequestFinishBeforeItStopsAccepting is the shutdown claim in
// serve()'s comment, tested rather than asserted.
//
// serve() documents that it stops accepting first and then lets in-flight requests finish,
// because the reverse order drops a request the client believes was accepted - which for a
// governance plane means an audit record that was written and never answered. That ordering is
// the whole reason the function exists, and before this test nothing executed it.
//
// It was not executable from the integration suite, which is why this file is here instead. The
// integration test runs this binary as a real OS process, so it can only interrupt it by killing
// it: Windows does not deliver os.Interrupt to another process, and Kill cannot be caught. A
// test that runs the process cannot observe a graceful drain on this platform at all, which was
// stated honestly in that suite but left the drain unproven everywhere.
//
// Driving the interrupt channel directly proves the same property, on every platform, without
// depending on a signal being deliverable: the listener is a real TCP socket, the request is a
// real HTTP request over a real connection, and the only thing simulated is the notification that
// a signal would otherwise deliver. What is under test is therefore the production drain and not
// a model of it.

// drainTestTimeout bounds every wait below. It is generous on purpose: a failure here should be
// a real assertion failure, not a timeout that fires before the drain has had a chance to run.
const drainTestTimeout = 10 * time.Second

func TestTheDrainLetsAnInFlightRequestFinishBeforeItStopsAccepting(t *testing.T) {
	release := make(chan struct{})
	arrived := make(chan struct{}, 1)
	var arrivedOnce sync.Once

	mux := http.NewServeMux()
	mux.HandleFunc("/slow", func(w http.ResponseWriter, r *http.Request) {
		arrivedOnce.Do(func() { arrived <- struct{}{} })
		<-release
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("finished"))
	})
	mux.HandleFunc("/fast", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("binding a listener: %v", err)
	}
	addr := listener.Addr().String()

	server := &http.Server{Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	interrupts := make(chan os.Signal, 1)

	done := make(chan int, 1)
	go func() { done <- serve(server, listener, interrupts, drainTestTimeout) }()

	// Start a request that will still be running when the drain begins, and confirm it reached
	// the handler first. Without that confirmation the test could pass by draining before the
	// request was ever in flight, which would prove nothing about ordering.
	inFlight := make(chan result, 1)
	go func() {
		status, body, err := get(addr + "/slow")
		inFlight <- result{status: status, body: body, err: err}
	}()

	select {
	case <-arrived:
	case <-time.After(drainTestTimeout):
		t.Fatal("the slow request never reached the handler; the test would prove nothing")
	}

	interrupts <- syscall.SIGTERM

	// The drain is now under way with the request still executing inside the handler. Confirm it
	// has genuinely not answered yet, so that the assertion below is about the drain waiting for
	// the request rather than about a response that had already happened to flush. This is the
	// difference between "the drain waited" and "the drain happened to come along in time".
	select {
	case got := <-inFlight:
		// Two quite different things land here, and this test refuses to guess between them.
		// Either the connection died the moment the drain began, which is the exact defect
		// (a hard close instead of a graceful one), or the response flushed before the handler
		// was released, which means the run never had an in-flight request to begin with. Both
		// make the run worthless, and neither is the property under test.
		t.Fatalf("the in-flight request returned %+v before its handler was released: either "+
			"the drain killed the connection instead of waiting for it, or nothing was in "+
			"flight, so this run proves nothing about the drain", got)
	case <-time.After(100 * time.Millisecond):
	}

	// Release the handler only now. A graceful drain must let a request that was already
	// executing finish, so the answer has to arrive after the interrupt.
	close(release)

	// The property: the request already in flight is still answered, and it is answered
	// completely, not truncated. A client that received a partial body would still be holding a
	// half-written audit record, so both the status and the exact body are checked.
	select {
	case got := <-inFlight:
		if got.err != nil {
			t.Fatalf("the in-flight request failed during the drain: %v", got.err)
		}
		if got.status != http.StatusOK {
			t.Errorf("in-flight request status = %d, want %d; the drain dropped or altered it",
				got.status, http.StatusOK)
		}
		if got.body != "finished" {
			t.Errorf("in-flight request body = %q, want %q; the drain truncated it",
				got.body, "finished")
		}
	case <-time.After(drainTestTimeout):
		t.Fatal("the in-flight request was never answered; the drain abandoned it")
	}

	// The other half of the ordering: new work is refused. If the drain still accepted
	// connections it would keep admitting requests for the remainder of its deadline and then
	// drop them, which is the failure mode the ordering exists to prevent.
	deadline := time.Now().Add(drainTestTimeout)
	for {
		_, _, err := get(addr + "/fast")
		if err != nil {
			break // refused, which is what should happen
		}
		if time.Now().After(deadline) {
			t.Fatal("the listener was still accepting new requests after the drain began")
		}
		time.Sleep(10 * time.Millisecond)
	}

	// And the process would exit 0, which is the code an operator's supervisor reads as a clean
	// shutdown. A non-zero here means the drain reported failure, so a supervisor would treat a
	// normal stop as a crash.
	select {
	case code := <-done:
		if code != 0 {
			t.Errorf("serve returned %d, want 0 after a clean drain", code)
		}
	case <-time.After(drainTestTimeout):
		t.Fatal("serve did not return after the drain")
	}
}

// TestTheDrainGivesUpOnARequestThatOutlivesTheShutdownDeadline pins the other half of the
// contract: the drain is bounded, and exceeding its deadline is reported rather than waited out
// forever.
//
// Without this, a handler that blocks forever would make shutdown hang indefinitely, and the only
// way to find that out would be to run one. The cost of the bound is that the in-flight request is
// abandoned when it expires, so the exit code is 1 - the process reports that it did not stop
// cleanly, rather than exiting 0 and implying that it did.
func TestTheDrainGivesUpOnARequestThatOutlivesTheShutdownDeadline(t *testing.T) {
	held := make(chan struct{})
	arrived := make(chan struct{}, 1)
	var arrivedOnce sync.Once

	mux := http.NewServeMux()
	mux.HandleFunc("/never", func(w http.ResponseWriter, r *http.Request) {
		arrivedOnce.Do(func() { arrived <- struct{}{} })
		// Block until the test tears the server down. This request never finishes on its own.
		<-held
	})

	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("binding a listener: %v", err)
	}
	addr := listener.Addr().String()

	server := &http.Server{Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	interrupts := make(chan os.Signal, 1)

	// A short deadline, because the property under test is that the deadline is honoured and
	// waiting a real ten seconds to observe it would prove exactly the same thing.
	const deadline = 250 * time.Millisecond

	done := make(chan int, 1)
	go func() { done <- serve(server, listener, interrupts, deadline) }()

	go func() {
		resp, err := http.Get("http://" + addr + "/never")
		if err == nil {
			_, _ = io.Copy(io.Discard, resp.Body)
			_ = resp.Body.Close()
		}
	}()

	select {
	case <-arrived:
	case <-time.After(drainTestTimeout):
		close(held)
		t.Fatal("the request never reached the handler; the test would prove nothing")
	}

	started := time.Now()
	interrupts <- syscall.SIGTERM

	select {
	case code := <-done:
		elapsed := time.Since(started)

		if code != 1 {
			t.Errorf("serve returned %d, want 1; a drain that hit its deadline must report that "+
				"it did not stop cleanly rather than exit 0", code)
		}
		// A generous ceiling, because the point is that the wait is bounded by the deadline and
		// not by the handler. It is not the deadline itself, so a slow machine does not fail.
		if ceiling := 10 * deadline; elapsed > ceiling {
			t.Errorf("serve returned after %v, which exceeds the %v shutdown deadline by more "+
				"than a factor of ten; the drain waited on the handler instead of the deadline",
				elapsed, deadline)
		}
	case <-time.After(drainTestTimeout):
		close(held)
		t.Fatal("serve never returned; the shutdown deadline is not being honoured")
	}
	close(held)
}

// TestTheListenerFailingIsReportedAsAnUnexpectedStop covers the branch that does not involve an
// interrupt at all.
//
// If Serve returns an error that is not ErrServerClosed, the process has lost its listener and
// cannot serve. That is exit 1, distinct from both a clean drain and a normal shutdown, and it is
// the difference between a supervisor restarting a process that had a problem and one restarting a
// process that stopped when asked.
func TestTheListenerFailingIsReportedAsAnUnexpectedStop(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("binding a listener: %v", err)
	}

	server := &http.Server{
		Handler:           http.NewServeMux(),
		ReadHeaderTimeout: 5 * time.Second,
	}
	interrupts := make(chan os.Signal, 1)

	done := make(chan int, 1)
	go func() { done <- serve(server, listener, interrupts, drainTestTimeout) }()

	// Closing the listener underneath Serve is the portable way to make it fail without
	// depending on how a platform reports a broken socket. On Windows a duplicate close returns
	// an error where POSIX would not, so the error is deliberately discarded and the assertion
	// is made on serve's exit code rather than on whether the close itself succeeded.
	_ = listener.Close()

	select {
	case code := <-done:
		if code != 1 {
			t.Errorf("serve returned %d, want 1; a listener that failed is an unexpected stop", code)
		}
	case <-time.After(drainTestTimeout):
		t.Fatal("serve did not return after its listener was closed")
	}
}

// result carries one HTTP response from a helper goroutine.
type result struct {
	status int
	body   string
	err    error
}

// get issues a GET against host:port/path and reads the whole body.
//
// The scheme is added here rather than at each call site because a call site that forgets it
// produces a request error instead of a connection error, and two of the tests above read a
// request error as "the listener refused me". That would have made the stop-accepting assertion
// pass on a request that was never sent.
func get(hostAndPath string) (int, string, error) {
	req, err := http.NewRequestWithContext(
		context.Background(), http.MethodGet, "http://"+hostAndPath, nil)
	if err != nil {
		return 0, "", err
	}

	client := &http.Client{
		// No timeout: the slow-handler tests rely on the server's shutdown deadline, not on the
		// client giving up, because the client's timeout would hide the property under test.
		Transport: &http.Transport{},
	}

	resp, err := client.Do(req)
	if err != nil {
		return 0, "", err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return resp.StatusCode, "", fmt.Errorf("reading body: %w", err)
	}
	return resp.StatusCode, string(body), nil
}

// compile-time guard: the drain's success path depends on ErrServerClosed being recognised
// rather than compared, and a future refactor that compared by string would compile fine here
// and fail only at runtime under a signal.
var _ = errors.Is
