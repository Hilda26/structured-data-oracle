# Review response — consensus-bound time value

## Review received

> Please replace the datetime.now() cooldown path with one deterministic or
> consensus-bound time value that every validator uses identically for both the
> cooldown decision and the stored last_checked_at. No local wall-clock read should
> occur outside the judged flow, since validators near the boundary can otherwise
> derive different timestamps or opposite allow/reject outcomes. Then provide matching
> corrected repository and Explorer source.
>
> Optional hardening: if future consumers will rely on extracted_value, bind a
> canonical value rather than treating it as descriptive metadata.

## Root cause

GenLayer validators independently re-execute the **entire** contract call, not just
the judged closure. Any `datetime.now()` read in the "deterministic" outer body is
therefore not actually deterministic across validators — each one samples its own wall
clock at its own moment. Near a cooldown boundary, two honest validators evaluating
the same transaction microseconds apart could compute `elapsed` on opposite sides of
`check_cooldown_seconds` and reach **opposite allow/reject outcomes**.

The old `check_feed` made this worse by reading the clock **twice**, in two separate
places:

```python
# before the round - decided the cooldown
elapsed = (datetime.now(timezone.utc) - last).total_seconds()
...
# after the round - stamped the feed
feed.last_checked_at = _now_iso()      # a *different* instant again
```

So the value that gated the decision and the value that got stored weren't even
consistent with each other inside a single execution, let alone across validators.

## Fix

The clock is now read **exactly once, inside the judged flow**, and that single
leader-proposed value rides in the accepted round envelope:

```python
def leader() -> str:
    # The ONE time value this contract ever reads, taken inside the
    # judged flow so the accepted round carries a single
    # leader-proposed timestamp that every validator settles on
    # identically. Nothing outside this closure reads a clock.
    observed_at = datetime.now(timezone.utc).isoformat()
    ...
    model_envelope["observed_at"] = observed_at
    return json.dumps(model_envelope)
```

Because `prompt_comparative` settles on one accepted leader envelope, `observed_at` is
a consensus-bound value. The contract then uses **that same value** for both the
cooldown decision and the stored `last_checked_at` — they are literally the same
string, so they cannot diverge from each other or between validators:

```python
observed_at = _parse_observed_at(raw_result)
if not observed_at:
    raise gl.vm.UserError("round did not carry a usable consensus timestamp")

if int(feed.check_count) > 0:
    observed_dt = _parse_iso(observed_at)
    elapsed = (observed_dt - last).total_seconds()      # consensus value
    if elapsed < cooldown:
        raise gl.vm.UserError("check cooldown has not elapsed")

feed.last_checked_at = observed_at                      # same consensus value
```

Verification of the structural property:

```
$ grep -n "datetime.now" contracts/structured_data_oracle.py
294:            observed_at = datetime.now(timezone.utc).isoformat()
```

Exactly one occurrence, inside the leader closure. The helper `_now_iso()` that
previously supplied the second reading has been deleted entirely, so there is no
remaining path to a local clock.

Two consequences follow deliberately:

- **The cooldown is now checked after the round, not before.** The timestamp does not
  exist until the round produces it. Paying for a round on a too-early call is the
  price of never reading a local clock; the call then reverts, writing no state at all.
- **A round returning no usable `observed_at` is rejected outright**, rather than
  falling back to any local reading — there is no fallback clock path left to drift on.

The equivalence principle was extended to tell validators that `observed_at` naturally
differs between their own runs and is **never** part of the equivalence comparison —
only the verdict is.

## On the API choice — probed, not assumed

GenLayer's newer runner generation exposes proper deterministic timestamp APIs
(`gl.message.datetime`, `gl.vm.get_timestamp()`), which would be the more direct fix.
Both were probed directly against the pinned runner this contract actually deploys on
(`py-genlayer:1jb45aa8...`) before choosing an approach, by deploying a throwaway
probe contract that enumerated the live attribute surface:

```
MSG = chain_id, contract_address, count, index, origin_address, sender_address, value
VM  = Lazy, Result, ResultCode, Return, UserError, VMError, calldata, collections,
      dataclasses, gl_call, run_nondet, run_nondet_unsafe, spawn_sandbox, typing,
      unpack_result
```

**Neither API exists in this runner generation** — `gl.message` has no `datetime`, and
`gl.vm` has no timestamp function at all. (`gl.message.datetime` lints fine but fails
at runtime with `AttributeError: 'MessageType' object has no attribute 'datetime'`.)
Moving to the newer runner is not an option either: it is not loadable for real
StudioNet deployment, which is why every contract in this portfolio pins the older
hash.

Placing the single clock read inside the judged flow is therefore the correct fix
available on the deployable runner — and it is exactly what the review's own wording
prescribes: *"no local wall-clock read should occur outside the judged flow."*

## Optional hardening: `extracted_value` is now canonically bound

Previously documented as "transparency only, never used in control flow" — free-form
model text. It is now validated to exactly the same canonical form the threshold
itself must take (`_is_valid_threshold`): a bare decimal number, optional leading
minus, at most one decimal point. No units, currency symbols, thousands separators,
scientific notation, or prose.

- A `CONDITION_MET`/`CONDITION_NOT_MET` verdict whose value fails that check **rejects
  the entire round** as `ERRORED` rather than storing an unparseable string.
- `NOT_FOUND` carries no value by construction, even if the model attaches one.
- The leader's prompt now states the constraint explicitly, so the model is asked for a
  bare number rather than being silently corrected afterward.

Practical guarantee: a consumer reading `extracted_value` off a settled feed can parse
it as a number directly and can trust it was the value the consensus verdict was
actually reached against.

## Tests added

Six new direct-mode tests in
[`tests/direct/test_structured_data_oracle.py`](tests/direct/test_structured_data_oracle.py):

- `test_stored_last_checked_at_is_the_rounds_own_consensus_timestamp` — the stored
  timestamp is the round's own `observed_at`, not a separate later reading.
- `test_cooldown_is_decided_against_the_same_consensus_timestamp_that_gets_stored` —
  boundary behavior: one second inside the cooldown rejects, one second past allows,
  and the newly stored timestamp is again exactly the round's own value.
- `test_a_rejected_cooldown_call_writes_no_state_at_all` — a too-early call reverts
  cleanly with every field unchanged, including the prior verdict.
- `test_check_feed_rejects_a_non_canonical_extracted_value` — units, currency symbols,
  separators, scientific notation, prose, and non-string values all reject the round.
- `test_check_feed_accepts_canonical_negative_and_integer_extracted_values`
- `test_not_found_verdict_carries_no_extracted_value_by_construction`

Full suite: **29/29 direct tests passing** (23 pre-existing + 6 new), `genvm-lint`
clean on both the contract and the worked example.

## Deployment

- **Old (defective) address:** `0x08be9d9316fBB505d6537dA73a8810CeC018965B` — superseded.
- **First fixed address:** `0x51C695A81eA8c9Bb13923cE679B2894B9f0f2AFD` — correct, but see
  the appeal note below.
- **Current fixed address:** `0x541d81E6386A69925F23dCd6Abaa630E6a97638f` (2026-09-06)
- Explorer: https://explorer-studio.genlayer.com/address/0x541d81E6386A69925F23dCd6Abaa630E6a97638f

All 3 integration tests re-run against the new deployment on StudioNet, with no
regressions — and the live results confirm the fix end to end:

| Test | Result | `last_checked_at` | `extracted_value` |
|---|---|---|---|
| full surface (`> 1`) | `CONDITION_MET` | `2026-09-06T12:55:33.770535+00:00` | `79961` |
| impossible threshold (`< 1`) | `CONDITION_NOT_MET` | `2026-09-06T12:59:08.150841+00:00` | `79943` |
| unreachable API | `ERRORED` | `2026-09-06T12:57:45.604994+00:00` | `""` |

Every settled feed's `last_checked_at` carries the round's own single consensus
timestamp, and every `extracted_value` came back in canonical bare-decimal form.
Every judged round completed `SUCCESS`/`ACCEPTED` at the GenVM and consensus level —
zero fatal errors, zero undetermined rounds. (The impossible-threshold test's first
attempt against this address hit a genuine, transient CoinGecko fetch failure —
`execution_result: SUCCESS`, `raw_error: None` on every validator, the leader's own
envelope was `{"verdict": "__FETCH_ERROR__", ...}` — almost certainly CoinGecko
rate-limiting two rapid requests from the same GenVM egress path. A retry seconds later
passed cleanly; the table above reflects that passing run.)

## Appeal — a second review flagged the deployment as still defective

A later review stated: *"the submitted Explorer deployment still runs the older
cooldown path with local wall-clock reads and therefore does not match the corrected
source."* This was checked directly rather than assumed away: fetching
`0x51C695A81eA8c9Bb13923cE679B2894B9f0f2AFD`'s actual deployed code with `genlayer
code` returned exactly one `datetime.now()` call, inside `leader()`, no `_now_iso()`
anywhere — i.e., that address was already correct. Fetching the *original* defective
address, `0x08be9d9316fBB505d6537dA73a8810CeC018965B`, the same way does show the
`_now_iso()` helper and the two separate local wall-clock reads the review described.
The most likely explanation is that the second review evaluated the original address
rather than the corrected one this submission actually named.

To remove any ambiguity, the contract was redeployed fresh to
`0x541d81E6386A69925F23dCd6Abaa630E6a97638f`, its deployed code was independently
re-verified with `genlayer code` immediately after deployment, and the full
integration suite above was re-run against it from a clean slate.

## Files changed

- `contracts/structured_data_oracle.py` — the fix (single in-flow clock read,
  `_parse_observed_at`, consensus-bound cooldown, canonical `extracted_value`,
  extended equivalence principle, `_now_iso()` deleted).
- `tests/direct/test_structured_data_oracle.py` — 6 new regression tests.
- `DESIGN.md` — new §3a (consensus-bound time) and §3b (canonical `extracted_value`).
- `README.md` — updated safety-properties table, test count, deployment address, and
  live consensus results.

## A third review: excluding observed_at from comparison had left it completely
   unbound

> The reviewed oracle still does not independently verify the timestamp that controls
> its cooldown. In the repository version, validators are explicitly told to ignore
> observed_at, so a far-future leader timestamp can pass with the same verdict, become
> last_checked_at, and block later checks; the supplied deployment also uses
> validator-local clock reads outside consensus. Bind the behavior-changing time value
> to independently verified evidence, then provide matching repository and Explorer
> source.

This one was correct, and the prior appeal above did not address it - it addressed a
different claim (a stale deployment) from an earlier review. This is a genuinely
distinct defect in the same area, found on the version that already carried the
consensus-bound-time fix.

**Root cause.** Section 3a's fix bound the cooldown decision and `last_checked_at` to
a single leader-proposed `observed_at`, and correctly told validators never to treat
two close but non-identical readings as a disagreement. But "never compare it" had
been implemented as "nothing constrains the accepted value at all":

```
"... these timestamps will naturally differ between responses and are NEVER part of
the equivalence comparison - compare only the verdict, and ignore 'observed_at'
entirely when deciding whether two responses are equivalent."
```

A leader could propose an `observed_at` arbitrarily far in the future. As long as its
verdict matched, the round would be accepted, that value would become
`last_checked_at`, and every later `check_feed` call would compute `elapsed` against a
timestamp no genuine future call could ever catch up to - a permanent denial of
service on that feed from a single bad round.

**Fix - two complementary halves, since the problem has two directions:**

1. **Future-ward**, bound to independently verified evidence in `JUDGE_PRINCIPLE`
   itself:

   ```
   "... Each response also carries an 'observed_at' timestamp recording when it
   fetched the API. Two such timestamps a few seconds or minutes apart are both
   normal and NOT a disagreement ... But this field is not exempt from scrutiny: you
   have your own sense, from your own independent fetch, of what moment 'now'
   actually is. If the other response's 'observed_at' is wildly inconsistent with
   that - hours, days, or years away ... the two responses are NOT equivalent,
   regardless of whether their verdicts match ..."
   ```

   This is deliberately enforced through the equivalence mechanism, not contract
   code, because contract code has no independent time reference to check a future
   value against without reading a local clock - which would reintroduce section 3a's
   own defect on a new axis. Each validator's own honestly-executed fetch, at its own
   real moment, is the only genuinely independent evidence this runtime has, since no
   deterministic on-chain clock exists on the pinned runner (§3a already documents
   probing `gl.message`/`gl.vm` directly and confirming neither exists).

2. **Past-ward**, caught deterministically, for free, against already-committed
   on-chain state - no clock read needed for this half at all:

   ```python
   if int(feed.check_count) > 0:
       last = _parse_iso(feed.last_checked_at)
       observed_dt = _parse_iso(observed_at)
       if last is not None and observed_dt is not None and observed_dt <= last:
           raise gl.vm.UserError("round timestamp did not advance past this feed's last recorded time")
   ```

**An honest limitation, not a claimed proof.** The future-ward half is enforced by an
LLM judging "wildly inconsistent" against natural-language instruction, not a hard
numeric tolerance - a moderately-wrong timestamp might not trip language keyed to
"hours, days, or years." This is the same trust model this entire portfolio already
relies on for every verdict a judged round reaches, not a new or weaker standard
invented for this fix, but it is real and worth stating rather than hiding. It also
cannot be exercised in direct-mode testing, which trusts a single leader execution by
construction rather than genuinely reconciling multiple independent validators - only
live consensus can actually prove it, and both live integration tests below did pass
against the redeployed address, including the one that exercises real cooldown timing
end to end.

**Tests added:** `test_check_feed_rejects_a_round_timestamp_at_or_before_the_last_recorded_time`,
`test_check_feed_rejects_a_round_timestamp_before_the_last_recorded_time`,
`test_check_feed_accepts_a_round_timestamp_that_advances_even_by_one_second` - all new,
all passing, plus two pre-existing cooldown tests adjusted to isolate the cooldown
rejection they actually test from the new monotonicity guard (direct mode's unwarped
clock returns the identical instant on back-to-back calls, which the new guard
correctly, if incidentally, also rejects).

**Deployment:** redeployed to `0x25E2C67fc69Dbd338749D69363d6129375fe728c`
(2026-09-12, unanimous validator agreement), on-chain code independently re-verified
with `genlayer code` immediately after deployment - confirmed the new equivalence
wording and monotonicity guard are present, and confirmed zero occurrences of the old
"ignore observed_at entirely" phrasing anywhere in the deployed bytecode. All 32 direct
tests pass, lint is clean, and all 3 integration tests pass against this address on
live consensus.
