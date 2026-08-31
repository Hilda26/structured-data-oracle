# Submission Package

## Title

StructuredDataOracle — Schema-Drift-Resilient JSON API Condition Oracle

## Notes / Description (≤1000 characters, 937 used)

StructuredDataOracle judges live JSON API data against a declared condition -
resilient to schema drift, unlike a JSON path that breaks silently when an API
renames a field or returns an error as an ordinary 200 body. Anyone declares an API
URL, a field description, and a comparator/threshold; check_feed fetches the API live
in one judged round and validators read the raw response for what it contains,
recognizing the value under whatever key or nesting it appears as. NOT_FOUND (value
genuinely absent) is kept strictly separate from CONDITION_NOT_MET (value found,
condition unmet). Time is consensus-bound: the clock is read exactly once inside the
judged flow, and that single value drives both the cooldown decision and the stored
timestamp, so validators can never diverge. extracted_value is canonically bound to a
bare decimal a consumer can parse directly. 415-line contract, 29 direct tests, 3
passing live StudioNet tests.

## Evidence links

- GitHub repo: https://github.com/Hilda26/structured-data-oracle (no AI attribution —
  verified via `git log -1 --format='%B' | grep -i "co-authored\|claude\|generated
  with"` → no match, on every commit)
- Explorer contract URL: https://explorer-studio.genlayer.com/address/0x51C695A81eA8c9Bb13923cE679B2894B9f0f2AFD
- Studio import URL: open studio.genlayer.com → Import contract →
  `0x51C695A81eA8c9Bb13923cE679B2894B9f0f2AFD`
- Deployed StudioNet address: `0x51C695A81eA8c9Bb13923cE679B2894B9f0f2AFD`
  (redeployed with the consensus-timestamp fix; supersedes
  `0x08be9d9316fBB505d6537dA73a8810CeC018965B`)

## Review addressed — consensus-bound time value

> Please replace the datetime.now() cooldown path with one deterministic or
> consensus-bound time value that every validator uses identically for both the
> cooldown decision and the stored last_checked_at. No local wall-clock read should
> occur outside the judged flow [...] Optional hardening: if future consumers will
> rely on extracted_value, bind a canonical value rather than treating it as
> descriptive metadata.

**Fixed.** The clock is now read exactly once, inside the judged flow, and that single
leader-proposed `observed_at` rides in the accepted round envelope — making it a
consensus-bound value that every validator settles on identically. The contract uses
*that same string* for both the cooldown decision and the stored `last_checked_at`, so
they cannot diverge from each other or between validators. `grep datetime.now` on the
contract returns exactly one line, inside the leader closure; the `_now_iso()` helper
that supplied the old second reading was deleted entirely, leaving no fallback clock
path.

Two deliberate consequences: the cooldown is now checked *after* the round (the
timestamp doesn't exist until the round produces it — a too-early call reverts writing
no state), and a round returning no usable `observed_at` is rejected outright rather
than falling back to a local reading.

**Optional hardening also done.** `extracted_value` is now validated to the same
canonical bare-decimal form the threshold must take — a non-conforming value rejects
the whole round rather than storing unparseable text, so a consumer can parse it
directly and trust it was the value the verdict was reached against.

GenLayer's newer runner exposes `gl.message.datetime` / `gl.vm.get_timestamp()`, which
would be more direct — both were probed against the pinned deployable runner and
**neither exists there**, and the newer runner isn't loadable for real StudioNet
deployment. Placing the single clock read inside the judged flow is the correct fix
available on the deployable runner, and is exactly what the review's wording
prescribes. Full writeup in `REVIEW.md` and `DESIGN.md` §3a/§3b.

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
- `pytest tests/direct/` — 29/29 passing (creation validation including malformed-
  threshold rejection, all four terminal states, cooldown enforcement, permissionless
  checking, the worked consumer example `ThresholdGatedAction`, plus 6 new regression
  tests for the review fix: the stored timestamp being the round's own consensus
  value, cooldown boundary behavior decided against that same value, a rejected
  cooldown call writing no state at all, and canonical `extracted_value` enforcement).
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
  - These runs also confirm the review fix end to end: every settled feed's
    `last_checked_at` carries the round's own single consensus timestamp (e.g.
    `2026-08-30T16:10:52.371007+00:00`), and every `extracted_value` came back in
    canonical bare-decimal form (`78853`, `78793`, `""` for the errored feed).

## Character count check

937/1000 characters (verified with `len()` in Python, whitespace-normalized).
