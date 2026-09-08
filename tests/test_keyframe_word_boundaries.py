import copy

import pytest

from backend.context_ir import normalize_keyframe_roles


def test_title_surface_does_not_become_face_source():
    payload = {
        "task": {"type": "ref2va"},
        "assets": [{"asset_id": "image_1", "media_type": "image"}],
        "asset_bindings": [{"asset_id": "image_1", "role": "style", "inherit": ["rust-red title surface feel"]}],
        "subjects": [{"subject_id": "subject_1", "appearance_shot_ids": ["01"]}],
        "reference_relationships": [{"asset_id": "image_1", "subject_refs": ["subject_1"]}],
        "timeline": [{"shot_id": "01"}],
    }
    normalize_keyframe_roles(payload)
    roles = {item["role"] for item in payload["keyframe_roles"]}
    assert "style_reference" in roles
    assert "appearance_source" not in roles


def test_explicit_identity_still_derives_appearance():
    payload = {
        "task": {"type": "ref2va"},
        "assets": [{"asset_id": "image_1", "media_type": "image"}],
        "asset_bindings": [{"asset_id": "image_1", "role": "identity", "inherit": ["face identity"]}],
        "subjects": [], "reference_relationships": [],
        "timeline": [{"shot_id": "01"}],
    }
    normalize_keyframe_roles(payload)
    assert any(item["role"] == "appearance_source" for item in payload["keyframe_roles"])


@pytest.mark.parametrize("description", ["indoor tonal mood", "wallpaper-like grain", "surface texture"])
def test_style_substrings_do_not_create_physical_roles(description):
    payload = {
        "task": {"type": "ref2va"},
        "assets": [{"asset_id": "image_1", "media_type": "image"}],
        "asset_bindings": [{"asset_id": "image_1", "role": "style", "inherit": [description]}],
        "subjects": [], "reference_relationships": [],
        "timeline": [{"shot_id": "01"}],
    }
    normalize_keyframe_roles(payload)
    assert {item["role"] for item in payload["keyframe_roles"]} == {"style_reference"}
    previous = copy.deepcopy(payload)
    normalize_keyframe_roles(payload)
    assert payload == previous


@pytest.mark.parametrize("binding_role, expected", [
    ("identity", "appearance_source"), ("outfit", "appearance_source"),
    ("product", "appearance_source"), ("scene", "scene_anchor"),
])
def test_explicit_roles_do_not_depend_on_english_keywords(binding_role, expected):
    payload = {
        "task": {"type": "ref2va"},
        "assets": [{"asset_id": "image_1", "media_type": "image"}],
        "asset_bindings": [{"asset_id": "image_1", "role": binding_role, "inherit": ["保留用户指定属性"]}],
        "subjects": [], "reference_relationships": [],
        "timeline": [{"shot_id": "01"}],
    }
    normalize_keyframe_roles(payload)
    assert any(item["role"] == expected for item in payload["keyframe_roles"])
