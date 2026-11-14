# **Bitemporal Modeling, Provenance Schemas, and Incremental Retraction on SQLite**

Modeling evolving, source-attributed knowledge in an embedded relational database requires separating *when a claim held true in the domain* from *when the database recorded it*—and, in distributed pipelines, *when an upstream agent observed it*—while refusing to overwrite historical assertions in place1. By adopting XTDB's minimal append-only tuple layout—storing system\_from, valid\_from, and valid\_to while omitting system\_to—a SQLite database avoids retroactive interval splitting on write and reconstructs any historical epistemic state via reverse-system-time playback and ceiling-interval materialization2. Layering relational provenance modeled on W3C PROV-O responsibility roles, why-provenance, and provenance semirings onto that log enables downstream derived claims to trace their supporting witness sets and undergo deterministic belief retraction through Counting or Delete-and-Rederive (DRed) maintenance when upstream sources change or disappear7.  
Because SQLite lacks native SQL:2011 temporal tables and stores data in row-oriented B-trees rather than column-oriented Apache Arrow segments, executing reverse-system-time playback on every current-state query incurs avoidable scan overhead2. Rather than relying on a single prebuilt production SQLite temporal engine—no reviewed production SQLite codebase combines full bitemporality, PROV-O lineage, and DRed maintenance out of the box—architects can synthesize proven production primitives from duckpipe, sqlite-history, dbward, curia, and cr-sqlite: locking an append-only rowid observation log (JSONB payloads in STRICT tables) with modification-blocking triggers while maintaining narrow WITHOUT ROWID current-state projection tables via AFTER INSERT triggers and constrained partial indexes13. Inspection on SQLite 3.46.1 also highlights two critical planner and storage pitfalls that break naive temporal schemas: open-ended (valid\_to IS NULL OR valid\_to \> t) predicates prevent B-tree upper-bound seeks on valid\_to, and standard rtree virtual tables store 32-bit floats that quantize a 1 s interval at 2026 Unix epoch seconds into a 256.0 s span and a 500 ms interval into a 262,144.0 ms span15.  
Two evidentiary boundaries frame these recommendations. First, although an XTDB engineering post reports substantial SELECT and UPDATE speedups (titled around 40x query performance) from temporal metadata pruning and valid-time clamping6, and DRedMTL authors report orders-of-magnitude gains over full rematerialization on tested datasets26, no independent benchmark compares SQLite trigger-projected bitemporal tables against native bitemporal engines or commercial SQL:2011 databases; published temporal benchmarks such as Kaufmann et al. (EDBT 2014\) predate SQLite STRICT (documented 2021\) and JSONB (released 2024\)19. Second, the available W3C PROV-O documentation formally defines prov:Agent (referencing entities and activities) without providing standalone class or property axioms for prov:Entity, prov:Activity, prov:wasDerivedFrom, or prov:wasInvalidatedBy7; accordingly, the provenance schema below translates PROV-O's responsibility model using formal database provenance theory (why-provenance and provenance semirings) rather than claiming verbatim OWL compliance7.

## **Bitemporal Semantics and the Valid-Time vs. System-Time Split**

The core distinction in temporal database theory separates *valid time*—the interval during which a fact is true in modeled reality—from *transaction time* (termed *system time* in SQL:2011 and XTDB, or *record time* in domain engineering)—the interval during which a fact is stored and current in the database1. Jensen, Snodgrass, and collaborators established this taxonomy in the *Consensus Glossary of Temporal Database Concepts* (1993–1998) and the Bitemporal Conceptual Data Model (BCDM), specifying that valid times are user- or domain-supplied and freely retroactive or scheduled, whereas transaction time is system-maintained, monotonically advancing, and bounded by the present3. As Tom Johnston and Randall Weis detail in *Managing Time in Relational Databases* (2010) and Tom Johnston expands in *Bitemporal Data* (2014), conventional version and history tables—as well as Kimball Type 2 Slowly Changing Dimensions (SCD2)—collapse real-world state transitions and retrospective error corrections onto a single timeline, making it impossible to answer both "what was true on April 1?" and "on October 15, what did our database claim was true on April 1?"27. Practitioners remain divided on when full bitemporality justifies its complexity: in analytical engineering discussions, some argue standard warehouse snapshots effectively capture transaction/recorded time and suffice when retroactive reporting changes are unwanted36, and Martin Fowler notes that storing explicit calculation traces can sometimes satisfy audit requirements more simply than a fully bitemporal model29.

| Temporal Axis / Construct | Academic & Industry Lineage | Mutability & Authority | Primary Query Answered | Modeling Pitfalls & Tradeoffs |
| :---- | :---- | :---- | :---- | :---- |
| Valid time (application / business / effective time) | Consensus Glossary (1993–1998); SQL:2011 application-period entities; Martin Fowler (*Effectivity*)1 | User- or domain-supplied; supports backdated corrections and future effectivity1 | "What was true in the external domain during period \[t1, t2)?"3 | Overwriting in place loses audit lineage when late facts arrive1 |
| System time (transaction / record time) | Consensus Glossary; SQL:2011 (SYSTEM\_TIME); XTDB1 | System-assigned at commit; strictly append-only and non-retroactive4 | "What state did the database hold as of commit instant T?"1 | Confusing SCD2 capture timestamps with valid time conflates corrections and domain changes33 |
| Observation / decision time (tritemporal third axis) | Wikipedia *Temporal database* (tritemporal model); Asserted Versioning Framework (*assertion time*)4 | External actor or decision timestamp; may precede database commit4 | "When did an upstream source observe or decide a claim prior to ingestion lag?"4 | Collapsing network or batch lag into system\_time misaligns cross-system audits4 |
| Bitemporal event records (1 µs valid duration) | XTDB v1/v2 ingestion taxonomy & event modeling12 | Immutable instant or short bounded period (1 µs) appended at system\_from12 | "Which telemetry or feed observations arrived out of order?"38 | Using 1 µs events for continuous state forces downstream coalescing or window joins12 |

For event-sourced provenance pipelines—where sensors, web scrapers, or partner feeds operate across unreliable networks—*observation time* sits conceptually between domain valid time and local SQLite commit time4. Academic literature captures this intermediate boundary as *decision time* in tritemporal schemas (for example, modeling an assumed 7-day delay between an election decision and database registration), while Johnston's Asserted Versioning Framework extends transaction time into *assertion time* to handle deferred and future assertions4. On SQLite, keeping the storage timeline cleanly bitemporal means binding system\_from strictly to the local transaction commit order and recording upstream observation timestamps (observed\_at\_us) on the provenance ingestion activity—adding a third indexed temporal axis only when audit queries must replay upstream decision states independently of local commit timestamps4.  
Two long-standing debates from the relational temporal literature directly govern SQLite schema semantics. First, although ideas from Richard Snodgrass's TSQL2 proposal influenced the SQL:2011 standard (ISO/IEC 9075-2:2011, surveyed by Krishna Kulkarni and Jan-Eike Michels in *SIGMOD Record*, 2012\)27, SQL:2011 departed substantially from TSQL2 by eliminating hidden temporal columns4, and TSQL2 edge cases drew formal critique from C. J. Date and Hugh Darwen alongside their first-principles relational treatment with Nikos Lorentzos in *Time and Relational Theory* (2014)27. Explicit timestamp columns in SQLite align naturally with SQL:2011 transparency while avoiding hidden-column magic. Second, Michael Böhlen, Richard Snodgrass, and Michael Soo (TimeCenter TR-9, 1996\) demonstrated that *uncoalesced* relations—where value-equivalent tuples hold adjacent (meet in Allen's 1983 interval algebra) or overlapping intervals—produce different results under duration predicates, such as selecting presidents serving over six years when two consecutive four-year terms remain unmerged30. Because coalescing relies on inequality interval comparisons that degrade toward quadratic scans on conventional B-trees40, SQLite provenance stores should preserve uncoalesced source-attributed rows in the raw observation log (never merging distinct upstream agents) and materialize coalesced or active beliefs into projection tables on write.

## **Reverse-System-Time Resolution and Interval Materialization**

Persisting closed bitemporal intervals (system\_from, system\_to, valid\_from, valid\_to) directly in SQL rows creates heavy write amplification and breaks append-only storage2. As XTDB's engineering series (*Building a Bitemporal Index, Part 2: Resolution*) demonstrates, inserting a retroactive correction at T4 for valid time \[T2, T4) over prior assertions (v1 valid \[T1, ∞) inserted at T1, and v2 valid \[T3, ∞) inserted at T3) forces a closed-interval table to update existing rows to close system\_to at T4 and fracture \[T1, ∞) into three separate bitemporal rows (\[T1, T2), \[T2, T4), and \[T4, ∞))2.  
XTDB avoids write-time interval splitting by storing only the minimal append-only log tuple (entity\_id, valid\_from, valid\_to, system\_from, payload) and omitting system\_to entirely2. Because system\_from records exact transaction order, system\_to is implicitly determined by later overlapping events2. Queries resolve entity state by replaying each entity's events in **reverse system\_from order**2. For point-in-time lookups (ST \<= t\_sys, VT \= t\_val), including the common "as of now" query, the engine scans backward from t\_sys and **terminates immediately on the first row whose \[valid\_from, valid\_to) interval covers t\_val**—earlier writes in system time cannot supersede a later write covering the same valid-time point, allowing older history rows to remain unread2.  
When an audit or analytical query requests an entity's complete valid-time timeline or full 2D bitemporal surface (FOR ALL SYSTEM\_TIME FOR ALL VALID\_TIME), XTDB constructs non-overlapping rectangles in a single backward sweep using a **ceiling** map across valid time2. For each valid-time partition, ceiling holds the upper system\_time bound not yet obscured by newer observations, initialized to ∞ over (-∞, ∞)2. Each event encountered during reverse system\_from playback splits or intersects overlapping ceiling partitions, emits one resolved rectangle \[system\_from, ceiling\_st) × \[vt\_sub\_from, vt\_sub\_to) per overlapped partition, and lowers ceiling to system\_from across its valid-time span2.

| Backward Step (system\_from) | Log Entry (VT, Version) | ceiling Before Event | Emitted Bitemporal Rectangles (ST × VT \-\> Version) | Updated ceiling Across VT |
| :---- | :---- | :---- | :---- | :---- |
| Init (\> T4) | — | (-∞, ∞): ∞ | — | (-∞, ∞): ∞2 |
| 1\. T4 | \[T2, T4), v1.5 | (-∞, ∞): ∞ | \[T4, ∞) × \[T2, T4) \-\> v1.5 | (-∞, T2): ∞; \[T2, T4): T4; \[T4, ∞): ∞2 |
| 2\. T3 | \[T3, ∞), v2 | \[T2, T4): T4; \[T4, ∞): ∞ | \[T3, T4) × \[T3, T4) \-\> v2; \[T3, ∞) × \[T4, ∞) \-\> v2 | (-∞, T2): ∞; \[T2, T3): T4; \[T3, ∞): T32 |
| 3\. T1 | \[T1, ∞), v1 | \[T1, T2): ∞; \[T2, T3): T4; \[T3, ∞): T3 | \[T1, ∞) × \[T1, T2) \-\> v1; \[T1, T4) × \[T2, T3) \-\> v1; \[T1, T3) × \[T3, ∞) \-\> v1 | (-∞, T1): ∞; \[T1, ∞): T12 |

To prune storage blocks during historical and current reads without persisting system\_to, XTDB stores file- and page-level min/max metadata (valid\_from, valid\_to, system\_from) alongside **Recency**—defined as the maximum timestamp T for which an event was believed valid for both valid-time \= T and system-time \= T—and clamps valid-time predicates during queries and FOR PORTION OF VALID\_TIME updates so execution skips irrelevant periods6. Because SQLite executes row-store B-trees rather than Arrow files with custom page metadata, SQLite achieves fast current-state reads (VT \= ST \= now) through O(log N) primary-key lookups against a materialized projection table while retaining the system\_from-only claim\_observations log for reverse-system\_from historical resolution2.

## **Event-Sourced Provenance Schemas and W3C PROV-O Patterns on SQLite**

Attributing bitemporal claims to upstream sources and derivation pipelines connects semantic provenance standards to relational algebra. In the available W3C PROV-O specification text, prov:Agent is formally defined as something bearing responsibility for an activity taking place, for the existence of an entity, or for another agent's activity7. Because that source text does not supply the standalone class or property axioms for prov:Entity, prov:Activity, prov:wasDerivedFrom, or prov:wasInvalidatedBy7, our relational provenance design pairs PROV-O's agent–activity–entity responsibility pattern with established database provenance theory: Buneman, Khanna, and Tan's *why*\-provenance (2001) and Green, Karvounarakis, and Tannen's *provenance semirings* (PODS 2007 and 2017; implemented practically in ProvSQL)7. In this relational representation, each observed assertion acts as a base witness entity, every ingestion or rule execution is recorded as an activity attributed to an agent, derivation edges group conjunctive and alternative witness sets (why-provenance), and retraction events supersede or invalidate downstream beliefs7.  
Existing production SQLite tooling and event schemas illustrate the individual mechanisms available on SQLite—and where they fall short of full bitemporal provenance.

| Production SQLite Tool / Schema | Core Physical & Trigger Pattern | Temporality & Immutability | Provenance / Attribution | Gap for Bitemporal Provenance |
| :---- | :---- | :---- | :---- | :---- |
| simonw/sqlite-history18 | \_\<table\>\_history populated by triggers (AFTER INSERT, update, delete); \_mask bitmask (-1 on delete) | Unitemporal transaction log (\_version, \_updated) | Column-level change mask only | Lacks valid-time intervals, agent attribution, and derivation edges18 |
| vlcn-io/cr-sqlite & superfly/corrosion23 | \*\_\_crsql\_clock per-column metadata \+ crsql\_changes virtual table (table, pk, cid, val, col\_version, db\_version, site\_id, cl, seq) | CRDT convergence (cl odd/even tombstones); crsql\_changes is *not* an immutable history log23 | 16-byte site\_id, transaction db\_version, col\_version | Overwrites intermediate column history; high-traffic sync tuning noted in fly.io/infra-log23 |
| duckcode-ai/duckpipe17 | SQLite audit log with modification-blocking triggers (prevent\_audit\_update) | Append-only enforced directly in SQLite trigger layer | Operational audit trail | Provides write-immutability pattern, without bitemporal resolution17 |
| dbward-dev/dbward16 | Embedded SQLite control plane with approval workflows and hash-chained audit logs | Tamper-evident append-only chain (24 event types) | Approval/agent identity and SQL risk classification | Lacks valid-time windows and relational witness tracking16 |
| alp82/curia (events)22 | events (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, type TEXT NOT NULL, ticket TEXT, agent TEXT) | Monotonic id write order \+ ISO-8601 UTC ts | Explicit agent and event type | Single timeline; no structured interval bounds or witness groups22 |
| sqlite-utils51 | events (id INTEGER, payload ANY) built with \--strict | Single-table event container | Application-defined inside payload | Relies on caller discipline for immutability and bitemporal indexing51 |

Synthesizing XTDB's system\_from-only log2, PROV-O agent–activity responsibility7, duckpipe-style immutability triggers17, STRICT typing19, JSONB payloads21, and semiring witness grouping8 produces the following **synthesized reference schema** for SQLite 3.45+. claim\_observations uses a standard rowid INTEGER PRIMARY KEY to isolate wide val\_jsonb payloads on B\*Tree leaves, whereas prov\_agents and claim\_derivations use WITHOUT ROWID for narrow clustered lookups13.

SQL  
PRAGMA foreign\_keys \= ON;

CREATE TABLE prov\_agents (  
    agent\_id    TEXT PRIMARY KEY,  
    agent\_kind  TEXT NOT NULL CHECK (agent\_kind IN ('source\_feed', 'extractor', 'rule\_engine', 'human')),  
    trust\_tier  INTEGER NOT NULL DEFAULT 1,  
    meta\_jsonb  BLOB NOT NULL  
) STRICT, WITHOUT ROWID;

CREATE TABLE prov\_activities (  
    activity\_id    INTEGER PRIMARY KEY,  
    agent\_id       TEXT NOT NULL REFERENCES prov\_agents(agent\_id),  
    activity\_kind  TEXT NOT NULL CHECK (activity\_kind IN ('ingest', 'correction', 'derivation', 'retraction')),  
    observed\_at\_us INTEGER NOT NULL,  
    started\_at\_us  INTEGER NOT NULL,  
    ended\_at\_us    INTEGER  
) STRICT;

CREATE TABLE claim\_observations (  
    obs\_id            INTEGER PRIMARY KEY,  
    entity\_id         TEXT NOT NULL,  
    attr              TEXT NOT NULL,  
    event\_kind        TEXT NOT NULL CHECK (event\_kind IN ('assert', 'retract')),  
    val\_jsonb         BLOB,  
    valid\_from\_us     INTEGER NOT NULL,  
    valid\_to\_us       INTEGER,  
    system\_from\_us    INTEGER NOT NULL,  
    activity\_id       INTEGER NOT NULL REFERENCES prov\_activities(activity\_id),  
    agent\_id          TEXT NOT NULL REFERENCES prov\_agents(agent\_id),  
    supersedes\_obs\_id INTEGER REFERENCES claim\_observations(obs\_id),  
    row\_hash          BLOB  
) STRICT;

CREATE TABLE claim\_derivations (  
    derived\_obs\_id    INTEGER NOT NULL REFERENCES claim\_observations(obs\_id),  
    witness\_group\_id  INTEGER NOT NULL,  
    source\_obs\_id     INTEGER NOT NULL REFERENCES claim\_observations(obs\_id),  
    PRIMARY KEY (derived\_obs\_id, witness\_group\_id, source\_obs\_id)  
) STRICT, WITHOUT ROWID;

CREATE TRIGGER trg\_obs\_no\_update BEFORE UPDATE ON claim\_observations  
BEGIN  
    SELECT RAISE(ABORT, 'claim\_observations is append-only; append a correction or retraction row');  
END;

CREATE TRIGGER trg\_obs\_no\_delete BEFORE DELETE ON claim\_observations  
BEGIN  
    SELECT RAISE(ABORT, 'claim\_observations is append-only; logical retractions only');  
END;

In this design, retracting a claim or recording that an upstream source stopped reporting an attribute never mutates existing rows in claim\_observations; instead, the ingestion activity appends an event\_kind \= 'retract' record at system\_from\_us \= T\_now covering the affected (entity\_id, attr, valid\_from\_us, valid\_to\_us) interval1. In claim\_derivations, rows sharing (derived\_obs\_id, witness\_group\_id) represent one conjunctive witness combination (why-provenance), while multiple distinct witness\_group\_id values for the same derived\_obs\_id represent independent alternative derivations8. The primary compliance exception to strict append-only immutability occurs under GDPR right-to-erasure mandates—addressed in TensorDB (a Rust bitemporal ledger) via FORGET KEY cryptographic tombstones and in Snowplow via event-store erasure graphs53—where privileged erasure workflows must selectively purge val\_jsonb payloads without breaking obs\_id foreign-key graphs.

## **Cascading Belief Retraction When Upstream Claims Change or Disappear**

When an upstream source retracts a claim, revises a historical value, or omits an entity from a subsequent extraction snapshot, naive cascading deletes both erase audit history and introduce correctness bugs whenever a downstream derived fact holds multiple independent justifications10. Formal belief maintenance algorithms address this multiple-support problem across distinct graph topologies and expressive power levels.

| Algorithm / Framework | Academic Lineage | Graph / Rule Scope | Retraction Mechanism | SQLite Implementation Fit |
| :---- | :---- | :---- | :---- | :---- |
| JTMS & ATMS | Doyle (1979); De Kleer (1986)28 | Dependency networks; assumption-based reasoning | Tracks explicit justifications or assumption dependencies to withdraw unsupported beliefs and support partial re-derivation55 | Conceptual foundation for claim\_derivations witness tracking55 |
| Counting Algorithm | Gupta, Mumick, & Subrahmanian (SIGMOD 1993\)10 | Nonrecursive views / acyclic DAGs | Stores integer derivation counts (count(t)); join counts multiply (count(t1) \* count(t2)), union counts sum signed deltas; tuple survives while count \> 011 | High fit: synchronous AFTER INSERT trigger updates support\_count on current\_claims11 |
| Delete-and-Rederive (DRed) | Gupta, Mumick, & Subrahmanian (SIGMOD 1993\)10 | Recursive Datalog, cycles, stratified negation | Three strata-ordered phases: OVERDELETE superset D, one-step backward REDERIVE R from surviving tuples, forward INSERT propagation10 | Required for cyclic/recursive knowledge graphs via WITH RECURSIVE inside BEGIN IMMEDIATE10 |
| DRedc | Hu, Motik, & collaborators (hmh18)10 | Recursive Datalog / ontological rules | Splits nonrecursive vs. recursive counters per fact; nonzero nonrecursive counters halt overdeletion; nonzero recursive counters eliminate backward REDERIVE10 | Strong optimization when SQLite materializes high-fan-in multi-hop rules10 |
| DRedMTL | AAAI DatalogMTL incremental maintenance26 | Metric temporal logic over intervals \[tL, tR\] | Adapts 3-phase OVERDELETE/REDERIVE/INSERT to periodic temporal interval unfoldings (unfd(D), unfd(I))26 | Template for cascading retractions bound to finite \[valid\_from, valid\_to) slices26 |
| Provenance Semirings | Green, Karvounarakis, & Tannen (PODS 2007, 2017); ProvSQL8 | Positive relational algebra & annotated views | Represents alternative witness sets algebraically; retracting a base token zeros only terms containing it8 | Directly mirrors witness\_group\_id conjunctions and disjunctions in claim\_derivations8 |

In practice, selecting a SQLite retraction engine hinges on whether derivation dependencies form cycles. For **acyclic (stratified DAG) provenance graphs**, AFTER INSERT triggers operating with PRAGMA recursive\_triggers \= ON (subject to SQLite's MAX\_TRIGGER\_DEPTH=1000 limit verified in SQLite 3.46.1) implement Counting directly inside the write transaction11: when a retraction row arrives for source\_obs\_id, any witness\_group\_id referencing that observation becomes inactive, decrementing support\_count on the dependent derived\_obs\_id; only if support\_count reaches 0 does the engine append a systemic event\_kind \= 'retract' row for the derived belief, firing the next trigger hop11. For **recursive or cyclic derivations**—where Gupta et al. note Counting can fail to terminate when derivation counts are infinite11 and recursive triggers risk hitting MAX\_TRIGGER\_DEPTH24—the application should execute DRed explicitly inside a BEGIN IMMEDIATE transaction10: traverse claim\_derivations via WITH RECURSIVE into a temporary overdeletion table D, test each candidate in D for surviving alternative witness\_group\_id tuples whose source observations remain active (REDERIVE), propagate surviving derivations forward (INSERT), and append event\_kind \= 'retract' rows for every unrescued belief10. Appending retraction rows rather than mutating history ensures FOR SYSTEM\_TIME AS OF \< T\_now audits continue to observe the pre-retraction belief1.

## **SQLite Physical Design, Indexing, and Projection Strategies**

Sustaining low-latency operational reads over an append-only observation log requires coordinating materialized projections, partial index constraints, table storage options, JSONB encoding, R\*Tree coordinate scaling, and WAL checkpoint isolation.

### **Materialized Projection Tables and Trigger Discipline**

To deliver O(log N) primary-key lookups for current-state queries (VT \= ST \= now), maintain a narrow WITHOUT ROWID materialized projection table (current\_claims) updated synchronously by AFTER INSERT triggers on claim\_observations18. SQLite documentation advises preferring AFTER triggers over BEFORE triggers when referencing row identifiers because rowid is undefined inside a BEFORE INSERT trigger when INTEGER PRIMARY KEY auto-generation occurs20. Notice the temporal scoping condition in the WHEN clause below: filtering on NEW.valid\_from\_us \<= NEW.system\_from\_us AND (NEW.valid\_to\_us IS NULL OR NEW.valid\_to\_us \> NEW.system\_from\_us) allows purely historical backfills (valid\_to\_us \<= system\_from\_us) to bypass the current-state projection while recording both open-ended and still-active bounded claims, and prevents future-dated assertions (valid\_from\_us \> system\_from\_us) from prematurely overwriting current state1.

SQL  
CREATE TABLE current\_claims (  
    entity\_id      TEXT NOT NULL,  
    attr           TEXT NOT NULL,  
    val\_jsonb      BLOB,  
    obs\_id         INTEGER NOT NULL REFERENCES claim\_observations(obs\_id),  
    valid\_from\_us  INTEGER NOT NULL,  
    valid\_to\_us    INTEGER,  
    system\_from\_us INTEGER NOT NULL,  
    support\_count  INTEGER NOT NULL DEFAULT 1,  
    is\_active      INTEGER NOT NULL DEFAULT 1 CHECK (is\_active IN (0, 1)),  
    PRIMARY KEY (entity\_id, attr)  
) STRICT, WITHOUT ROWID;

CREATE TRIGGER trg\_project\_claim\_after\_insert  
AFTER INSERT ON claim\_observations  
WHEN NEW.valid\_from\_us \<= NEW.system\_from\_us  
 AND (NEW.valid\_to\_us IS NULL OR NEW.valid\_to\_us \> NEW.system\_from\_us)  
BEGIN  
    INSERT INTO current\_claims (  
        entity\_id, attr, val\_jsonb, obs\_id, valid\_from\_us, valid\_to\_us,  
        system\_from\_us, support\_count, is\_active  
    )  
    VALUES (  
        NEW.entity\_id, NEW.attr, NEW.val\_jsonb, NEW.obs\_id, NEW.valid\_from\_us, NEW.valid\_to\_us,  
        NEW.system\_from\_us, 1,  
        CASE WHEN NEW.event\_kind \= 'assert' THEN 1 ELSE 0 END  
    )  
    ON CONFLICT (entity\_id, attr) DO UPDATE SET  
        val\_jsonb      \= excluded.val\_jsonb,  
        obs\_id         \= excluded.obs\_id,  
        valid\_from\_us  \= excluded.valid\_from\_us,  
        valid\_to\_us    \= excluded.valid\_to\_us,  
        system\_from\_us \= excluded.system\_from\_us,  
        is\_active      \= excluded.is\_active  
    WHERE excluded.system\_from\_us \>= current\_claims.system\_from\_us;  
END;

### **Partial Indexes and SQLite Query-Planner Constraints**

Supported since SQLite 3.8.0 (2013-08-26), partial indexes (CREATE INDEX ... WHERE expr) omit retracted or closed-interval rows from secondary B-trees, reducing index storage and insert cost on append-only logs15. Combining UNIQUE with a partial index enforces conditional invariants—such as permitting only one active open-ended projection or claim per (entity\_id, attr) without blocking historical versions—while noting that SQLite treats NULL values as distinct in UNIQUE indexes15.  
SQLite's query planner applies strict syntactic theorem-proving rules to determine partial-index usability15. Query predicates (W) must be AND-connected while index filter terms (X) are OR-connected, and SQLite performs **no algebraic simplification**: WHERE valid\_to \= 6 will not match WHERE valid\_to \= 3+3 or WHERE valid\_to BETWEEN 6 AND 6, and placing a literal on the left (6=b) in an index definition never matches anything15. If X includes z IS NOT NULL, SQLite matches standard comparison operators (=, \<, \>, \<=, \>=, \<\>, IN, LIKE, GLOB) on z, excluding IS15. Furthermore, EXPLAIN QUERY PLAN diagnostics on SQLite 3.46.1 show how open-ended NULL ranges and multi-column keys constrain B-tree interval seeks24:

| Index Definition (obs\_null / obs\_sent) | Query WHERE Predicate | SQLite 3.46.1 EXPLAIN QUERY PLAN Output | Planner Behavior & Operational Implication |
| :---- | :---- | :---- | :---- |
| idx\_null\_open(entity\_id, attr, valid\_from) WHERE valid\_to IS NULL AND retracted\_at IS NULL | entity\_id='e1' AND attr='status' AND valid\_to IS NULL AND retracted\_at IS NULL | SEARCH obs\_null USING INDEX idx\_null\_open (entity\_id=? AND attr=?)24 | Exact prefix lookup for open-ended current assertions; omits closed history15 |
| idx\_null\_active\_sys(entity\_id, valid\_from, valid\_to) WHERE retracted\_at IS NULL | entity\_id='e1' AND retracted\_at IS NULL AND valid\_from \<= 100 AND (valid\_to IS NULL OR valid\_to \> 100\) | SEARCH obs\_null USING INDEX idx\_null\_active\_sys (entity\_id=? AND valid\_from\<?)24 | (valid\_to IS NULL OR valid\_to \> 100\) prevents B-tree upper-bound traversal on valid\_to, scanning all prior intervals with valid\_from \<= 10024 |
| idx\_sent\_active(entity\_id, attr, valid\_from, valid\_to) WHERE is\_active \= 1 | entity\_id='e1' AND is\_active \= 1 AND valid\_from \<= 100 AND valid\_to \> 100 | SEARCH obs\_sent USING INDEX idx\_sent\_active (entity\_id=?)24 | Omitting leading attr stops index traversal at entity\_id, preventing both valid\_from and valid\_to seeks24 |

Practitioners should also verify join plans on target SQLite releases: a SQLite forum report (7dee41d325) documented a RIGHT JOIN correctness regression introduced in SQLite 3.39.0 (subsequently patched on trunk, paralleling Manuel Rigger's 2019 LEFT JOIN ticket 623eff57e76d45f6) where outer joins referencing a partial index returned spurious non-NULL rows62.

### **Clustered Storage, JSONB, and Generated Columns**

Choosing between standard rowid BTrees and WITHOUT ROWID clustered tables (SQLite 3.8.2+) depends on row payload size relative to SQLite's page-overflow boundary13. Standard rowid tables isolate payloads on BTree leaves while keeping interior pages compact (storing only 64-bit integer rowids), whereas WITHOUT ROWID tables store records in index B-tree format where interior pages hold full row payloads13. To guarantee a minimum fan-out of 4, SQLite forces any WITHOUT ROWID row larger than **1/4 of a database page** onto overflow pages13. In a user-reported SQLite forum measurement confirmed by Richard Hipp's explanation of the 1/4-page threshold, payloads hovering just past 1/4 page expanded a WITHOUT ROWID database to **2,347 KB versus 692 KB** (\~3.39x larger) in an equivalent rowid table, with worst-case overflow amplification reaching 4x for WITHOUT ROWID versus 2x for rowid13. Keep wide append-only claim\_observations tables as standard rowid tables, and limit WITHOUT ROWID to compact lookup structures (current\_claims, claim\_derivations, prov\_agents)13.  
For semi-structured claim attributes, SQLite 3.45.0 (2024-01-15) introduced JSONB, an opaque internal binary parse-tree BLOB format designed strictly for SQLite internal use21. Unlike PostgreSQL's JSONB, SQLite's JSONB retains O(N) traversal complexity rather than O(1) key access, though SQLite documentation notes roughly 2x—and potentially several times—faster throughput on workflows dominated by parsing and modifying JSON21. In a controlled 20,000-row inspection on SQLite 3.46.1 storing a nested sensor claim object, JSONB lowered payload size from 4,220,000 B to 3,520,000 B (ratio 0.834, 16.6% smaller), while a single read-only filter scan (json\_extract(doc, '\$.payload.temp') \> 20\) ran in 10.67 ms versus 10.85 ms for text JSON—confirming that JSONB's primary advantages are storage compaction and eliminating parse/serialize steps on repeated JSON edits rather than O(1) read indexing21. To index extracted JSON claim properties directly inside STRICT tables, pair JSONB payloads with GENERATED ALWAYS AS (...) columns—keeping in mind that STRICT tables mandate an explicit datatype on every generated column19.

### **R\*Tree Interval Indexing and the 32-Bit Float Quantization Trap**

SQLite's R\*Tree virtual table module (implementing Beckmann et al., SIGMOD 1990; compiled by default as ENABLE\_RTREE in SQLite 3.46.1) explicitly supports time-domain overlap queries across 1 to 5 dimensions alongside a 64-bit integer key and up to 100 total columns including auxiliaries (since SQLite 3.24.0)24. However, standard rtree virtual tables store boundary coordinates as **32-bit floats**, whereas rtree\_i32 stores **32-bit signed integers**25. Inspecting 2026 Unix timestamps on SQLite 3.46.1 reveals that raw rtree float32 truncation severely distorts narrow temporal intervals24:

| Virtual Table Module | Input Epoch Interval \[min\_vt, max\_vt\] | Stored Bounds in SQLite 3.46.1 | Stored Width vs. Input Width | Engineering Constraint / Mitigation |
| :---- | :---- | :---- | :---- | :---- |
| rtree (32-bit float)24 | \[1794581700, 1794581701\] (2026 seconds, 1 s span) | \[1794581504.0, 1794581760.0\]24 | 256.0 s stored vs. 1 s input24 | False-positive overlap across \>4-minute buckets; do not feed raw Unix timestamps to rtree24 |
| rtree (32-bit float)24 | \[1794581700123, 1794581700623\] (2026 ms, 500 ms span) | \[1794581463040.0, 1794581725184.0\]24 | 262,144.0 ms stored (\~524.3x input width)24 | Severe selectivity collapse at sub-second granularity24 |
| rtree\_i32 (32-bit signed int)24 | \[1794581700, 1794581701\] (2026 seconds, 1 s span) | \[1794581700, 1794581701\]24 | 1 s (exact)24 | Exact up to 2,147,483,647 (year 2038); overflows on ms/µs timestamps without re-epoched scaling24 |

When indexing 2D (valid\_time, system\_time) overlap windows in rtree\_i32, applications must rebase coordinates relative to a domain epoch (e.g., seconds since 2020-01-01), clamp open-ended bounds to a sentinel integer below 2,147,483,647, and post-filter candidate obs\_id matches against exact 64-bit microsecond timestamps in claim\_observations24.

### **WAL Concurrency and Checkpoint Hygiene**

Enabling Write-Ahead Logging (PRAGMA journal\_mode \= WAL) allows concurrent current-state and historical readers to proceed alongside single-writer observation appends and DRed retractions71. Yet high-concurrency ingestion exposes a documented checkpoint-locking hazard reported by David Crawshaw and Dan Kennedy on the SQLite forum: under sustained load (36 connections at \~1,000 writes/sec in Crawshaw's test), automatic checkpoints lag behind, while manually calling PRAGMA wal\_checkpoint(RESTART) to bound WAL size fails with SQLITE\_BUSY within a microsecond—completely bypassing busy\_timeout handlers—whenever any worker connection holds or triggers an automatic checkpoint72. Setting PRAGMA wal\_autocheckpoint \= 0 on every connection and scheduling PASSIVE or coordinated RESTART/TRUNCATE checkpoints from a single background coordinator eliminates checkpoint lock contention60.

## **Implementation Checklist for Production SQLite Deployments**

> 1. **Enforce bitemporal append-only logging on claim\_observations.** Store (entity\_id, attr, event\_kind, val\_jsonb, valid\_from\_us, valid\_to\_us, system\_from\_us, activity\_id, agent\_id) in a STRICT rowid table, omit system\_to\_us, and enforce immutability with BEFORE UPDATE and BEFORE DELETE RAISE(ABORT, ...) triggers2.  
> 2. **Isolate current-state reads from reverse-system-time replay.** Maintain a compact WITHOUT ROWID current\_claims projection via AFTER INSERT triggers for operational reads (VT \= ST \= now), and execute reverse-system\_from\_us early-termination scans or ceiling materializations only for historical time-travel and audit queries2.  
> 3. **Align belief retraction with derivation topology.** Use AFTER INSERT trigger-maintained support\_count counters (PRAGMA recursive\_triggers \= ON) over claim\_derivations witness groups for acyclic DAGs, and switch to WITH RECURSIVE three-phase DRed (OVERDELETE, REDERIVE, INSERT) inside BEGIN IMMEDIATE transactions whenever derivation rules introduce cycles or recursion9.  
> 4. **Harden SQLite physical tuning against documented traps.** Verify EXPLAIN QUERY PLAN on partial indexes (avoiding unindexed OR IS NULL bounds where valid\_to selectivity is required, and testing LEFT/RIGHT JOIN queries), store payloads as JSONB with explicitly typed generated columns, rebase timestamps before indexing intervals in rtree\_i32 (never raw rtree), and set PRAGMA wal\_autocheckpoint \= 0 across all pooled connections15.

#### **Works cited**

> 1. Time in XTDB, [https\://docs.xtdb.com/about/time-in-xtdb.html](https://docs.xtdb.com/about/time-in-xtdb.html)  
> 2. Building a Bitemporal Index (part 2): "Bitemporal Resolution" \- XTDB, [https\://xtdb.com/blog/building-a-bitemp-index-2-resolution](https://xtdb.com/blog/building-a-bitemp-index-2-resolution)  
> 3. A Consensus Glossary of Temporal Database Concepts \- cs.aau.dk, [https\://homes.cs.aau.dk/\~csj/Papers/Files/1993\_jensenCGTDC-TR93-2035.pdf](https://homes.cs.aau.dk/~csj/Papers/Files/1993_jensenCGTDC-TR93-2035.pdf)  
> 4. Temporal database \- Wikipedia, [https\://en.wikipedia.org/wiki/Temporal\_database](https://en.wikipedia.org/wiki/Temporal_database)  
> 5. What Is Temporal Data Modeling? How Databases Track Time, [https\://tdwi.org/blogs/data-101/2026/05/what-is-temporal-data-modeling.aspx](https://tdwi.org/blogs/data-101/2026/05/what-is-temporal-data-modeling.aspx)  
> 6. How we 40x'd the performance of a class of temporal queries \- XTDB, [https\://xtdb.com/blog/40x-query-perf](https://xtdb.com/blog/40x-query-perf)  
> 7. PROV-O: The PROV Ontology \- W3C, [https\://www\.w3.org/TR/prov-o/](https://www.w3.org/TR/prov-o/)  
> 8. (PDF) Provenance Semirings \- ResearchGate, [https\://www\.researchgate.net/publication/221559651\_Provenance\_Semirings](https://www.researchgate.net/publication/221559651_Provenance_Semirings)  
> 9. On the Impact of Provenance Semiring Theory on the ... \- DROPS, [https\://drops.dagstuhl.de/entities/document/10.4230/OASIcs.Tannen.9](https://drops.dagstuhl.de/entities/document/10.4230/OASIcs.Tannen.9)  
> 10. Optimised Maintenance of Datalog Materialisations, [https\://www\.cs.ox.ac.uk/people/boris.motik/pubs/hmh18optimised-maintenance.pdf](https://www.cs.ox.ac.uk/people/boris.motik/pubs/hmh18optimised-maintenance.pdf)  
> 11. Maintaining views incrementally – Read with an AI tutor \- ChapterPal, [https\://www\.chapterpal.com/s/o8g3re46/maintaining-views-incrementally](https://www.chapterpal.com/s/o8g3re46/maintaining-views-incrementally)  
> 12. Launching XTDB v2 — time-travel SQL database to simplify, [https\://xtdb.com/blog/launching-xtdb-v2](https://xtdb.com/blog/launching-xtdb-v2)  
> 13. Why in tables WITHOUT ROWID is the amount of payload that spills, [https\://sqlite.org/forum/forumpost/ad86fbaa04](https://sqlite.org/forum/forumpost/ad86fbaa04)  
> 14. Auditing and Versioning Data in SQLite \- bytefish.de, [https\://www\.bytefish.de/blog/sqlite\_logging\_changes.html](https://www.bytefish.de/blog/sqlite_logging_changes.html)  
> 15. Partial Indexes \- SQLite, [https\://www\.sqlite.org/partialindex.html](https://www.sqlite.org/partialindex.html)  
> 16. dbward-dev \- GitHub, [https\://github.com/dbward-dev/dbward](https://github.com/dbward-dev/dbward)  
> 17. Overview · duckcode-ai/duckpipe · GitHub, [https\://github.com/duckcode-ai/duckpipe/security](https://github.com/duckcode-ai/duckpipe/security)  
> 18. simonw/sqlite-history: Track changes to SQLite tables using triggers, [https\://github.com/simonw/sqlite-history](https://github.com/simonw/sqlite-history)  
> 19. STRICT Tables \- SQLite, [https\://www\.sqlite.org/stricttables.html](https://www.sqlite.org/stricttables.html)  
> 20. Search SQLite Documentation, [https\://www\.sqlite.org/search?q=rowid\&i=3](https://www.sqlite.org/search?q=rowid&i=3)  
> 21. JSON Functions And Operators \- SQLite, [https\://www\.sqlite.org/json1.html](https://www.sqlite.org/json1.html)  
> 22. The schema and the fourteen queries (\#321) \- alp82/curia \- GitHub, [https\://github.com/alp82/curia/issues/321](https://github.com/alp82/curia/issues/321)  
> 23. vlcn.io/cr-sqlite working \| aayushprime, [https\://lamichhaneaayush.com.np/notes/vlcn-io-cr-sqlite-notes/](https://lamichhaneaayush.com.np/notes/vlcn-io-cr-sqlite-notes/)  
> 24. [unknown\_url](http://docs.google.com/unknown_url)  
> 25. RTree on ESP32 SQLite Version \- SQLite User Forum, [https\://sqlite.org/forum/info/d10acbf22fd7a6f8](https://sqlite.org/forum/info/d10acbf22fd7a6f8)  
> 26. Incremental Maintenance of DatalogMTL Materialisations, [https\://ojs.aaai.org/index.php/AAAI/article/view/39025/42987](https://ojs.aaai.org/index.php/AAAI/article/view/39025/42987)  
> 27. Temporal Algorithms – SQL for Data Warehousing, [https\://bitemporal.net/](https://bitemporal.net/)  
> 28. An Approach to Modeling and Maintaining The Evolution and ... \- EIL, [https\://eil.mie.utoronto.ca/wp-content/uploads/km/papers/huang-PHD-2007.pdf](https://eil.mie.utoronto.ca/wp-content/uploads/km/papers/huang-PHD-2007.pdf)  
> 29. Temporal Patterns \- Martin Fowler, [https\://martinfowler.com/eaaDev/timeNarrative.html](https://martinfowler.com/eaaDev/timeNarrative.html)  
> 30. The Consensus Glossary of Temporal Database Concepts \- SciSpace, [https\://scispace.com/papers/the-consensus-glossary-of-temporal-database-concepts-w5g6m32myf](https://scispace.com/papers/the-consensus-glossary-of-temporal-database-concepts-w5g6m32myf)  
> 31. Introduction to Temporal Database Research \- InfoLab, [https\://infolab.usc.edu/csci599/Fall2001/paper/chapter1.pdf](https://infolab.usc.edu/csci599/Fall2001/paper/chapter1.pdf)  
> 32. 1 Time Data Types, [https\://www2.cs.arizona.edu/\~rts/pubs/EDC.pdf](https://www2.cs.arizona.edu/~rts/pubs/EDC.pdf)  
> 33. UNDERSTANDING BITEMPORAL DATA \- AssertedVersioning.com, [http\://www\.assertedversioning.com/Documents/EDW-2011-Johnston.pdf](http://www.assertedversioning.com/Documents/EDW-2011-Johnston.pdf)  
> 34. AssertedVersioning.com, [http\://assertedversioning.com/](http://assertedversioning.com/)  
> 35. Temporal Databases Annotated Bibliography \- Illuminated Computing, [https\://illuminatedcomputing.com/posts/2017/12/temporal-databases-bibliography/](https://illuminatedcomputing.com/posts/2017/12/temporal-databases-bibliography/)  
> 36. dbt, Bitemporality, and Snapshots \- In-Depth Discussions, [https\://discourse.getdbt.com/t/dbt-bitemporality-and-snapshots/1067](https://discourse.getdbt.com/t/dbt-bitemporality-and-snapshots/1067)  
> 37. Logical data modeling: Modeling temporal data \- IBM, [https\://www\.ibm.com/docs/en/ida/9.1.2?topic=models-modeling-temporal-data](https://www.ibm.com/docs/en/ida/9.1.2?topic=models-modeling-temporal-data)  
> 38. Building a Bitemporal Index (part 1): A Taxonomy of Bitemporal Data, [https\://xtdb.com/blog/building-a-bitemp-index-1-taxonomy](https://xtdb.com/blog/building-a-bitemp-index-1-taxonomy)  
> 39. Bitemporality \- XTDB Docs, [https\://v1-docs.xtdb.com/concepts/bitemporality/](https://v1-docs.xtdb.com/concepts/bitemporality/)  
> 40. Coalescing in Temporal Databases A TIMECENTER Technical Report, [https\://timecenter.cs.aau.dk/wp-content/uploads/2022/12/TR-9.pdf](https://timecenter.cs.aau.dk/wp-content/uploads/2022/12/TR-9.pdf)  
> 41. METHODS OF ACCESS TO SERIES OF ARCHIVED DATABASE, [https\://digikogu.taltech.ee/et/Download/ed4e7b02-5f0a-4c84-8b34-a2b18fbbc609](https://digikogu.taltech.ee/et/Download/ed4e7b02-5f0a-4c84-8b34-a2b18fbbc609)  
> 42. This is a standard bi-temporal model; valid time and transaction time, [https\://news.ycombinator.com/item?id=14733841](https://news.ycombinator.com/item?id=14733841)  
> 43. Bi-Temporal Tables: A Quick Guide for the Financial Industry \- Medium, [https\://mkulakowski2-73849.medium.com/bi-temporal-tables-a-quick-guide-for-the-financial-industry-9c443ba343ad](https://mkulakowski2-73849.medium.com/bi-temporal-tables-a-quick-guide-for-the-financial-industry-9c443ba343ad)  
> 44. But bitemporality always introduces complexity\! \- XTDB, [https\://xtdb.com/blog/but-bitemporality-always-introduces-complexity](https://xtdb.com/blog/but-bitemporality-always-introduces-complexity)  
> 45. Building a Bitemporal Index (part 3): Storage \- XTDB, [https\://xtdb.com/blog/building-a-bitemp-index-3-storage](https://xtdb.com/blog/building-a-bitemp-index-3-storage)  
> 46. ProvSQL Tutorial \- Introduction to Semiring Provenance, [https\://pierre.senellart.com/talks/descartes-20221010.pdf](https://pierre.senellart.com/talks/descartes-20221010.pdf)  
> 47. Infra Log \- Fly.io, [https\://fly.io/infra-log/](https://fly.io/infra-log/)  
> 48. README.md \- vlcn-io/cr-sqlite · GitHub, [https\://github.com/vlcn-io/cr-sqlite/blob/main/README.md](https://github.com/vlcn-io/cr-sqlite/blob/main/README.md)  
> 49. corrosion/doc/crdts.md at main \- GitHub, [https\://github.com/superfly/corrosion/blob/main/doc/crdts.md](https://github.com/superfly/corrosion/blob/main/doc/crdts.md)  
> 50. CrSqlSchema.ts \- effect-native, [https\://effectnative.dev/crsql/CrSqlSchema.ts.html](https://effectnative.dev/crsql/CrSqlSchema.ts.html)  
> 51. sqlite-utils command-line tool, [https\://sqlite-utils.datasette.io/en/stable/cli.html](https://sqlite-utils.datasette.io/en/stable/cli.html)  
> 52. Clustered Indexes and the WITHOUT ROWID Optimization \- SQLite, [https\://www\.sqlite.org/withoutrowid.html](https://www.sqlite.org/withoutrowid.html)  
> 53. I Built a Database That Never Forgets — Here's Why \- DEV Community, [https\://dev.to/walebadr/tensordb-ai-native-bitemporal-ledger-database-with-full-sql-and-postgresql-wire-protocol-3eal](https://dev.to/walebadr/tensordb-ai-native-bitemporal-ledger-database-with-full-sql-and-postgresql-wire-protocol-3eal)  
> 54. llms.txt \- Snowplow Documentation, [https\://docs.snowplow.io/llms.txt](https://docs.snowplow.io/llms.txt)  
> 55. Using RDF Graph Provenance to Efficiently ... \- ePrints Soton, [https\://eprints.soton.ac.uk/id/eprint/437665/1/Final\_thesis.pdf](https://eprints.soton.ac.uk/id/eprint/437665/1/Final_thesis.pdf)  
> 56. A Survey and an Implementation Roadmap for Belief Change \- arXiv, [https\://arxiv.org/html/2608.14567v1](https://arxiv.org/html/2608.14567v1)  
> 57. Pragma statements supported by SQLite, [https\://www\.sqlite.org/pragma.html](https://www.sqlite.org/pragma.html)  
> 58. (PDF) Maintaining views incrementally \- ResearchGate, [https\://www\.researchgate.net/publication/213883593\_Maintaining\_views\_incrementally](https://www.researchgate.net/publication/213883593_Maintaining_views_incrementally)  
> 59. Maintaining views incrementally \- Sci-Hub, [https\://www\.sci-hub.st/10.1145/170035.170066](https://www.sci-hub.st/10.1145/170035.170066)  
> 60. SQLite backups by opening transaction \- SQLite User Forum, [https\://sqlite.org/forum/info/b99fcba66158d97d363fd8fc4f6187bd3d31df67bb186add9881e3f80f73bf35](https://sqlite.org/forum/info/b99fcba66158d97d363fd8fc4f6187bd3d31df67bb186add9881e3f80f73bf35)  
> 61. Unique \- SQLite, [https\://sqlite.org/search?q=unique](https://sqlite.org/search?q=unique)  
> 62. Unexpected multiple join result involving full ... \- SQLite User Forum, [https\://www\.sqlite.org/forum/forumpost/7dee41d325](https://www.sqlite.org/forum/forumpost/7dee41d325)  
> 63. The SQLite JSONB Format, [https\://sqlite.org/jsonb.html](https://sqlite.org/jsonb.html)  
> 64. JSONB has landed \- SQLite User Forum, [https\://sqlite.org/forum/forumpost/fa6f64e3dc1a5d97](https://sqlite.org/forum/forumpost/fa6f64e3dc1a5d97)  
> 65. Search SQLite Documentation, [https\://www\.sqlite.org/search?q=json\&i=1](https://www.sqlite.org/search?q=json&i=1)  
> 66. Generated Columns \- SQLite, [https\://www\.sqlite.org/gencol.html](https://www.sqlite.org/gencol.html)  
> 67. Generated columns in strict tables \- SQLite User Forum, [https\://www\.sqlite.org/forum/info/beebf65c61687ce7](https://www.sqlite.org/forum/info/beebf65c61687ce7)  
> 68. The SQLite R\*Tree Module, [https\://www\.sqlite.org/rtree.html](https://www.sqlite.org/rtree.html)  
> 69. The SQLite R\*Tree Module, [https\://www2.sqlite.org/draft/matrix/rtree.html](https://www2.sqlite.org/draft/matrix/rtree.html)  
> 70. RTree on ESP32 SQLite Version \- SQLite User Forum, [https\://sqlite.org/forum/forumpost/1e653cb3bf?raw](https://sqlite.org/forum/forumpost/1e653cb3bf?raw)  
> 71. Write-Ahead Logging \- SQLite, [https\://www\.sqlite.org/wal.html](https://www.sqlite.org/wal.html)  
> 72. Checkpoint a database \- SQLite, [https\://www\.sqlite.org/c3ref/wal\_checkpoint\_v2.html](https://www.sqlite.org/c3ref/wal_checkpoint_v2.html)  
> 73. PRAGMA wal\_checkpoint(RESTART ... \- SQLite User Forum, [https\://sqlite.org/forum/info/6a66501e4df030ae](https://sqlite.org/forum/info/6a66501e4df030ae)