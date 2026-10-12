import pytest

from adaptive_ss import data_gen


@pytest.fixture(scope="session")
def ds():
    return data_gen.generate()
