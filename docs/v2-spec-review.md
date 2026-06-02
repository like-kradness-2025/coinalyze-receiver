# v2 Spec Review

## Verdict: **PASS**
### Score: **97 / 100**

I re-read the full v2 specification after the 8 fixes were applied and verified that the previously identified blockers are now explicitly covered. The document is now sufficiently precise for implementation and clears the 95-point gate.

---

## What I verified

I read the entire spec and confirmed the following fixes are present and materially correct:

1. **Symbol-map source path and loader rules** are now explicit in **B.2**
   - Exact path: `~/.hermes/data/coinalyze/coinalyze-btc-selected-20-symbol-market-map.json`
   - Load-time validation is defined
   - Missing/malformed/wrong-count behavior is defined

2. **UPSERT identity** is now unambiguous in **B.4.3**
   - Composite PK is `(symbol, timestamp)`
   - No extra identity fields are mentioned
   - `ON CONFLICT(symbol, timestamp)` is specified

3. **`to` semantics** are now clear in **A.3**
   - `to` is exclusive
   - It is minute-aligned
   - This resolves the duplicate/missing bar ambiguity

4. **`list-markets`** endpoint and output rules are now defined in **B.5.4**
   - Exact endpoint paths are specified
   - Auth/rate-limit behavior is covered
   - Filtering and output columns are defined

5. **`show`** command behavior is now defined in **B.5.3**
   - Output format is tabular
   - Ordering is specified
   - Local-file-only behavior is explicit
   - Missing/malformed file exits with code 1

6. **Summary aggregation and exit codes** are now specified in **B.6.1**
   - Per-symbol severity rules are defined
   - Per-type aggregation is illustrated
   - `fetch` and `loop` exit behavior is stated

7. **Shutdown semantics** are tightened in **C.1.2**
   - `SIGINT`/`SIGTERM` are listed
   - Current in-flight request may complete
   - No new requests should start after shutdown is requested
   - Storage flush/close behavior is defined

8. **v1 module deletion** is now noted in **B.4.2**
   - `receiver.py` and `selected20.py` are explicitly called out as deleted from v2

---

## Remaining gaps / risks

I do not see any remaining blocking gaps. The spec is now coherent across API behavior, storage identity, CLI behavior, and loop shutdown semantics.

Minor note:
- The `loop` fatal-condition wording in **B.6.1** and **C.1.2/C.2** is acceptable, though implementations should still treat uncaught exceptions and authentication failures as process-fatal as described.

---

## Final recommendation

**PASS** the 95-point gate.

The prior implementation risks have been addressed, and the spec is now detailed enough to support a consistent v2 implementation without material ambiguity.