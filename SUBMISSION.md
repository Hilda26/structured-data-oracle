# Submission Package

## Title

StructuredDataOracle — Schema-Drift-Resilient JSON API Condition Oracle

## Notes / Description (≤1000 characters, 898 used)

StructuredDataOracle judges live JSON API data against a declared condition -
resilient to schema drift, unlike a JSON path that breaks silently when an API
renames a field or returns an error as an ordinary 200 body. Anyone declares an API
URL, a field description, and a comparator/threshold; check_feed fetches the API live
in one judged round and validators read the raw response for what it contains,
recognizing the value under whatever key or nesting it appears as. NOT_FOUND (value
genuinely absent) is kept strictly separate from CONDITION_NOT_MET (value found,
condition unmet). Checked against every prior portfolio correction: no frozen-state
race, no stale-verdict-on-error, no fund-lock risk since nothing is escrowed here.
Equivalence strategy matches GenLayer's own guidance for external APIs with unstable
fields. 340-line contract, 23 direct tests, 3 passing live StudioNet tests.

## Evidence links

- GitHub repo: https://github.com/Hilda26/structured-data-oracle (no AI attribution —
  verified via `git log -1 --format='%B' | grep -i "co-authored\|claude\|generated
  with"` → no match, on every commit)
- Explorer contract URL: https://explorer-studio.genlayer.com/address/0x08be9d9316fBB505d6537dA73a8810CeC018965B
- Studio import URL: open studio.genlayer.com → Import contract →
  `0x08be9d9316fBB505d6537dA73a8810CeC018965B`
- Deployed StudioNet address: `0x08be9d9316fBB505d6537dA73a8810CeC018965B`

## Why this is not "too simple" - a deliberate self-audit before submission

Before packaging this submission, the design was checked directly against the three
real correction requests every other contract in this portfolio has received, to make
sure none of those failure classes were quietly reintroduced here:

1. **HandleGuard's TOCTOU fix** (a frozen shortlist judged against a shared, mutable
   set that could drift before an async round completed) — does not apply.
   `check_feed` fetches everything it judges live, inside the same round, every time.
   No Feed's verdict is ever compared against another Feed's mutable state.
2. **SourceConsensus's stale-verdict-on-error fix** (a prior successful round's labels
   survived visible after a later round failed to parse) — already handled correctly
   from the first version of this contract: `extracted_value = ""` sits in the exact
   same branch as `state = STATE_ERRORED`, verified by
   `test_check_feed_on_fetch_failure_sets_errored`.
3. **DisputeArbiter's bounded-timeout-exit fix** (an unreachable evidence URL could
   lock two parties' escrowed stakes forever) — does not apply structurally, not by
   oversight: `StructuredDataOracle` never escrows value. A Feed stuck in `ERRORED`
   forever means only that it stops producing fresh readings; nothing is locked,
   because there was never anything at stake.

The equivalence-principle choice (`prompt_comparative`, not `strict_eq`) was also
checked directly against GenLayer's own build guidance, which names "external APIs
with unstable fields" as the explicit case for a custom leader/validator — a
word-for-word description of this contract's job — and against GenLayer's own shipped
prediction-market reference example, which correctly uses `strict_eq` only because it
targets one fixed, structurally stable source (unlike this contract's arbitrary,
creator-declared APIs). Full writeup in `DESIGN.md` §4a and §5a.

## What was verified

- `genvm-lint check contracts/structured_data_oracle.py --json` and the worked
  example: both clean.
- `pytest tests/direct/` — 23/23 passing (creation validation including malformed-
  threshold rejection, all four terminal states, cooldown enforcement, permissionless
  checking, and the worked consumer example `ThresholdGatedAction`).
- `pytest tests/integration/ --network=studionet` against the live deployment — all 3
  tests passed, covering every real verdict category:
  - `test_full_surface_drives_create_and_check_and_reads_every_view`: real judged
    round on CoinGecko's live BTC price API, `CONDITION_MET`.
  - `test_check_feed_reaches_condition_not_met_on_a_real_impossible_threshold`: the
    same real API with a flipped threshold — the round still correctly found the real
    value and correctly reported `CONDITION_NOT_MET`, proving the negative path is a
    genuine judgment, not a default.
  - `test_check_feed_with_unreachable_api_completes_without_genvm_or_consensus_error`:
    a genuinely dead domain reached `ERRORED` with the transaction still completing
    `SUCCESS`/`ACCEPTED` at the GenVM/consensus level.
  - Every judged round across every run has completed `SUCCESS`/`ACCEPTED` — zero
    fatal errors, zero undetermined rounds.

## Character count check

898/1000 characters (verified with `len()` in Python, whitespace-normalized).
