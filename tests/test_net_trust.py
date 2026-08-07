"""`app/net_trust.py`: routing HTTPS verification through the OS trust store.

The module exists because the backend's HTTPS (urllib, in this process) and the page's HTTPS
(the webview) consult different trust stores, and in a packaged build the first one is typically
empty — see the module docstring and changelog/20260806-backend-tls-system-trust.md.

What is asserted here is the module's CONTRACT rather than the verification itself: that the
patch lands, that repeating it is free, and — the important one — that a failure to apply it can
never take the application down with it. Whether the OS store then accepts a given certificate is
`truststore`'s business and needs a real machine with a real certificate; that part is listed as
unverified in the changelog.

    uv run pytest tests/test_net_trust.py
"""

from __future__ import annotations

import ssl

import pytest

from app import net_trust


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    """Clear the memo so each test observes a first call.

    `install_system_trust` is called at import of `app.main`, so by the time any test runs the
    real one has already happened; without this every test here would hit the memo and assert
    nothing. `monkeypatch` restores the previous value, which keeps the patch that the rest of
    the suite runs under intact.
    """
    monkeypatch.setattr(net_trust, "_installed", None)


def test_it_patches_the_ssl_module():
    """The point of the module: `ssl.SSLContext` is truststore's after the call."""
    assert net_trust.install_system_trust() is True
    assert ssl.SSLContext.__module__.startswith("truststore")


def test_the_patch_is_what_urllib_will_pick_up():
    """Verifies the mechanism, not just the attribute.

    `urllib.request` builds its context per request via `ssl.create_default_context()`, which is
    why patching the class reaches call sites that were written before this module existed. If
    that stopped being true the fix would silently do nothing.
    """
    net_trust.install_system_trust()
    assert type(ssl.create_default_context()).__module__.startswith("truststore")


def test_repeating_it_costs_nothing(monkeypatch):
    """Three entry points call this and none can assume it ran first, so it must be idempotent."""
    assert net_trust.install_system_trust() is True

    def _fail():
        raise AssertionError("inject_into_ssl called twice")

    import truststore

    monkeypatch.setattr(truststore, "inject_into_ssl", _fail)
    assert net_trust.install_system_trust() is True


def test_a_failure_is_reported_and_swallowed(monkeypatch, capsys):
    """The load-bearing one: a machine that cannot use the OS store must still get an app.

    Letting the exception out would turn a certificate problem into an application that does not
    start — strictly worse, since without the patch HTTPS is merely as broken as it was before.
    The warning is what makes the state diagnosable from a session log, so it is asserted too.
    """
    import truststore

    def _boom():
        raise RuntimeError("no Security.framework here")

    monkeypatch.setattr(truststore, "inject_into_ssl", _boom)

    assert net_trust.install_system_trust() is False

    err = capsys.readouterr().err
    assert "system certificate store" in err
    assert "no Security.framework here" in err


def test_a_failure_is_not_retried(monkeypatch, capsys):
    """A machine that cannot inject would otherwise print the same warning on every call."""
    import truststore

    monkeypatch.setattr(truststore, "inject_into_ssl", lambda: 1 / 0)
    assert net_trust.install_system_trust() is False
    capsys.readouterr()

    assert net_trust.install_system_trust() is False
    assert capsys.readouterr().err == ""
