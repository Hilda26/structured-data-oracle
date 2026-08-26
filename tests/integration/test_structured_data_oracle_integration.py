"""
Full-surface integration test against a StudioNet-deployed
StructuredDataOracle. Requires STRUCTUREDDATAORACLE_ADDRESS (see
conftest.py).

check_feed is the slow judged write here: one real API fetch plus one
exec_prompt, in a single consensus round, so this uses a generous
wait_interval/wait_retries.
"""

import pytest
from gltest.assertions import tx_execution_succeeded, tx_execution_failed

FAST_WAIT = dict(wait_interval=3000, wait_retries=30)
SLOW_WAIT = dict(wait_interval=6000, wait_retries=100)

# Real, stable, public JSON API - no API key required. Bitcoin's USD price
# is always comfortably above 1, so this condition is reliably CONDITION_MET
# without needing to guess a live-sensitive threshold.
API_URL = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
FIELD_DESC = "the current price of Bitcoin in US dollars"
COOLDOWN = 3600


@pytest.mark.integration
def test_full_surface_drives_create_and_check_and_reads_every_view(deployed_contract, creator_account, checker_account):
    c = deployed_contract
    creator = c.connect(creator_account)
    checker = c.connect(checker_account)

    # --- deterministic write ---------------------------------------------
    create_result = creator.create_feed(args=[API_URL, FIELD_DESC, ">", "1", COOLDOWN]).transact(**FAST_WAIT)
    assert tx_execution_succeeded(create_result), create_result
    feed_id = int(c.feed_count(args=[]).call()) - 1
    feed = c.get_feed(args=[feed_id]).call()
    print("created feed:", feed)
    assert feed["state"] == "NEVER_CHECKED"
    assert feed["check_count"] == 0

    # --- the slow judged write: one real fetch + one exec_prompt -----------
    check_result = checker.check_feed(args=[feed_id]).transact(**SLOW_WAIT)
    print("check_feed receipt:", check_result)
    assert tx_execution_succeeded(check_result), (
        "check_feed failed or returned UNDETERMINED - known retryable "
        "StudioNet behavior; rerun this test if so"
    )
    checked = c.get_feed(args=[feed_id]).call()
    print("checked feed:", checked)
    assert checked["state"] in ("CONDITION_MET", "CONDITION_NOT_MET", "NOT_FOUND", "ERRORED"), checked
    assert checked["check_count"] == 1
    # Bitcoin's USD price is reliably far above 1 - a real check should
    # find the value and confirm the condition.
    assert checked["state"] == "CONDITION_MET", checked

    # --- cooldown enforcement ----------------------------------------------
    second_attempt = checker.check_feed(args=[feed_id]).transact(**FAST_WAIT)
    assert tx_execution_failed(second_attempt), "check_feed before cooldown should fail"

    # --- create_feed input validation reverts on-chain too ------------------
    bad_create = creator.create_feed(args=["http://insecure.example.com", FIELD_DESC, ">", "1", COOLDOWN]).transact(
        **FAST_WAIT
    )
    assert tx_execution_failed(bad_create), "non-https api_url should be rejected"

    # --- unknown id reverts --------------------------------------------------
    with pytest.raises(Exception):
        c.get_feed(args=[999999]).call()
