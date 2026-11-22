import sys

import pytest

from redrip import oscompat


@pytest.fixture
def frozen_linux(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(oscompat, "IS_WINDOWS", False)


def test_restores_users_library_path(frozen_linux):
    env = {"LD_LIBRARY_PATH": "/app/_internal:/opt/mine", "LD_LIBRARY_PATH_ORIG": "/opt/mine"}
    assert oscompat.restore_system_env(env) == {"LD_LIBRARY_PATH": "/opt/mine"}


def test_drops_bundle_library_path_when_user_had_none(frozen_linux):
    env = {"LD_LIBRARY_PATH": "/app/_internal", "HOME": "/home/x"}
    assert oscompat.restore_system_env(env) == {"HOME": "/home/x"}


def test_not_frozen_leaves_env_alone(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    env = {"LD_LIBRARY_PATH": "/usr/local/lib"}
    assert oscompat.restore_system_env(env) == {"LD_LIBRARY_PATH": "/usr/local/lib"}


def test_child_env_has_no_bundle_library_path(frozen_linux, monkeypatch):
    from redrip import runner
    monkeypatch.setenv("LD_LIBRARY_PATH", "/app/_internal")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    assert "LD_LIBRARY_PATH" not in runner.child_env()
