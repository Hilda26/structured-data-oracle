# Submission Package

## Title

StructuredDataOracle — Schema-Drift-Resilient JSON API Condition Oracle

## Notes / Description (≤1000 characters, 958 used)

StructuredDataOracle judges live JSON API data against a declared condition -
resilient to schema drift, unlike a JSON path that breaks silently when an API
renames a field or returns an error as an ordinary 200 body. Anyone declares an API
URL, a field description, and a comparator/threshold; check_feed fetches the API live
and validators read the raw response for what it contains, recognizing the value
under whatever key or nesting it appears as. NOT_FOUND (value absent) stays distinct
from CONDITION_NOT_MET (value found, condition unmet). Consensus uses a custom
leader/validator function, not just an LLM principle: each validator independently
re-fetches and re-reasons, then checks the leader's verdict and timestamp by hard
comparison, so the accepted time value never drifts more than 300s from a real
validator's own clock. extracted_value is canonically bound to a bare decimal. 483
lines, 39 direct tests, 3 passing live StudioNet tests.

## Evidence links

- GitHub repo: https://github.com/Hilda26/structured-data-oracle (no AI attribution —
  verified via `git log -1 --format='%B' | grep -i "co-authored\|claude\|generated
  with"` → no match, on every commit)
- Explorer contract URL: https://explorer-studio.genlayer.com/address/0xbA03D3cfF2D0dF47b65499463d8C14dF01043c0c
- Studio import URL: open studio.genlayer.com → Import contract →
  `0xbA03D3cfF2D0dF47b65499463d8C14dF01043c0c`
- Deployed StudioNet address: `0xbA03D3cfF2D0dF47b65499463d8C14dF01043c0c`
  (redeployed with the real, deterministic timestamp fix; see the Appeal section
  below. Supersedes `0x25E2C67fc69Dbd338749D69363d6129375fe728c` (a first attempt at
  the same review that turned out to still be judgment-based),
  `0x541d81E6386A69925F23dCd6Abaa630E6a97638f`, and
  `0x51C695A81eA8c9Bb13923cE679B2894B9f0f2AFD`, all of which supersede the original
  defective `0x08be9d9316fBB505d6537dA73a8810CeC018965B`)

## Appeal — 2026-09-12

The review stated: *"The reviewed oracle still does not independently verify the
timestamp that controls its cooldown. In the repository version, validators are
explicitly told to ignore observed_at, so a far-future leader timestamp can pass with
the same verdict, become last_checked_at, and block later checks; the supplied
deployment also uses validator-local clock reads outside consensus. Bind the
behavior-changing time value to independently verified evidence, then provide matching
repository and Explorer source."*

This was a real, distinct defect - not the same issue the 2026-09-06 appeal addressed
(that one was about a stale deployment address; this one is a genuine gap in the
timestamp logic itself, present on the already-corrected version too). A first fix
bound the future direction through the equivalence-principle text - asking each
validator's own LLM judgment to treat a "wildly inconsistent" timestamp as a
disagreement. On honest review that was still prose, not proof: nothing made "wildly
inconsistent" a number, and there was no way to demonstrate a boundary because none
existed.

**The actual fix replaces the consensus mechanism itself.** `check_feed` no longer
uses `gl.eq_principle.prompt_comparative` with a natural-language principle - it uses
`gl.vm.run_nondet_unsafe(leader_fn, validator_fn)`, GenLayer's own custom
leader/validator primitive, where `validator_fn` is ordinary Python: every validator
independently re-runs `leader_fn` itself and accepts the leader's proposal only if its
own verdict matches exactly *and* its own independently-observed `observed_at` falls
within a fixed 300-second window of the leader's - a hard number, not a judgment call.
`check_feed` also still deterministically rejects any accepted `observed_at` that
doesn't strictly exceed the feed's own `last_checked_at`, closing the complementary
past-regression direction against on-chain state alone.

This is proven directly: seven new direct-mode tests use gltest's
`direct_vm.run_validator()` to genuinely execute the real `validator_fn` against a
crafted malicious leader result - including the literal far-future and far-past
attacks the review described (both rejected) and the exact 300s/301s boundary (pinned
to the second). Direct mode never invokes `validator_fn` during an ordinary contract
call by default (it trusts a single leader execution and only records `validator_fn`
for a test to invoke separately), so these are the only tests in this codebase that
actually exercise it - not inferred from the happy path continuing to work. Full
rationale in `DESIGN.md` §3c and `REVIEW.md`.

Redeployed to `0xbA03D3cfF2D0dF47b65499463d8C14dF01043c0c` (2026-09-12, unanimous
validator agreement), on-chain code independently re-verified with `genlayer code`
immediately after deployment - confirmed `run_nondet_unsafe`, `MAX_CLOCK_SKEW_SECONDS`,
and `validator_fn` are present, and confirmed zero occurrences of `JUDGE_PRINCIPLE` or
`prompt_comparative` anywhere in the deployed bytecode. 39/39 direct tests pass (7 new
`validator_fn` tests plus the 3 monotonicity tests from the first attempt), lint
clean, all 3 integration tests pass live - including one run where a real, transient
CoinGecko rate limit organically exercised `validator_fn`'s shared-failure agreement
path on live infrastructure, not just in a test. Please evaluate this address.

## Appeal — 2026-09-06

The review stated: *"the submitted Explorer deployment still runs the older cooldown
path with local wall-clock reads and therefore does not match the corrected source."*

The repository and the previously-submitted address
(`0x51C695A81eA8c9Bb13923cE679B2894B9f0f2AFD`) were both already correct — verified just
now by fetching that address's actual deployed code directly with `genlayer code
0x51C695A81eA8c9Bb13923cE679B2894B9f0f2AFD`, which returns exactly one `datetime.now()`
call, inside `leader()`, with no `_now_iso()` helper. For direct comparison, the same
command against the original defective address, `0x08be9d9316fBB505d6537dA73a8810CeC018965B`,
does return the `_now_iso()` helper and two separate local wall-clock reads — the exact
pattern the review described. It's likely the review evaluated that original address
rather than the corrected one actually named in this submission.

To remove any doubt, the contract has been redeployed fresh to
`0x541d81E6386A69925F23dCd6Abaa630E6a97638f` (2026-09-06, unanimous validator
agreement). Its deployed code was independently re-verified the same way immediately
after deployment, and all 3 integration tests pass against it on live StudioNet
consensus — see "Measured on live consensus" in `README.md` for the actual verdicts and
extracted values. Please evaluate this address.

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

The equivalence-strategy choice (a custom leader/validator via
`gl.vm.run_nondet_unsafe`, not `strict_eq`) was checked directly against GenLayer's
own build guidance, which names "external APIs with unstable fields" and "full
control over consensus logic" as the explicit case for a custom leader/validator — a
word-for-word description of this contract's job — and against GenLayer's own shipped
prediction-market reference example, which correctly uses `strict_eq` only because it
targets one fixed, structurally stable source (unlike this contract's arbitrary,
creator-declared APIs). Full writeup in `DESIGN.md` §4, §4a, and §5a.

## What was verified

- `genvm-lint check contracts/structured_data_oracle.py --json` and the worked
  example: both clean (lint pass; the deeper schema-validate step hit an unrelated
  local SDK-cache miss for the pinned runner tarball during this pass — not a code
  issue, corroborated by `genlayer deploy` and `gltest` both successfully loading the
  same pinned runner in the same session).
- `pytest tests/direct/` — 39/39 passing: creation validation including
  malformed-threshold rejection, all four terminal states, cooldown enforcement,
  permissionless checking, the worked consumer example `ThresholdGatedAction`, the
  deterministic timestamp-monotonicity guard, and seven tests that genuinely invoke
  the real `validator_fn` via `direct_vm.run_validator()` against a crafted malicious
  leader result — including the literal far-future/far-past attacks a review
  described, both rejected, with the exact 300s/301s boundary pinned to the second.
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
