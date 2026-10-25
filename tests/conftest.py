"""Shared pytest fixtures."""

import pytest

from ctd.data.store import RawStore


@pytest.fixture(autouse=True)
def isolated_downloads(tmp_path, monkeypatch):
    """Point ``ctd ingest``'s Downloads folder at an empty temp folder: the real one may hold bookmarklet
    downloads, which ingest would move into the test's temporary inbox."""
    monkeypatch.setenv("CTD_DOWNLOADS", str(tmp_path / "downloads"))


@pytest.fixture
def store(tmp_path):
    return RawStore(tmp_path / "data")
