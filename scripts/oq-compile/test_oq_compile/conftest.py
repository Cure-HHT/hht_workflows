from pathlib import Path

import pytest
import yaml

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_manifest_path():
    return FIXTURES / "sample-manifest.yaml"


@pytest.fixture
def sample_manifest_dict():
    return yaml.safe_load((FIXTURES / "sample-manifest.yaml").read_text())
