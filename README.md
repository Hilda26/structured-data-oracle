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

- **Direct-mode** (`tests/direct/`, `pytest tests/direct/`): 23 tests, no network, no
  live consensus — fast feedback on every deterministic branch, every failure/
  abstention path (including the `NOT_FOUND` vs `CONDITION_NOT_MET` distinction), and
  the worked consumer example, using gltest's built-in `mock_web`/`mock_llm`.
- **Integration** (`tests/integration/`, `pytest tests/integration/ --network=studionet`):
  requires `STRUCTUREDDATAORACLE_ADDRESS` set to a real StudioNet deployment; drives
  `create_feed` and a real judged `check_feed` against a real, stable public JSON API.

## Deployment

- Deployed StudioNet address: _pending manual deployment_
- Studio import: open [studio.genlayer.com](https://studio.genlayer.com) → "Import
  contract" → paste the deployed address once available.
