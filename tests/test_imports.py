import importlib

import pytest

SUBPACKAGES = [
    "data", "reference", "bonds", "funding", "curve", "vol", "model", "risk", "history", "report", "cli",
    "data.registry",
]


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackage_imports(name):
    importlib.import_module(f"ctd.{name}")
