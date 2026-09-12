# StructuredDataOracle

A reusable GenLayer Intelligent Contract that lets any app watch a live JSON API
against a declared condition — "is this exchange rate above X," "has this protocol's
TVL crossed Y" — without hardcoding a JSON path that breaks the moment the API
reshapes itself. Any app that needs "does live structured data currently satisfy this
condition" decided fairly imports this instead of writing its own fetch-and-extract
oracle logic.

## The problem with the naive version

The obvious implementation is a deterministic JSON-path lookup: fetch the URL, parse
the JSON, index into a fixed path, compare the number. It needs no LLM and no
consensus — and it is exactly the class of oracle that breaks constantly in practice.
Real public APIs rename fields between versions without notice, nest the same value
differently across regions or plan tiers, and very often return a rate-limit or error
message as an ordinary HTTP 200 JSON body — structurally indistinguishable from a
success response to a fixed-path reader, which will happily extract garbage (or find
nothing) and report it as if the fetch had genuinely succeeded. A fixed path cannot
tell "the value is really below threshold" from "the API changed shape and my path
points at nothing anymore" — both look the same to it.

## Why this needs validator consensus, not a backend

Delete GenLayer and this either falls back to the brittle fixed-path script above, or
to a backend service that fetches and extracts invisibly (no way for anyone relying on
the result to check the extraction was done honestly, or done at all). Run the
counterfactual against each alternative:

- **A fixed JSON-path script** — breaks silently the moment the API reshapes itself;
  can't distinguish a real "condition not met" from "my path is now wrong."
- **A backend fetch-and-extract service** — the fetch and extraction are invisible;
  nothing stops it from reporting a stale or fabricated value.
- **A single LLM call over backend-supplied text** — combines an unverifiable fetch
  with an unrepeatable judgment.
- **Trusting the API's own labeling of its data** — many public APIs don't declare a
  stable schema at all; there's nothing to "trust" beyond hoping the shape doesn't
  change.

GenLayer's validator set independently fetches the same API endpoint and independently
reads the response for what it actually contains — recognizing the described value
under whatever key, nesting, or casing it happens to appear as — reconciling under an
equivalence principle that requires agreement on the verdict category, not on incidental
formatting. No single party decides alone whether live structured data satisfies a
condition, and the read is on real, contract-fetched content every time, never a
cached or backend-supplied summary.

## Why it isn't the patterns that don't belong in this category

- **Not an AI app with a blockchain attached.** The output is a state transition — a
  feed is `CONDITION_MET`, `CONDITION_NOT_MET`, `NOT_FOUND`, or `ERRORED` — never advice
  a human reads and acts on manually.
- **Not a format-only validator.** The equivalence principle compares the verdict
  category itself, never whether the model's JSON merely parses.
- **Not judging claimant-submitted evidence.** `check_feed` takes no response body as
  an argument at all — the API is fetched contract-side, live, on every call. A
  creator can declare which URL and field to watch, but cannot supply what the
  contract sees there.
- **Structurally distinct from every other submission in this portfolio.**
  ParametricPool and VisualClaim each judge a single piece of unstructured evidence
  (a rendered page, a screenshot). HandleGuard never fetches anything. SourceConsensus
  reconciles a cooperative set of *unstructured* sources toward one shared answer.
  DisputeArbiter judges adversarial unstructured evidence between two staked parties.
  StructuredDataOracle is the first primitive here to read *structured* data (JSON)
  under schema drift and evaluate it against a fixed numeric condition — a genuinely
  different evidence modality and judgment shape, not a relabeled copy of any of them.
- **Not a prediction market itself, and not trying to be one.** GenLayer's own docs
  name "prediction markets with subjective outcomes" as a use case and ship a
  reference example that resolves a single sports fixture from a fixed web page.
  StructuredDataOracle is deliberately one layer beneath that: a reusable, multi-tenant
  *oracle* that any number of markets, DeFi contracts, or automations could poll for
  "does live structured data currently satisfy this condition" — the same
  input-layer relationship a real prediction market has to a real-world data feed,
  just for JSON APIs instead of one hardcoded sports page. It holds no stakes, runs no
  market, and settles no bets; ParametricPool already covers this portfolio's
  pooled-value settlement territory, and mixing that concern in here would blur what
  each primitive is actually for.

## The non-deterministic core, and why the deterministic half is just as load-bearing

Exactly **one** non-deterministic operation, bundled into a single
`gl.eq_principle.prompt_comparative` block: a leader function that fetches the
declared API URL (`gl.nondet.web.render`, text mode — the same primitive used for web
pages elsewhere in this portfolio works unchanged for a JSON response, since it's just
fetching raw text over HTTPS) and asks `gl.nondet.exec_prompt` to find the described
value and evaluate it against the declared comparator and threshold. The model never
decides what the threshold should be, never invents the comparator, and the
deterministic half is where every actual consequence lives: comparator/threshold
validation at creation, cooldown gating, and strict output sanitization that keeps a
fetch failure from ever being mistaken for a genuine judgment. Full rationale in
`DESIGN.md`.

## Safety properties

| Property | Enforced by | Verified by |
|---|---|---|
| A feed's API, field description, comparator, and threshold can never be edited after creation | no setter exists at all | `test_create_feed_succeeds_and_stores_declared_fields` and the absence of any editing method |
| Only a fixed set of comparators is ever accepted - the model never invents an operator | `create_feed` validates against `VALID_COMPARATORS` | `test_create_feed_rejects_invalid_comparator` |
| A malformed threshold (units, commas, scientific notation) can never be declared | `_is_valid_threshold` rejects anything but a plain decimal number | `test_create_feed_rejects_malformed_thresholds` |
| A fetch failure is never mistaken for a genuine "condition not met" judgment | the leader returns a `FETCH_ERROR` sentinel before ever calling `exec_prompt`, routing to `ERRORED` | `test_check_feed_on_fetch_failure_sets_errored` |
| "The value isn't there" is never conflated with "the value is there but fails the condition" | `NOT_FOUND` and `CONDITION_NOT_MET` are kept as distinct states | `test_check_feed_condition_not_met_is_distinct_from_not_found`, `test_check_feed_not_found_when_field_genuinely_absent` |
| An out-of-band verdict label is never coerced into a real state | `_parse_oracle_verdict` accepts only the three declared verdicts | `test_check_feed_discards_an_out_of_band_verdict_label` |
| A failed round never leaves a stale extracted value looking current | `extracted_value` is cleared whenever `check_feed` errors | `test_check_feed_on_fetch_failure_sets_errored` |
| Validators can never derive different timestamps or opposite cooldown outcomes | the clock is read exactly once, inside the judged flow; that single consensus-bound value drives both the cooldown decision and the stored `last_checked_at` | `test_stored_last_checked_at_is_the_rounds_own_consensus_timestamp`, `test_cooldown_is_decided_against_the_same_consensus_timestamp_that_gets_stored` |
| A cooldown-rejected call writes no state at all | the check runs after the round and reverts, rolling everything back | `test_a_rejected_cooldown_call_writes_no_state_at_all` |
| `extracted_value` is always a parseable number a consumer can rely on, never prose | validated to the same canonical decimal form as the threshold; a non-canonical value rejects the whole round | `test_check_feed_rejects_a_non_canonical_extracted_value`, `test_not_found_verdict_carries_no_extracted_value_by_construction` |
| Anyone can push a stuck `ERRORED` feed forward, not just the creator | `check_feed` has no caller restriction, ever | `test_check_feed_after_errored_can_be_retried_by_anyone_once_cooldown_allows` |
| A feed is a shared public oracle from the first call, not a personal claim | no "creator only" gate on the first check | `test_check_feed_is_permissionless_from_the_first_call` |

## Why it's reusable

The consumer integration is genuinely small — this is the whole thing, from
`examples/threshold_gated_action.py`:

```python
@gl.contract_interface
class IStructuredDataOracle:
    class View:
        def get_feed(self, feed_id: u256) -> dict: ...
    class Write:
        pass

feed = IStructuredDataOracle(self.oracle_address).view().get_feed(feed_id)
if feed["state"] == "CONDITION_MET":
    ...  # trigger whatever this contract controls
```

Any DeFi, automation, or alerting contract that needs to act on "does live structured
data satisfy this condition" can gate on that instead of writing its own JSON-fetch-
and-extract logic — the exact same "read a verdict, never re-derive it" shape every
other worked example in this portfolio already uses, applied to a genuinely new
underlying primitive.

## Testing

- **Direct-mode** (`tests/direct/`, `pytest tests/direct/`): 32 tests, no network, no
  live consensus — fast feedback on every deterministic branch, every failure/
  abstention path (including the `NOT_FOUND` vs `CONDITION_NOT_MET` distinction), the
  deterministic half of the timestamp-monotonicity guard, and the worked consumer
  example, using gltest's built-in `mock_web`/`mock_llm`.
- **Integration** (`tests/integration/`, `pytest tests/integration/ --network=studionet`):
  3 tests, requires `STRUCTUREDDATAORACLE_ADDRESS` set to a real StudioNet deployment;
  drives `create_feed` and real judged `check_feed` rounds covering `CONDITION_MET`,
  `CONDITION_NOT_MET`, and a genuinely unreachable API (`ERRORED`), plus cooldown and
  input-validation reverts on-chain.

## Deployment

- Deployed StudioNet address: `0x25E2C67fc69Dbd338749D69363d6129375fe728c` (redeployed
  2026-09-12 for the timestamp-binding fix described below. Supersedes
  `0x541d81E6386A69925F23dCd6Abaa630E6a97638f` and `0x51C695A81eA8c9Bb13923cE679B2894B9f0f2AFD`,
  and none of these should be confused with `0x08be9d9316fBB505d6537dA73a8810CeC018965B`,
  the original defective deployment that read a local wall clock outside the judged
  flow — see `REVIEW.md`. The deployed code at this address was fetched directly with
  `genlayer code` and confirmed to contain exactly one `datetime.now()` call, inside
  `leader()`, the new timestamp-binding equivalence wording, and the new deterministic
  monotonicity guard — with zero occurrences of the old "ignore observed_at entirely"
  phrasing anywhere in the deployed bytecode.)
- Explorer: https://explorer-studio.genlayer.com/address/0x25E2C67fc69Dbd338749D69363d6129375fe728c
- Studio import: open [studio.genlayer.com](https://studio.genlayer.com) → "Import
  contract" → paste `0x25E2C67fc69Dbd338749D69363d6129375fe728c`.

## A second review: excluding observed_at from comparison had left it unbound

> The reviewed oracle still does not independently verify the timestamp that controls
> its cooldown. In the repository version, validators are explicitly told to ignore
> observed_at, so a far-future leader timestamp can pass with the same verdict, become
> last_checked_at, and block later checks; the supplied deployment also uses
> validator-local clock reads outside consensus. Bind the behavior-changing time value
> to independently verified evidence, then provide matching repository and Explorer
> source.

Real, and fixed with two complementary changes - full technical rationale in
`DESIGN.md` §3c and the review response in `REVIEW.md`:

1. `JUDGE_PRINCIPLE` no longer tells validators to ignore `observed_at` outright. It
   now binds the leader's proposed timestamp to each validator's own independently
   fetched sense of "now" - the only genuinely independent time evidence this runtime
   has, since no deterministic on-chain clock exists on the pinned runner (confirmed by
   directly probing its attribute surface). A wildly inconsistent value - the far-future
   case the review named - is now a real disagreement, not something validators are
   told to overlook.
2. `check_feed` deterministically rejects any accepted `observed_at` that does not
   strictly exceed the feed's own `last_checked_at`, checked purely against
   already-committed on-chain state - closing the complementary past-regression
   direction for free, with no clock read at all.

## Measured on live consensus

All 3 integration tests passed against the address above, covering every real verdict
this contract can reach — not just the easy case:

- **`test_full_surface_drives_create_and_check_and_reads_every_view`**: a feed
  watching "the current price of Bitcoin in US dollars" from CoinGecko's live public
  API against `> 1` resolved to `extracted_value: "77289"`, `state: CONDITION_MET`.
  Cooldown enforcement, the new timestamp-binding equivalence wording, and
  `create_feed` input-validation reverts all verified on-chain in the same run.
- **`test_check_feed_reaches_condition_not_met_on_a_real_impossible_threshold`**: the
  same real API, condition flipped to `< 1` (something Bitcoin's price can never
  satisfy) — the judged round still correctly *found* the real value
  (`extracted_value: "77283"`) and correctly reported `CONDITION_NOT_MET`, proving the
  negative path is a genuine judgment, not a default.
- **`test_check_feed_with_unreachable_api_completes_without_genvm_or_consensus_error`**:
  a genuinely dead domain reached `state: ERRORED` with `extracted_value` cleared,
  while the transaction itself still completed `SUCCESS`/`ACCEPTED` at the GenVM and
  consensus level — a real fetch failure absorbed as contract-level state, never a
  GenVM execution error.

In every case, the judged round located the described value inside the API's raw JSON
response (`{"bitcoin":{"usd":...}}`) without any hardcoded path. Every judged round
across this contract's testing has completed `SUCCESS`/`ACCEPTED` at the GenVM and
consensus level — zero fatal errors, zero undetermined rounds.

These runs also confirm the consensus-timestamp fix end to end: every settled feed's
`last_checked_at` carries the round's own single `observed_at` value (e.g.
`2026-08-30T16:10:52.371007+00:00`), and every `extracted_value` came back in
canonical bare-decimal form (`78853`, `78793`, and `""` for the errored feed) rather
than as free-form model text.
