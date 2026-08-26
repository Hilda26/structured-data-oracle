"""
Tests for the worked consumer example (examples/threshold_gated_action.py).
Proves the example genuinely reads StructuredDataOracle's judged verdict
rather than re-implementing any extraction of its own.
"""

from gltest.direct.loader import create_address

from .conftest import install_call_contract_hook

CONTRACT = "examples/threshold_gated_action.py"
ORACLE_ADDRESS_SEED = "some_structured_data_oracle"


def _oracle_addr_hex(seed=ORACLE_ADDRESS_SEED):
    addr = create_address(seed)
    return "0x" + (addr if isinstance(addr, bytes) else bytes(addr.as_bytes)).hex()


def _feed_payload(state: str, extracted_value: str = "") -> dict:
    return {
        "id": 1,
        "creator": "0x" + "11" * 20,
        "api_url": "https://api.example.com/rates",
        "field_description": "the current USD to EUR exchange rate",
        "comparator": ">",
        "threshold": "1.05",
        "check_cooldown_seconds": 3600,
        "state": state,
        "extracted_value": extracted_value,
        "last_checked_at": "2026-01-01T00:00:00+00:00",
        "check_count": 1,
    }


def test_trigger_succeeds_when_condition_is_met(direct_deploy, direct_vm, direct_alice):
    direct_vm.sender = direct_alice
    c = direct_deploy(CONTRACT, _oracle_addr_hex())
    install_call_contract_hook(direct_vm, {"get_feed": _feed_payload("CONDITION_MET", "1.08")})

    c.trigger_if_condition_met(1)
    assert c.was_triggered(1) is True


def test_trigger_rejects_when_condition_not_met(direct_deploy, direct_vm, direct_alice):
    direct_vm.sender = direct_alice
    c = direct_deploy(CONTRACT, _oracle_addr_hex())
    install_call_contract_hook(direct_vm, {"get_feed": _feed_payload("CONDITION_NOT_MET", "0.95")})

    with direct_vm.expect_revert("condition is not currently met"):
        c.trigger_if_condition_met(1)
    assert c.was_triggered(1) is False


def test_trigger_rejects_when_feed_never_checked(direct_deploy, direct_vm, direct_alice):
    direct_vm.sender = direct_alice
    c = direct_deploy(CONTRACT, _oracle_addr_hex())
    install_call_contract_hook(direct_vm, {"get_feed": _feed_payload("NEVER_CHECKED")})

    with direct_vm.expect_revert("condition is not currently met"):
        c.trigger_if_condition_met(1)


def test_trigger_cannot_be_triggered_twice_for_the_same_feed(direct_deploy, direct_vm, direct_alice):
    direct_vm.sender = direct_alice
    c = direct_deploy(CONTRACT, _oracle_addr_hex())
    install_call_contract_hook(direct_vm, {"get_feed": _feed_payload("CONDITION_MET", "1.08")})

    c.trigger_if_condition_met(1)
    with direct_vm.expect_revert("already triggered"):
        c.trigger_if_condition_met(1)
