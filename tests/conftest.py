"""Test-wide guarantees.

The suite must never depend on Overpass, on the IGN Geoplateforme, or on any
other host: a red build has to mean the code changed, not that a public service
was slow, rate-limited or down.  Rather than trusting that by convention, every
outbound socket connection is refused for the whole session, so a test that
reaches for the network fails loudly and immediately.
"""

from __future__ import annotations

import socket

import pytest


class NetworkAccessInTestError(RuntimeError):
    pass


@pytest.fixture(autouse=True, scope="session")
def _forbid_network() -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise NetworkAccessInTestError(
            "The offline test suite attempted a network connection. Live acquisition "
            "belongs to scripts/phase1b_live_oisans.py, and tests must run from the "
            "frozen fixtures under tests/fixtures/."
        )

    original_connect = socket.socket.connect
    original_create = socket.create_connection
    socket.socket.connect = refuse  # type: ignore[method-assign]
    socket.create_connection = refuse  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.create_connection = original_create  # type: ignore[assignment]
