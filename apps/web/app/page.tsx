import styles from "./page.module.css";

/**
 * Operator console — home.
 *
 * Authority boundary
 * ------------------
 * This component is presentation only. It renders what the Go control plane reports and
 * it can request actions, but it cannot establish authorization, risk approval, order
 * state, or a financial balance. Every privileged action is authorized server-side
 * (docs/02_POLYGLOT_ENGINEERING_STANDARD.md, docs/25 section 3.6).
 *
 * The data below is currently a static projection of verified state, not a live control
 * plane response. The control plane does not exist yet, and the console says so rather
 * than rendering a plausible-looking dashboard over nothing. When the API lands, these
 * values move behind a server-side fetch; nothing else about the component changes.
 */

type Tone = "idle" | "ok" | "warn" | "danger";

/**
 * `pending-attestation` is deliberately distinct from `evidence-verified`.
 *
 * A gate whose mechanical checks all pass but which still needs a named reviewer to sign
 * it off is not a passing gate. docs/11 is explicit that partial completion is FAIL and
 * that no gate may be marked passed on documentation alone, so collapsing these two states
 * into one green pill would misreport the real control status on the operator's screen.
 */
type GateState = "not-started" | "evidence-verified" | "pending-attestation" | "out-of-scope";

const TONE_CLASS: Record<Tone, string> = {
  idle: styles.pillIdle ?? "",
  ok: styles.pillOk ?? "",
  warn: styles.pillWarn ?? "",
  danger: styles.pillDanger ?? "",
};

const STATE_TONE: Record<GateState, Tone> = {
  "not-started": "idle",
  "evidence-verified": "ok",
  "pending-attestation": "warn",
  "out-of-scope": "danger",
};

const STATE_LABEL: Record<GateState, string> = {
  "not-started": "Not started",
  "evidence-verified": "Evidence verified",
  "pending-attestation": "Pending attestation",
  "out-of-scope": "Out of scope",
};

interface Gate {
  id: string;
  name: string;
  state: GateState;
  detail: string;
}

const GATES: readonly Gate[] = [
  {
    id: "G0",
    name: "Specification integrity",
    state: "pending-attestation",
    detail:
      "All 7 mechanical criteria pass: 26/26 documents present, byte lengths and SHA-256 " +
      "digests match, no unlisted or legacy documents, all 25 ADRs accepted. Gate report " +
      "filed at evidence/gates/. Not passed: a named human reviewer has not attested the " +
      "package, so this gate is not marked verified.",
  },
  {
    id: "G1",
    name: "Domain foundation",
    state: "not-started",
    detail: "Canonical types, envelopes, idempotency, migrations, domain tests.",
  },
  {
    id: "G2",
    name: "Market data",
    state: "not-started",
    detail: "Normalized instruments, feed health, freshness, provenance, replayable ingest.",
  },
  {
    id: "G3",
    name: "Trading core",
    state: "not-started",
    detail: "Risk gate, OMS state machine, order invariants, halt, ledger, reconciliation.",
  },
  { id: "G4", name: "Research", state: "not-started", detail: "Versioned datasets, deterministic backtests." },
  { id: "G5", name: "AI company OS", state: "not-started", detail: "Model registry, decision ledger, tool permissions." },
  { id: "G6", name: "Simulation and shadow", state: "not-started", detail: "Realistic execution, fault injection, performance." },
  { id: "G7", name: "Operator interfaces", state: "not-started", detail: "Web and Telegram on one authorization path." },
  { id: "G8", name: "Venue adapters", state: "not-started", detail: "Contract tests, precision, rate limits, failure modes." },
  { id: "G9", name: "Security and operations", state: "not-started", detail: "Scans, secrets isolation, observability, recovery drills." },
  { id: "G10", name: "Production readiness", state: "not-started", detail: "Release evidence, capacity, verified rollback." },
  {
    id: "G11",
    name: "Live activation",
    state: "out-of-scope",
    detail: "Requires legal eligibility, isolated live credentials, and two distinct approvers.",
  },
];

/** The authority hierarchy from docs/01 section 3, in precedence order. */
const AUTHORITY = [
  { name: "Operator approval", rule: "Controls activation and high-impact configuration." },
  { name: "Risk Engine", rule: "The authoritative financial veto. Deterministic and final." },
  { name: "OMS", rule: "Authoritative for canonical internal order state." },
  { name: "Reconciliation", rule: "Authoritative for resolving venue discrepancies." },
  { name: "Ledger", rule: "Authoritative for financial facts, via append-only entries." },
  { name: "Strategy and AI", rule: "Propose actions only. Never authorize execution." },
  { name: "This interface", rule: "Presentation only. No financial authority whatsoever." },
] as const;

function GatePill({ state }: { state: GateState }) {
  return (
    <span className={`${styles.pill} ${TONE_CLASS[STATE_TONE[state]]}`}>
      <span className={styles.dot} aria-hidden="true" />
      {STATE_LABEL[state]}
    </span>
  );
}

export default function Home() {
  const verified = GATES.filter((g) => g.state === "evidence-verified").length;
  const remaining = GATES.length - verified - GATES.filter((g) => g.state === "out-of-scope").length;

  return (
    <div className={styles.shell}>
      <header className={styles.masthead}>
        <h1 className={styles.brand}>
          web-trade
          <span className={styles.brandSub}>Operator Console</span>
        </h1>
        <span className={`${styles.pill} ${styles.pillIdle}`}>
          <span className={styles.dot} aria-hidden="true" />
          Control plane: not connected
        </span>
      </header>

      {/*
        The most important fact on this page. It is first, it is the loudest element, and
        it is not dismissible. Live capability is deny-by-default and stays disabled until
        G0-G11 pass with evidence (docs/25 section 3.7, docs/11 G11).
      */}
      <section className={styles.banner} aria-labelledby="live-disabled-heading">
        <span className={styles.bannerIcon} aria-hidden="true">
          ■
        </span>
        <div>
          <div className={styles.bannerTitle} id="live-disabled-heading">
            Live trading is disabled
          </div>
          <p className={styles.bannerBody}>
            This platform holds no live capability. Live mode cannot be enabled without
            verified legal eligibility, isolated live credentials, two-person approval, and
            passing release gates. No setting in this interface can bypass that.
          </p>
        </div>
      </section>

      <section className={styles.panel} aria-labelledby="gates-heading">
        <div className={styles.panelHead}>
          <h2 className={styles.panelTitle} id="gates-heading">
            Release gates
          </h2>
          <span className={styles.panelNote}>
            {verified} of {remaining + verified} in scope &middot; G11 excluded
          </span>
        </div>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <caption className="sr-only">
              Execution gate status. A gate is pass or fail; partial completion is a
              failure, and no gate may be marked passed on documentation alone.
            </caption>
            <thead>
              <tr>
                <th scope="col">Gate</th>
                <th scope="col">Name</th>
                <th scope="col">Status</th>
                <th scope="col">Scope</th>
              </tr>
            </thead>
            <tbody>
              {GATES.map((gate) => (
                <tr key={gate.id}>
                  <th scope="row" className={styles.gateId}>
                    {gate.id}
                  </th>
                  <td>{gate.name}</td>
                  <td>
                    <GatePill state={gate.state} />
                  </td>
                  <td className={styles.chainRule}>{gate.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className={styles.panel} aria-labelledby="authority-heading">
        <div className={styles.panelHead}>
          <h2 className={styles.panelTitle} id="authority-heading">
            Authority hierarchy
          </h2>
          <span className={styles.panelNote}>Highest precedence first</span>
        </div>
        <div className={styles.panelBody}>
          <ol className={styles.chain}>
            {AUTHORITY.map((entry, index) => (
              <li key={entry.name}>
                <span className={styles.chainIndex} aria-hidden="true">
                  {index + 1}
                </span>
                {/*
                  The name and the rule are one text flow with a visual line break between
                  them, rather than two spans joined by <br>. A <br> makes assistive
                  technology read "Operator approvalControls activation..." with no pause,
                  which is materially worse than it sounds.
                */}
                <p className={styles.chainItem}>
                  <span className={styles.chainName}>{entry.name}</span> {entry.rule}
                </p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <p className={styles.callout}>
        This interface is an untrusted client. It may request actions and render
        authoritative responses, but it cannot establish authorization, risk approval, order
        state, or financial balances. Every value shown here originates from the Go control
        plane; none of it is computed in the browser.
      </p>

      <footer className={styles.footer}>
        Specification authority: <code className="mono">docs/</code> (26 documents,
        digest-verified). The console is not an authority for any value it displays.
      </footer>
    </div>
  );
}
