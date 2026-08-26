import os
import sys
import atexit

import pytest


def _tolerant_unlink(path, *args, **kwargs):
    try:
        return _real_unlink(path, *args, **kwargs)
    except PermissionError:
        _leaked_files.append(path)


_leaked_files = []
_real_unlink = os.unlink

if sys.platform == "win32":
    # Same Windows fd0-unlink issue as the other submissions' conftest.
    os.unlink = _tolerant_unlink

    def _sweep_leaked_files():
        for path in _leaked_files:
            try:
                os.remove(path)
            except OSError:
                pass

    atexit.register(_sweep_leaked_files)


def _addr_bytes(addr) -> bytes:
    if isinstance(addr, bytes):
        return addr
    return bytes(addr.as_bytes)


def install_call_contract_hook(vm, responses_by_method: dict) -> None:
    """
    Install a hook answering CallContract (the request shape behind
    @gl.contract_interface view calls) with a fixed calldata-encoded
    response per method name. Used by the worked example's tests to mock
    StructuredDataOracle.get_feed() without needing a second real
    deployment.
    """
    from genlayer.py import calldata
    from genlayer.py.public_abi import ResultCode

    def _hook(vm, request):
        if not isinstance(request, dict) or "CallContract" not in request:
            return None
        call = request["CallContract"]
        method = call["calldata"]["method"]
        if method not in responses_by_method:
            raise AssertionError(f"no mocked response for CallContract method {method!r}")
        payload = responses_by_method[method]
        return bytes([ResultCode.RETURN]) + calldata.encode(payload)

    vm._gl_call_hook = _hook


def warp_to(direct_vm, iso: str) -> None:
    """Advance the VM clock. gltest's direct VMContext.warp() patches
    datetime.datetime.now() dynamically and re-reads it fresh on every
    call, so a single vm.warp() call is sufficient here."""
    direct_vm.warp(iso)


@pytest.fixture(autouse=True)
def _reset_known_contract():
    """One gl.Contract subclass is tracked globally by the SDK per
    process; reset it after every test so file order never matters."""
    yield
    try:
        import genlayer.gl.genvm_contracts as gc

        gc.__known_contract__ = None
    except ImportError:
        pass
