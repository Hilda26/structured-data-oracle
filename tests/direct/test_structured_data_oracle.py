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
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    feed_id = _create_feed(c, direct_vm, direct_owner, check_cooldown_seconds=3600)
    _mock_response(direct_vm, '{"rate": 1.08}')
    _mock_verdict(direct_vm, '{"verdict": "CONDITION_MET", "extracted_value": "1.08"}')
    c.check_feed(feed_id)
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
# Unknown ids
# ---------------------------------------------------------------------


def test_operations_on_unknown_feed_id_revert(direct_deploy, direct_vm, direct_owner):
    c = _deploy(direct_deploy, direct_vm, direct_owner)
    with direct_vm.expect_revert("unknown feed_id"):
        c.get_feed(999)
