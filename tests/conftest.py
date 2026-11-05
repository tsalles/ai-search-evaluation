import socket

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--allow-live", action="store_true", help="Authorize selected paid Azure tests"
    )


@pytest.fixture(autouse=True)
def prohibit_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("live"):
        if not request.config.getoption("--allow-live"):
            pytest.fail("Paid live tests require explicit --allow-live authorization.")
        return

    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("External network access is forbidden in offline tests.")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
