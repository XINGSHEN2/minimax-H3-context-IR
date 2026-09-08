from pathlib import Path

from backend.agent import _perception_input_origin


def test_supplied_analysis_is_reused_without_file():
    assert _perception_input_origin({"perception": {"assets": []}}, None) == "supplied_analysis"


def test_file_route_has_precedence():
    assert _perception_input_origin({"perception": {}}, Path("analysis.json")) == "file"


def test_pipeline_does_not_claim_a_provider_cache_miss_or_hit():
    assert _perception_input_origin({}, None) == "perception_pipeline"
    assert _perception_input_origin({"perception": None}, None) == "perception_pipeline"
