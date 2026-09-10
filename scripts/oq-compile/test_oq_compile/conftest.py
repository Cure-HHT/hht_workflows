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


@pytest.fixture
def sample_trace_path():
    return FIXTURES / "sample-trace.json"


@pytest.fixture
def sample_graph_path():
    return FIXTURES / "sample-graph.json"
