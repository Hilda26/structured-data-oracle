# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *

# ---------------------------------------------------------------------------
# ThresholdGatedAction - a worked consumer of the StructuredDataOracle
# primitive.
#
# Any DeFi or automation contract that needs to act on "does live
# structured data currently satisfy this condition" - trigger a rebalance
# when a rate crosses a threshold, unlock a payout when a protocol's TVL
# exceeds a level - can gate on a StructuredDataOracle Feed reaching
# CONDITION_MET, instead of writing its own JSON-fetch-and-extract logic.
# This example contains none of StructuredDataOracle's fetch/extraction
# machinery, it only reads a verdict StructuredDataOracle already reached.
# ---------------------------------------------------------------------------


@gl.contract_interface
class IStructuredDataOracle:
    class View:
        def get_feed(self, feed_id: u256) -> dict: ...

    class Write:
        pass


class ThresholdGatedAction(gl.Contract):
    oracle_address: Address
    triggered: TreeMap[u256, bool]

    def __init__(self, oracle_address: str):
        addr = oracle_address if isinstance(oracle_address, Address) else Address(oracle_address)
        self.oracle_address = addr

    @gl.public.write
    def trigger_if_condition_met(self, feed_id: u256) -> None:
        if feed_id in self.triggered:
            raise gl.vm.UserError("already triggered for this feed")

        feed = IStructuredDataOracle(self.oracle_address).view().get_feed(feed_id)

        if feed["state"] != "CONDITION_MET":
            raise gl.vm.UserError("feed condition is not currently met")

        self.triggered[feed_id] = True

    @gl.public.view
    def was_triggered(self, feed_id: u256) -> bool:
        return self.triggered.get(feed_id, False)
