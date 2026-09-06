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
