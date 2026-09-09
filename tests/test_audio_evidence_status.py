import copy

import pytest

from backend.perception import sanitize_media_analysis_quality


@pytest.mark.parametrize("status", ["unsupported_by_visual_provider", "invalid_placeholder", "not_analyzed"])
def test_empty_audio_is_unanalyzed_not_a_failed_visual_observation(status):
    source = {"assets": [{"asset_id": "audio_1", "entities": [], "events": [],
                          "technical": {"media_type": "audio", "analysis_status": status},
                          "transcript": "", "uncertainties": ["audio not analyzed"]}]}
    original = copy.deepcopy(source)
    result = sanitize_media_analysis_quality(source)
    asset = result["assets"][0]
    assert asset["technical"]["analysis_status"] == "not_analyzed"
    assert asset["transcript"] == ""
    assert asset["uncertainties"] == original["assets"][0]["uncertainties"]
    assert "duration_seconds" not in asset["technical"]
    assert source == original
    assert sanitize_media_analysis_quality(result) == result


def test_empty_video_remains_invalid():
    result = sanitize_media_analysis_quality({"assets": [{
        "asset_id": "video_1", "technical": {"media_type": "video"},
    }]})
    assert result["assets"][0]["technical"]["analysis_status"] == "invalid_placeholder"


def test_actual_audio_evidence_is_not_discarded():
    result = sanitize_media_analysis_quality({"assets": [{
        "asset_id": "audio_1", "summary": "caller supplied spoken line",
        "technical": {"media_type": "audio", "analysis_status": "observed"},
    }]})
    assert result["assets"][0]["technical"]["analysis_status"] == "observed"
    assert result["assets"][0]["summary"] == "caller supplied spoken line"
