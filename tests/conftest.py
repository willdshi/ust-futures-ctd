"""Shared pytest fixtures."""

import pytest

from ctd.data.store import RawStore


@pytest.fixture
def store(tmp_path):
    return RawStore(tmp_path / "data")
