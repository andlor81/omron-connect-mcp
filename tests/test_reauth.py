"""Re-login when OMRON rejects an expired session (401/403)."""

import pytest

from omron_connect_mcp import client as c


class _Resp:
    def __init__(self, status):
        self.status_code = status


class _HTTPError(Exception):
    def __init__(self, status):
        super().__init__(f"Client error '{status}'")
        self.response = _Resp(status)


class _FakeOmron:
    def __init__(self, fail_with=None):
        self.fail_with = fail_with

    def get_registered_devices(self, _):
        if self.fail_with:
            raise _HTTPError(self.fail_with)
        return []


def _client_with(sessions):
    """An OmronConnectClient whose connect() hands out the given sessions in order."""
    obj = c.OmronConnectClient(c.Credentials("a@b.c", "JP", "pw"))
    calls = {"connect": 0}

    def fake_connect():
        obj._client = sessions[calls["connect"]]
        calls["connect"] += 1

    obj.connect = fake_connect
    return obj, calls


@pytest.mark.parametrize("status", [401, 403])
def test_expired_session_logs_in_again_and_retries(status):
    obj, calls = _client_with([_FakeOmron(fail_with=status), _FakeOmron()])
    assert obj.devices() == []
    assert calls["connect"] == 2


def test_second_rejection_is_raised_not_looped():
    obj, calls = _client_with([_FakeOmron(fail_with=403), _FakeOmron(fail_with=403)])
    with pytest.raises(_HTTPError):
        obj.devices()
    assert calls["connect"] == 2


def test_other_errors_are_not_retried():
    obj, calls = _client_with([_FakeOmron(fail_with=500), _FakeOmron()])
    with pytest.raises(_HTTPError):
        obj.devices()
    assert calls["connect"] == 1


def test_plain_exception_is_not_an_auth_error():
    assert not c._is_auth_error(ValueError("x"))
