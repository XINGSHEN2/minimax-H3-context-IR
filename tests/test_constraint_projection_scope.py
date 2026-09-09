from backend.context_ir import _projected_constraint_text


def test_projection_preserves_shot_target():
    payload = {"intent": {"directives": [{
        "target": "Shot 1 frame composition", "operation": "preserve",
        "scope": ["tiny protagonist lower right"],
    }]}}
    result = _projected_constraint_text(payload)
    assert "For Shot 1 frame composition: tiny protagonist lower right" in result
    assert "Global constraints" not in result


def test_matching_content_in_other_shot_does_not_erase_scoped_requirement():
    payload = {"intent": {"directives": [{
        "target": "Shot 1 audio", "operation": "exclude",
        "scope": ["music"],
    }]}}
    result = _projected_constraint_text(payload, "Shot 2 has music")
    assert "For Shot 1 audio: music" in result


def test_target_is_written_once_without_losing_attributes():
    payload = {"intent": {"directives": [{
        "target": "Shot 1 protagonist", "operation": "preserve",
        "scope": ["dark wavy hair", "long coat", "black boots"],
    }]}}
    result = _projected_constraint_text(payload)
    assert result.count("For Shot 1 protagonist:") == 1
    for attribute in payload["intent"]["directives"][0]["scope"]:
        assert attribute in result
