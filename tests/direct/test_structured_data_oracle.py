"""
Direct-mode tests for StructuredDataOracle.

Naming convention: each test name states the property being verified, not
the mechanics used to verify it.
"""

from .conftest import warp_to

CONTRACT = "contracts/structured_data_oracle.py"

API_URL = "https://api.example.com/rates"
API_PATTERN = r"api\.example\.com"
FIELD_DESC = "the current USD to EUR exchange rate"
COOLDOWN = 3600


def _deploy(direct_deploy, direct_vm, sender):
    direct_vm.sender = sender
    return direct_deploy(CONTRACT)


def _create_feed(contract, direct_vm, sender, **overrides):
    direct_vm.sender = sender
    args = dict(
        api_url=API_URL,
        field_description=FIELD_DESC,
        comparator=">",
        threshold="1.05",
        check_cooldown_seconds=COOLDOWN,
    )
    args.update(overrides)
    return contract.create_feed(
        args["api_url"], args["field_description"], args["comparator"], args["threshold"], args["check_cooldown_seconds"]
    )


def _mock_response(direct_vm, body: str) -> None:
    direct_vm.mock_web(API_PATTERN, {"status": 200, "body": body})


def _mock_verdict(direct_vm, raw: str) -> None:
    direct_vm.mock_llm(r"evaluating a live data condition", raw)


# ---------------------------------------------------------------------
# Deploy / initial state
# ---------------------------------------------------------------------


def test_fresh_deploy_has_zero_feeds(direct_deploy, direct_vm, direct_owner):
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    assert int(c.feed_count()) == 0


# ---------------------------------------------------------------------
# create_feed - input validation
# ---------------------------------------------------------------------


def test_create_feed_succeeds_and_stores_declared_fields(direct_deploy, direct_vm, direct_owner):
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner)
    f = c.get_feed(feed_id)
    assert f["api_url"] == API_URL
    assert f["field_description"] == FIELD_DESC
    assert f["comparator"] == ">"
    assert f["threshold"] == "1.05"
    assert f["state"] == "NEVER_CHECKED"
    assert f["check_count"] == 0


def test_create_feed_rejects_non_https_url(direct_deploy, direct_vm, direct_owner):
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    with direct_vm.expect_revert("https://"):
        _create_feed(c, direct_vm, direct_owner, api_url="http://insecure.example.com/rates")


def test_create_feed_rejects_empty_field_description(direct_deploy, direct_vm, direct_owner):
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    with direct_vm.expect_revert("field_description must be"):
        _create_feed(c, direct_vm, direct_owner, field_description="")


def test_create_feed_rejects_invalid_comparator(direct_deploy, direct_vm, direct_owner):
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    with direct_vm.expect_revert("comparator must be one of"):
        _create_feed(c, direct_vm, direct_owner, comparator="!=")


def test_create_feed_rejects_malformed_thresholds(direct_deploy, direct_vm, direct_owner):
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    for bad in ["", "abc", "1.2.3", "1,000", "1e10", "$5", "5%", "--5"]:
        with direct_vm.expect_revert("threshold must be a plain decimal number"):
            _create_feed(c, direct_vm, direct_owner, threshold=bad)


def test_create_feed_accepts_negative_and_integer_thresholds(direct_deploy, direct_vm, direct_owner):
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner, threshold="-3.5")
    assert c.get_feed(feed_id)["threshold"] == "-3.5"
    feed_id2 = _create_feed(c, direct_vm, direct_owner, threshold="100")
    assert c.get_feed(feed_id2)["threshold"] == "100"


def test_create_feed_rejects_out_of_range_cooldown(direct_deploy, direct_vm, direct_owner):
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    with direct_vm.expect_revert("check_cooldown_seconds"):
        _create_feed(c, direct_vm, direct_owner, check_cooldown_seconds=0)


# ---------------------------------------------------------------------
# check_feed - the judged path
# ---------------------------------------------------------------------


def test_check_feed_is_permissionless_from_the_first_call(direct_deploy, direct_vm, direct_owner, direct_alice):
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner)
    _mock_response(direct_vm, '{"rate": 1.08}')
    _mock_verdict(direct_vm, '{"verdict": "CONDITION_MET", "extracted_value": "1.08"}')
    direct_vm.sender = direct_alice
    c.check_feed(feed_id)
    assert c.get_feed(feed_id)["state"] == "CONDITION_MET"


def test_check_feed_condition_met_records_extracted_value(direct_deploy, direct_vm, direct_owner):
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner, comparator=">", threshold="1.05")
    _mock_response(direct_vm, '{"data": {"usd_eur": 1.083}}')
    _mock_verdict(direct_vm, '{"verdict": "CONDITION_MET", "extracted_value": "1.083"}')
    c.check_feed(feed_id)
    f = c.get_feed(feed_id)
    assert f["state"] == "CONDITION_MET"
    assert f["extracted_value"] == "1.083"
    assert f["check_count"] == 1


def test_check_feed_condition_not_met_is_distinct_from_not_found(direct_deploy, direct_vm, direct_owner):
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner, comparator=">", threshold="2.0")
    _mock_response(direct_vm, '{"data": {"usd_eur": 1.083}}')
    _mock_verdict(direct_vm, '{"verdict": "CONDITION_NOT_MET", "extracted_value": "1.083"}')
    c.check_feed(feed_id)
    f = c.get_feed(feed_id)
    assert f["state"] == "CONDITION_NOT_MET"
    assert f["extracted_value"] == "1.083"


def test_check_feed_not_found_when_field_genuinely_absent(direct_deploy, direct_vm, direct_owner):
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner)
    _mock_response(direct_vm, '{"error": "rate limited"}')
    _mock_verdict(direct_vm, '{"verdict": "NOT_FOUND", "extracted_value": ""}')
    c.check_feed(feed_id)
    f = c.get_feed(feed_id)
    assert f["state"] == "NOT_FOUND"
    assert f["extracted_value"] == ""


def test_check_feed_on_fetch_failure_sets_errored(direct_deploy, direct_vm, direct_owner):
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner)
    # no web mock at all -> gltest's direct web-render raises inside leader()
    c.check_feed(feed_id)
    f = c.get_feed(feed_id)
    assert f["state"] == "ERRORED"
    assert f["extracted_value"] == ""


def test_check_feed_on_unparseable_output_errors_not_a_verdict(direct_deploy, direct_vm, direct_owner):
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner)
    _mock_response(direct_vm, '{"rate": 1.08}')
    direct_vm.mock_llm(r"evaluating a live data condition", "not json at all, sorry")
    c.check_feed(feed_id)
    assert c.get_feed(feed_id)["state"] == "ERRORED"


def test_check_feed_discards_an_out_of_band_verdict_label(direct_deploy, direct_vm, direct_owner):
    """A model inventing a verdict outside the declared set (including the
    leader's own internal FETCH_ERROR/LLM_ERROR sentinels, if a model
    somehow echoed one back) must never be coerced into a real state."""
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner)
    _mock_response(direct_vm, '{"rate": 1.08}')
    _mock_verdict(direct_vm, '{"verdict": "MAYBE", "extracted_value": "1.08"}')
    c.check_feed(feed_id)
    assert c.get_feed(feed_id)["state"] == "ERRORED"


def test_check_feed_rejects_before_cooldown_elapses(direct_deploy, direct_vm, direct_owner):
    from datetime import datetime, timedelta

    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner, check_cooldown_seconds=3600)
    _mock_response(direct_vm, '{"rate": 1.08}')
    _mock_verdict(direct_vm, '{"verdict": "CONDITION_MET", "extracted_value": "1.08"}')
    c.check_feed(feed_id)

    # A small forward warp - enough to clear the monotonicity guard
    # without clearing the cooldown itself - isolates this test to the
    # cooldown rejection specifically.
    first = c.get_feed(feed_id)["last_checked_at"]
    first_dt = datetime.fromisoformat(first.replace("Z", "+00:00"))
    warp_to(direct_vm, (first_dt + timedelta(seconds=1)).isoformat())
    with direct_vm.expect_revert("cooldown"):
        c.check_feed(feed_id)


def test_check_feed_permitted_again_after_cooldown_elapses(direct_deploy, direct_vm, direct_owner):
    from datetime import datetime, timedelta

    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner, check_cooldown_seconds=3600)
    _mock_response(direct_vm, '{"rate": 1.08}')
    _mock_verdict(direct_vm, '{"verdict": "CONDITION_MET", "extracted_value": "1.08"}')
    c.check_feed(feed_id)
    first_checked_at = c.get_feed(feed_id)["last_checked_at"]

    checked_dt = datetime.fromisoformat(first_checked_at.replace("Z", "+00:00"))
    warp_to(direct_vm, (checked_dt + timedelta(seconds=3601)).isoformat())

    direct_vm.clear_mocks()
    _mock_response(direct_vm, '{"rate": 0.95}')
    _mock_verdict(direct_vm, '{"verdict": "CONDITION_NOT_MET", "extracted_value": "0.95"}')
    c.check_feed(feed_id)
    f = c.get_feed(feed_id)
    assert f["check_count"] == 2
    assert f["state"] == "CONDITION_NOT_MET"


# ---------------------------------------------------------------------
# Consensus-bound timestamp: one value drives both the cooldown decision
# and the stored last_checked_at, and no clock is read outside the
# judged flow
# ---------------------------------------------------------------------


def test_stored_last_checked_at_is_the_rounds_own_consensus_timestamp(
    direct_deploy, direct_vm, direct_owner
):
    """
    The leader stamps `observed_at` once inside the judged flow and the
    contract stores exactly that value - it never takes a second, separate
    clock reading for storage. Warping the VM clock to a known instant
    before the round means the stored timestamp must be that instant, not
    some later moment sampled afterwards.
    """
    frozen = "2026-03-01T12:00:00+00:00"
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner)
    warp_to(direct_vm, frozen)
    _mock_response(direct_vm, '{"rate": 1.08}')
    _mock_verdict(direct_vm, '{"verdict": "CONDITION_MET", "extracted_value": "1.08"}')
    c.check_feed(feed_id)
    assert c.get_feed(feed_id)["last_checked_at"] == frozen


def test_cooldown_is_decided_against_the_same_consensus_timestamp_that_gets_stored(
    direct_deploy, direct_vm, direct_owner
):
    """
    Both sides of the cooldown comparison come from round timestamps, so
    the decision is reproducible from stored state alone. One second
    before the boundary must reject; one second after must allow - and the
    newly stored timestamp must again be exactly the round's own value.
    """
    from datetime import datetime, timedelta

    first = "2026-03-01T12:00:00+00:00"
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner, check_cooldown_seconds=3600)

    warp_to(direct_vm, first)
    _mock_response(direct_vm, '{"rate": 1.08}')
    _mock_verdict(direct_vm, '{"verdict": "CONDITION_MET", "extracted_value": "1.08"}')
    c.check_feed(feed_id)
    assert c.get_feed(feed_id)["last_checked_at"] == first

    first_dt = datetime.fromisoformat(first)

    # one second inside the cooldown -> rejected, and no state advanced
    warp_to(direct_vm, (first_dt + timedelta(seconds=3599)).isoformat())
    with direct_vm.expect_revert("cooldown"):
        c.check_feed(feed_id)
    still = c.get_feed(feed_id)
    assert still["check_count"] == 1
    assert still["last_checked_at"] == first

    # one second past the cooldown -> allowed, stamped with the new round
    after = (first_dt + timedelta(seconds=3601)).isoformat()
    warp_to(direct_vm, after)
    direct_vm.clear_mocks()
    _mock_response(direct_vm, '{"rate": 0.95}')
    _mock_verdict(direct_vm, '{"verdict": "CONDITION_NOT_MET", "extracted_value": "0.95"}')
    c.check_feed(feed_id)
    f = c.get_feed(feed_id)
    assert f["check_count"] == 2
    assert f["last_checked_at"] == after


def test_a_rejected_cooldown_call_writes_no_state_at_all(direct_deploy, direct_vm, direct_owner):
    """The cooldown check now runs after the judged round, so a too-early
    call must revert cleanly and leave every field exactly as it was -
    including the verdict from the previous successful round."""
    frozen = "2026-03-01T12:00:00+00:00"
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner, check_cooldown_seconds=3600)
    warp_to(direct_vm, frozen)
    _mock_response(direct_vm, '{"rate": 1.08}')
    _mock_verdict(direct_vm, '{"verdict": "CONDITION_MET", "extracted_value": "1.08"}')
    c.check_feed(feed_id)
    before = c.get_feed(feed_id)

    # A small forward warp - enough to clear the monotonicity guard
    # without clearing the cooldown itself - isolates this test to the
    # cooldown rejection specifically.
    warp_to(direct_vm, "2026-03-01T12:00:01+00:00")
    direct_vm.clear_mocks()
    _mock_response(direct_vm, '{"rate": 9.99}')
    _mock_verdict(direct_vm, '{"verdict": "CONDITION_NOT_MET", "extracted_value": "9.99"}')
    with direct_vm.expect_revert("cooldown"):
        c.check_feed(feed_id)

    assert c.get_feed(feed_id) == before


# ---------------------------------------------------------------------
# extracted_value is canonically bound, not descriptive metadata
# ---------------------------------------------------------------------


def test_check_feed_rejects_a_non_canonical_extracted_value(direct_deploy, direct_vm, direct_owner):
    """A consumer must be able to parse extracted_value as a number
    directly, so anything that isn't a bare decimal - units, currency
    symbols, separators, prose - rejects the whole round rather than being
    stored as-is."""
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    for bad in ['"1.08 USD"', '"$1.08"', '"1,080"', '"1.08e2"', '"about 1.08"', '"N/A"', "123"]:
        direct_vm.clear_mocks()
        _mock_response(direct_vm, '{"rate": 1.08}')
        _mock_verdict(direct_vm, '{"verdict": "CONDITION_MET", "extracted_value": ' + bad + "}")
        feed_id = _create_feed(c, direct_vm, direct_owner)
        c.check_feed(feed_id)
        f = c.get_feed(feed_id)
        assert f["state"] == "ERRORED", f"non-canonical value {bad} should have errored, got {f}"
        assert f["extracted_value"] == ""


def test_check_feed_accepts_canonical_negative_and_integer_extracted_values(
    direct_deploy, direct_vm, direct_owner
):
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    for good in ["-3.5", "100", "0"]:
        direct_vm.clear_mocks()
        _mock_response(direct_vm, '{"rate": 1.08}')
        _mock_verdict(direct_vm, '{"verdict": "CONDITION_MET", "extracted_value": "' + good + '"}')
        feed_id = _create_feed(c, direct_vm, direct_owner)
        c.check_feed(feed_id)
        f = c.get_feed(feed_id)
        assert f["state"] == "CONDITION_MET"
        assert f["extracted_value"] == good


def test_not_found_verdict_carries_no_extracted_value_by_construction(
    direct_deploy, direct_vm, direct_owner
):
    """NOT_FOUND means no value was found, so it must never carry one -
    even if the model tries to attach a number anyway."""
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner)
    _mock_response(direct_vm, '{"error": "rate limited"}')
    _mock_verdict(direct_vm, '{"verdict": "NOT_FOUND", "extracted_value": "1.08"}')
    c.check_feed(feed_id)
    f = c.get_feed(feed_id)
    assert f["state"] == "NOT_FOUND"
    assert f["extracted_value"] == ""


def test_check_feed_after_errored_can_be_retried_by_anyone_once_cooldown_allows(
    direct_deploy, direct_vm, direct_owner, direct_alice
):
    from datetime import datetime, timedelta

    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner, check_cooldown_seconds=1)
    c.check_feed(feed_id)  # no mocks -> ERRORED
    assert c.get_feed(feed_id)["state"] == "ERRORED"

    errored_at = c.get_feed(feed_id)["last_checked_at"]
    errored_dt = datetime.fromisoformat(errored_at.replace("Z", "+00:00"))
    warp_to(direct_vm, (errored_dt + timedelta(seconds=2)).isoformat())

    _mock_response(direct_vm, '{"rate": 1.08}')
    _mock_verdict(direct_vm, '{"verdict": "CONDITION_MET", "extracted_value": "1.08"}')
    direct_vm.sender = direct_alice
    c.check_feed(feed_id)
    assert c.get_feed(feed_id)["state"] == "CONDITION_MET"


# ---------------------------------------------------------------------
# Timestamp monotonicity - the review correction: excluding observed_at
# from cross-validator comparison (correct - each validator's own fetch
# legitimately differs) had been implemented as excluding it from ALL
# scrutiny, with nothing else constraining the accepted value. This
# deterministic half of the fix catches a leader-proposed timestamp that
# regresses behind this feed's own prior recorded time; the other half
# (binding it to what other validators can independently tell "now" is,
# which is what actually catches an implausible FUTURE value) lives in
# JUDGE_PRINCIPLE and can only be exercised on live multi-validator
# consensus, not in direct mode's single-leader-trusting execution.
# ---------------------------------------------------------------------


def test_check_feed_rejects_a_round_timestamp_at_or_before_the_last_recorded_time(
    direct_deploy, direct_vm, direct_owner
):
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner, check_cooldown_seconds=1)
    _mock_response(direct_vm, '{"rate": 1.08}')
    _mock_verdict(direct_vm, '{"verdict": "CONDITION_MET", "extracted_value": "1.08"}')
    c.check_feed(feed_id)
    before = c.get_feed(feed_id)

    # no warp at all - direct mode's clock returns the exact same instant
    # on this second call, which is not an advance
    direct_vm.clear_mocks()
    _mock_response(direct_vm, '{"rate": 9.99}')
    _mock_verdict(direct_vm, '{"verdict": "CONDITION_NOT_MET", "extracted_value": "9.99"}')
    with direct_vm.expect_revert("did not advance past this feed's last recorded time"):
        c.check_feed(feed_id)
    assert c.get_feed(feed_id) == before


def test_check_feed_rejects_a_round_timestamp_before_the_last_recorded_time(
    direct_deploy, direct_vm, direct_owner
):
    from datetime import datetime, timedelta

    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner, check_cooldown_seconds=1)
    _mock_response(direct_vm, '{"rate": 1.08}')
    _mock_verdict(direct_vm, '{"verdict": "CONDITION_MET", "extracted_value": "1.08"}')
    c.check_feed(feed_id)
    before = c.get_feed(feed_id)

    # a leader proposing a timestamp from before the feed's own recorded
    # history - the case this guard exists to catch, regardless of
    # whether it comes from a manipulated leader or a genuinely
    # desynchronized clock on whichever validator ends up leading a
    # future round
    last = c.get_feed(feed_id)["last_checked_at"]
    last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    warp_to(direct_vm, (last_dt - timedelta(seconds=10)).isoformat())
    direct_vm.clear_mocks()
    _mock_response(direct_vm, '{"rate": 9.99}')
    _mock_verdict(direct_vm, '{"verdict": "CONDITION_NOT_MET", "extracted_value": "9.99"}')
    with direct_vm.expect_revert("did not advance past this feed's last recorded time"):
        c.check_feed(feed_id)
    assert c.get_feed(feed_id) == before


def test_check_feed_accepts_a_round_timestamp_that_advances_even_by_one_second(
    direct_deploy, direct_vm, direct_owner
):
    from datetime import datetime, timedelta

    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner, check_cooldown_seconds=1)
    _mock_response(direct_vm, '{"rate": 1.08}')
    _mock_verdict(direct_vm, '{"verdict": "CONDITION_MET", "extracted_value": "1.08"}')
    c.check_feed(feed_id)

    last = c.get_feed(feed_id)["last_checked_at"]
    last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    warp_to(direct_vm, (last_dt + timedelta(seconds=1)).isoformat())
    direct_vm.clear_mocks()
    _mock_response(direct_vm, '{"rate": 9.99}')
    _mock_verdict(direct_vm, '{"verdict": "CONDITION_NOT_MET", "extracted_value": "9.99"}')
    c.check_feed(feed_id)
    assert c.get_feed(feed_id)["check_count"] == 2


# ---------------------------------------------------------------------
# Unknown ids
# ---------------------------------------------------------------------


def test_operations_on_unknown_feed_id_revert(direct_deploy, direct_vm, direct_owner):
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    with direct_vm.expect_revert("unknown feed_id"):
        c.get_feed(999)
