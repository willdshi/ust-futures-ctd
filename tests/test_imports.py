import importlib

import pytest

SUBPACKAGES = ["data", "reference", "bonds", "curve", "vol", "model", "risk", "report", "cli"]


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackage_imports(name):
    importlib.import_module(f"ctd.{name}")
