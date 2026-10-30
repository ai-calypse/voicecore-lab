import pytest
from fixtures import load_manifest


@pytest.fixture(scope="session")
def manifest():
    return load_manifest()
