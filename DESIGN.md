# Design — StructuredDataOracle

## 1. Non-determinism budget

Exactly **one** non-deterministic operation per `check_feed` call:

- A single `gl.vm.run_nondet_unsafe(leader_fn, validator_fn)` call whose leader fetches
  the declared API URL (`gl.nondet.web.render`, text mode — API responses are plain
  text over HTTP, so the same primitive every other contract in this portfolio uses
  for web pages works unchanged for JSON) and asks `gl.nondet.exec_prompt` to find the
  described field in the raw response and evaluate it against the declared condition.
  `validator_fn` independently re-runs the same operation and decides agreement with
  ordinary Python, not a second natural-language judgment call - see §3c and §4.

## 2. Why this is a judgment call, not a JSON-path lookup

The obvious "simple" version of this primitive is deterministic: store a JSON path
(e.g. `data.rates.EUR`), fetch the URL, parse the JSON, index into it, compare the
number. That version needs no LLM, no consensus, no GenLayer at all — and it is
exactly the kind of naive oracle that breaks constantly against real public APIs:

- Field names get renamed between API versions without notice.
- The same value gets nested differently depending on region, plan tier, or an
  undocumented redesign.
- A rate-limited or errored response is very often still HTTP 200 with a JSON body —
  structurally indistinguishable from a success response to a fixed-path reader, which
  will happily extract garbage (or crash) and report it as a real value.
- Some APIs wrap a single value under different keys per endpoint version
  (`"rate"` vs `"exchangeRate"` vs `"price"`), and a path written against one version
  silently returns nothing against another.

A fixed extraction path cannot tell "the value is genuinely below threshold" from "the
API reshaped itself and my path now points at nothing" — both look identical to it:
no match, or a stale/wrong number. Reading the response for what it **means** — the
same way GenLayer validators already read a rendered web page or a screenshot for what
it shows, rather than diffing bytes — is what makes this a genuine consensus judgment
call instead of a deterministic lookup that happens to be brittle. This is the
"data-driven DeFi" and "intelligent oracle" use case GenLayer names explicitly, applied
to structured JSON instead of prose or images — the fetch and the extraction are new
here, but the underlying discipline (judgment feeds deterministic code, never the
reverse) is the same one every other primitive in this portfolio already uses.

## 3. What stays deterministic

- Feed creation and its immutable parameters (API URL, field description, comparator,
  threshold, cooldown).
- Comparator validation: only `>`, `<`, `>=`, `<=`, `==` are accepted — the model is
  never asked to invent or interpret an operator, only to apply the one already
  declared.
- Threshold format validation (`_is_valid_threshold`): a plain decimal number only, no
  scientific notation, commas, or units — keeping the declared condition unambiguous
  for the model and for any consumer reading it back.
- Output sanitization: `_parse_oracle_verdict` accepts only `CONDITION_MET`,
  `CONDITION_NOT_MET`, or `NOT_FOUND` — the leader's own `__FETCH_ERROR__`/
  `__LLM_ERROR__` sentinels are deliberately outside that set, so a fetch or call
  failure can never be mistaken for a genuine model judgment.
- Cooldown gating and the whole state-transition logic.

The model performs exactly one judgment per round — "given this raw response, does the
described value satisfy this fixed condition" — and never decides what the threshold
should be, never invents the comparator, and never controls what downstream code does
with the verdict.

## 3a. Time: exactly one consensus-bound value, never a local wall-clock read

Validators independently re-execute the whole contract call, not just the judged
closure — so **any** `datetime.now()` read in the "deterministic" outer body is not
actually deterministic across validators. Two validators evaluating the same call
microseconds apart derive different timestamps, and near a cooldown boundary that
means they can reach *opposite* allow/reject outcomes on the same transaction. An
earlier version of this contract had exactly that defect: it read the clock twice in
the outer body — once to decide the cooldown, once again to stamp `last_checked_at` —
so the two values weren't even consistent with each other within a single execution.

The fix is that the clock is read **exactly once, inside the judged flow**:

```python
def leader_fn() -> str:
    observed_at = datetime.now(timezone.utc).isoformat()   # the ONLY clock read
    ...
    model_envelope["observed_at"] = observed_at
    return json.dumps(model_envelope)
```

Whichever mechanism decides consensus - `prompt_comparative` originally, `run_nondet_unsafe`
now (§3c) - settles on a single accepted leader envelope, so that one leader-proposed
timestamp becomes the round's consensus-bound time value. The contract then uses
**that same value** for both the cooldown decision and the stored `last_checked_at` —
they are literally the same string, so they can never diverge from each other or
between validators. `grep datetime.now contracts/structured_data_oracle.py` returns
exactly one line, and it is inside the leader closure.

Two consequences follow deliberately from this:

- **The cooldown is checked after the round, not before.** The timestamp does not
  exist until the round produces it. Paying for a round on a too-early call is the
  price of never reading a local clock; the call then reverts, writing no state at all
  (`test_a_rejected_cooldown_call_writes_no_state_at_all`).
- **A round that returns no usable `observed_at` is rejected outright** rather than
  falling back to any local reading — there is no fallback clock path to drift on.

The equivalence principle explicitly instructs validators to ignore `observed_at`
when comparing responses, since each validator's own run naturally stamps a different
time and that difference is never a real disagreement about the verdict.

Note on API choice: GenLayer's newer runner generation exposes deterministic
timestamp APIs (`gl.message.datetime`, `gl.vm.get_timestamp()`), which would be the
more direct fix. Both were probed directly against the pinned runner this contract
deploys on (`py-genlayer:1jb45aa8...`) and **neither exists there** — `gl.message`
exposes only `chain_id, contract_address, count, index, origin_address,
sender_address, value`, and `gl.vm` has no timestamp function at all. Moving to the
newer runner is not an option either: it is not loadable for real StudioNet
deployment (verified earlier in this portfolio's history, and the reason every
contract here pins the older hash). Placing the single clock read inside the judged
flow is therefore the correct fix available on the deployable runner — and it is
precisely what the review's own wording asks for: "no local wall-clock read should
occur outside the judged flow."

## 3b. `extracted_value` is canonically bound, not descriptive metadata

`extracted_value` is stored and exposed by `get_feed`, so consumers can and will read
it. To make that safe, it is validated to exactly the same canonical form the
threshold itself must take (`_is_valid_threshold`): a bare decimal number, optional
leading minus, at most one decimal point — no units, currency symbols, thousands
separators, scientific notation, or prose. A `CONDITION_MET`/`CONDITION_NOT_MET`
verdict whose value fails that check **rejects the entire round** as `ERRORED` rather
than storing an unparseable string, and `NOT_FOUND` carries no value by construction
even if the model attaches one.

The practical guarantee: any consumer reading `extracted_value` off a settled feed can
parse it as a number directly, and can trust it is the value the consensus verdict was
actually reached against — never a model embellishment that happened to ride along.
The leader's prompt states the same constraint explicitly, so the model is asked for a
bare number rather than being silently corrected afterward. It remains outside all
control flow: the contract's own routing keys off the verdict category alone.

## 3c. A second review: excluding observed_at from comparison had left it
    completely unbound - and the first fix for it was still judgment, not proof

Section 3a's fix bound the cooldown decision and `last_checked_at` to a single
consensus-bound `observed_at` value, and correctly told validators never to treat two
close but non-identical `observed_at` readings as a disagreement - each validator's
own independent fetch legitimately happens at a slightly different instant. A second
review found the gap that fix left behind: "never compare it" had been implemented as
"nothing at all constrains the accepted value." A leader could propose an `observed_at`
arbitrarily far in the future, and as long as its verdict matched, the round would be
accepted, that future timestamp would become `last_checked_at`, and every subsequent
`check_feed` call would compute a negative or undersized `elapsed` against it forever -
a permanent denial of service on a single feed from one bad round.

The first attempt at this fix bound the future direction through `JUDGE_PRINCIPLE` -
asking each validator's own LLM judgment to treat a "wildly inconsistent" timestamp as
a disagreement. That closed the literal case the review described, but on reflection it
was still enforcement by prose, not by proof: a moderately-wrong timestamp, short of
"hours, days, or years," might not trip language that loose, and there was no way to
demonstrate a hard boundary because none existed.

**The actual fix replaces the equivalence mechanism itself.** `check_feed` no longer
uses `gl.eq_principle.prompt_comparative` with a natural-language principle at all. It
uses `gl.vm.run_nondet_unsafe(leader_fn, validator_fn)` - GenLayer's own "custom
validator function" primitive, where `validator_fn` is ordinary Python code, not an LLM
prompt, that independently re-runs `leader_fn()` and decides agreement by comparison,
not judgment:

```python
def validator_fn(leader_result) -> bool:
    if not isinstance(leader_result, gl.vm.Return):
        try:
            leader_fn()
            return False
        except Exception:
            return True

    leader_raw = leader_result.calldata
    my_raw = leader_fn()

    leader_category = _verdict_category(leader_raw)
    my_category = _verdict_category(my_raw)
    if leader_category != my_category:
        return False
    if leader_category is None:
        return True

    leader_dt = _parse_iso(_parse_observed_at(leader_raw))
    my_dt = _parse_iso(_parse_observed_at(my_raw))
    if leader_dt is None or my_dt is None:
        return False

    skew = abs((leader_dt - my_dt).total_seconds())
    return skew <= MAX_CLOCK_SKEW_SECONDS
```

Two independent guarantees, both now arithmetic:

- **Verdict agreement** is exact-string equality on the canonical `verdict` enum
  (`CONDITION_MET` / `CONDITION_NOT_MET` / `NOT_FOUND`, or one of the leader's own
  `__FETCH_ERROR__`/`__LLM_ERROR__` sentinels) - not LLM judgment of "close enough."
  This is strictly *more* faithful to the original design intent than the old
  `prompt_comparative` principle, which already said "compare only the verdict" in
  prose; here that is simply what the code does. `extracted_value` is deliberately
  excluded from this comparison (as it always was) since it may legitimately differ
  between two genuinely independent live fetches of a value that can itself tick
  between requests (§4a's own `strict_eq` discussion covers why exact-JSON equality
  would be the wrong tool for that reason).
- **Timestamp agreement** requires the leader's proposed `observed_at` to fall within
  `MAX_CLOCK_SKEW_SECONDS` (300s) of this validator's own, independently-observed
  moment - a hard numeric bound, generous enough to absorb real fetch-plus-LLM latency
  between two genuinely independent executions, and enormously tighter than "hours,
  days, or years." A leader proposing a timestamp outside that window fails
  `validator_fn` outright, regardless of how well its verdict matches.

This still cannot bound the future direction with total precision - `MAX_CLOCK_SKEW_SECONDS`
is a chosen tolerance, not a proof that no dishonest value inside it could ever be
harmful, and it remains true (per section 3a) that no deterministic on-chain clock
exists on this runner to check against instead. What changed is that the bound is now a
number in the code, provable by unit test, rather than a hope that an LLM reads
"wildly inconsistent" the way a human author intended.

Verified directly, not just inferred from the happy path continuing to work:
`test_validator_rejects_a_leader_claiming_a_far_future_timestamp` and
`test_validator_rejects_a_leader_claiming_a_far_past_timestamp` reproduce the exact
attack the review described and confirm `validator_fn` returns `False`;
`test_validator_accepts_a_timestamp_exactly_at_the_clock_skew_boundary` and
`test_validator_rejects_a_timestamp_one_second_past_the_clock_skew_boundary` pin the
boundary to the exact second; `test_validator_rejects_a_leader_whose_verdict_disagrees_with_its_own_independent_run`
and `test_validator_agrees_when_both_independently_hit_the_same_fetch_error` cover the
verdict-agreement half. These are genuine invocations of the real `validator_fn`
against a crafted leader result via gltest's `direct_vm.run_validator()` - not
inferred from `check_feed`'s own happy-path tests, which never execute `validator_fn`
at all (direct mode calls `leader_fn()` once and trusts it by construction; it only
*records* `validator_fn` for a test to invoke separately, which is exactly what these
tests do). The deterministic monotonicity check below remains as a second, independent
line of defense on the past-regression direction specifically, needing no clock or
validator re-execution at all:

```python
if int(feed.check_count) > 0:
    last = _parse_iso(feed.last_checked_at)
    observed_dt = _parse_iso(observed_at)
    if last is not None and observed_dt is not None and observed_dt <= last:
        raise gl.vm.UserError("round timestamp did not advance past this feed's last recorded time")
```

## 4. Consensus mechanism (custom leader/validator, not a natural-language principle)

`check_feed`'s judged round is decided by `gl.vm.run_nondet_unsafe(leader_fn, validator_fn)`
- see §3c for `validator_fn`'s full text and rationale. `leader_fn` is unchanged from
section 3a: it fetches the API live, reads the clock exactly once, asks the model to
classify the result into the closed `CONDITION_MET`/`CONDITION_NOT_MET`/`NOT_FOUND` set
plus a canonical bare-decimal `extracted_value`, and returns the JSON envelope. There is
no natural-language equivalence principle in this contract any more; agreement is
decided entirely by `validator_fn`'s own Python comparison.

`extracted_value` is canonically bound (§3b) and carried for transparency and audit
(it's stored and returned by `get_feed`, so anyone can see what the model actually
read), never used in any control-flow decision and never part of what `validator_fn`
compares.

## 4a. Equivalence-strategy choice, checked against GenLayer's own guidance and its own
    reference prediction-market contract

GenLayer's own build guidance names three equivalence strategies: `strict_eq` for
exact-match consensus, `prompt_comparative`/`prompt_non_comparative` as LLM-judged
convenience wrappers, and a custom leader/validator pair (`run_nondet_unsafe`) "for
full control over consensus logic." This contract now uses the third, and for the same
underlying reason the second review pushed toward it: judging the *verdict* by meaning
still benefits from an LLM comparing substance over exact wording in principle, but the
review made clear that a *provable* bound (§3c) needed real code, not a prompt.
`run_nondet_unsafe` gets both at once - `validator_fn` is free to call whatever
LLM-backed logic it needs (it does, by calling `leader_fn()` itself) while deciding
agreement with ordinary Python.

`strict_eq` remains the wrong tool here regardless: it requires validators to
reproduce exactly the same normalized output, and this contract is a reusable registry
over *arbitrary, creator-declared* API endpoints whose whole reason for existing is
that such endpoints are *not* structurally stable across providers or versions (§2
above). Two honest validators reading the same value under a renamed key, or a source
whose price ticks between two fetches a few seconds apart, could disagree on exact
JSON text without disagreeing on what the data actually says - exactly the failure
comparing the parsed *verdict category* (§3c), not the raw response, is built to avoid.

Worth checking against GenLayer's own shipped example, since it's the one place their
docs show a working "prediction market" pattern end to end: it resolves a single,
hardcoded sports fixture by fetching one fixed, structurally stable BBC Sport page and
uses `gl.eq_principle.strict_eq()` to require validators to reproduce byte-identical
output. That's the right call for *that* contract - one known-stable source, one fixed
extraction - and it is itself already an instance of comparing a narrow, canonical
result rather than raw response text, the same instinct `validator_fn`'s
`_verdict_category` comparison applies here. It is not evidence that full `strict_eq`
(byte-identical output with no custom logic at all) would suit this contract, since a
declared API's shape can legitimately drift in ways a single sports fixture's page
does not. Note also that even GenLayer's own "stable source" example still reserves an
explicit "unresolved" sentinel (`-1`/`"-"`) for when extraction fails, rather than
guessing - the same fail-safe instinct behind this contract's `NOT_FOUND`/`ERRORED`
split.

## 5. Failure and abstention semantics

- **The API fails to fetch at all**: no judgment is even attempted — the leader
  returns a `FETCH_ERROR` sentinel before ever calling `exec_prompt`. Distinct from
  `NOT_FOUND`, which means the fetch succeeded but the described value genuinely isn't
  in the response.
- **`NOT_FOUND` vs `CONDITION_NOT_MET`**: kept deliberately distinct states, never
  collapsed into one "false" outcome. `NOT_FOUND` means "we don't know whether the
  condition holds, because the value isn't there to check." `CONDITION_NOT_MET` means
  "we know the value, and it doesn't satisfy the condition." A consumer contract
  gating on `CONDITION_MET` never needs to tell these apart to be safe (both fail the
  gate), but an operator watching the feed absolutely does — `NOT_FOUND` is the signal
  that the API or the field description needs attention, `CONDITION_NOT_MET` just
  means "not yet."
- **Unparseable model output, or a verdict label outside the declared set**: the whole
  round is rejected as `ERRORED`, never silently coerced into any of the three real
  states.
- **Fail-safe direction**: always toward *not* asserting a condition is met on
  ambiguous or missing evidence. `extracted_value` is cleared (not left stale) whenever
  the round errors, so a consumer reading `get_feed` after a failed round never sees a
  number that implies a successful extraction that didn't happen.
- `check_feed` is always re-callable (subject only to the cooldown) from any prior
  state, including `ERRORED` — no terminal "stuck forever" state, matching the
  refreshable-snapshot philosophy already used by VisualClaim and SourceConsensus (a
  Feed is a standing oracle question, not a one-shot claim to protect from replay).

## 5a. Deliberately checked against every prior correction in this portfolio

Three real review findings have already landed on earlier submissions here. Before
calling this design done, each was checked against `check_feed` directly:

- **HandleGuard's TOCTOU fix** (a shortlist frozen at request time judged against a
  *shared, mutable* set — other users' handles — that could drift before an async
  consensus round completed): does not apply. `check_feed` fetches everything it
  judges live, inside the same round, every single time. There is no frozen
  intermediate snapshot, and no Feed's verdict is ever compared against another Feed's
  mutable state — each Feed is judged entirely against its own immutable parameters
  and the live API response, with nothing else in the contract that could have drifted
  underneath it between request and resolution.
- **SourceConsensus's stale-verdicts-on-error fix** (a prior successful round's
  per-source labels survived visible after a later round failed to parse): already
  handled correctly from the first version of this contract, not patched in after the
  fact - `extracted_value = ""` sits in the exact same branch as `state = STATE_ERRORED`
  (see `check_feed`'s `if not verdict["ok"]:` block), so a failed re-check can never
  leave a prior round's extracted value looking current. Verified directly by
  `test_check_feed_on_fetch_failure_sets_errored`, which asserts both fields together.
- **DisputeArbiter's bounded-timeout-exit fix** (a permanently unreachable evidence URL
  could lock two parties' *escrowed stakes* forever, since `ERRORED` was retryable but
  never guaranteed to resolve): does not apply, for a structural reason rather than an
  oversight - `StructuredDataOracle` never escrows value. It has no payable method and
  nothing at stake. A Feed stuck in `ERRORED` forever because its API died means
  exactly one thing: that Feed stops producing fresh readings. Nothing is locked,
  nothing needs a bounded exit to recover, because there was never anything to recover
  - the same reason VisualClaim's and SourceConsensus's own refreshable-oracle designs
  were never asked to add one either. A bounded timeout exit is specifically the
  answer to "funds are stuck," not to "this data feed is stale," and conflating the two
  would be solving a problem this contract doesn't have.

## 6. Storage layout

```
Feed:
  id: u256
  creator: Address
  api_url: str                      # immutable
  field_description: str            # immutable
  comparator: str                   # immutable, one of >, <, >=, <=, ==
  threshold: str                    # immutable, plain decimal number as text
  check_cooldown_seconds: u256      # immutable
  state: str                        # NEVER_CHECKED | CONDITION_MET |
                                     # CONDITION_NOT_MET | NOT_FOUND | ERRORED
  extracted_value: str              # canonical decimal (see 3b), never in control flow
  last_checked_at: str              # the round's own consensus timestamp (see 3a)
  check_count: u256
```

`feeds: TreeMap[u256, Feed]`, keyed by an incrementing counter — the same registry
pattern as the rest of the portfolio.

## 7. The consumer interface

```python
@gl.contract_interface
class IStructuredDataOracle:
    class View:
        def get_feed(self, feed_id: u256) -> dict: ...
    class Write:
        pass
```

**Pull, not push**: a consumer polls `get_feed` for `state == "CONDITION_MET"`. See
`examples/threshold_gated_action.py` for a worked consumer that triggers an action once
a feed's condition is satisfied.

## 8. Trust model

| Role | Powers | Cannot |
|---|---|---|
| Feed creator | Declare the API, field description, comparator, threshold, and cooldown once, at creation | Cannot edit any of them afterward — no setter exists at all; cannot bias what the contract reads at the API |
| Anyone (permissionless) | Call `check_feed` on any feed, including the very first check | Cannot resolve it to anything other than what consensus judges from the actual fetched response |

Unlike VisualClaim's `reverify`, there is no "only the claimant may trigger the first
check" restriction — a Feed is a shared, public data-condition question from the
moment it's created, exactly like SourceConsensus's Query, so gating the first call
would serve no protective purpose here.

## 9. Latency budget

- `create_feed`: pure deterministic write, ~20-40s on StudioNet.
- `check_feed`: one consensus round, one page fetch, one `exec_prompt` — comparable to
  VisualClaim's `reverify` in shape (single fetch, single judgment), just reading a
  JSON body instead of a screenshot.
