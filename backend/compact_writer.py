"""Single-call content planning and H3 writing, opt-in experimental capability."""
from __future__ import annotations

import json
from typing import Any, Callable, Mapping

COMPACT_WRITING_INSTRUCTIONS = """Write a complete MiniMax H3 Prompt using the supplied user request and media
evidence. Follow the official H3 writing guide and shot-planning skill. Return
one JSON object with content_plan, h3_prompt (string), and uncertainties (array).
content_plan is a concise production record, not reasoning prose: task_mode
(generate, reference_transfer, edit, or continuation), must_keep
(short list of user requirements and identifying details), bindings (asset_id,
role, retained_attributes, excluded_attributes), and shots (start_seconds, end_seconds, start_state,
action, end_state, sound_cues). Keep it small, then realize the same content in
h3_prompt. This single call produces both; do not introduce an audit stage.
User requirements and prohibitions govern; observations establish appearance,
not permission to copy unrelated identity, scene, text, camera or audio. Treat
inferred and uncertain evidence as uncertain. Preserve original-language exact
dialogue and visible text, English elsewhere. Do not invent titles or speech.
Evidence wording matters as much as its source tag: "likely", "possibly", or
"not clearly visible" is not a confirmed fact even if tagged visible. When
observations disagree about the same attribute, preserve their supported common
appearance and reference its source; do not choose the more specific claim just
because it appears in a summary. Record only the unresolved distinction as uncertain.
When exact text must be read, keep the entire wording inside the visible frame
during its readable beat with room at the edges; scale or wrap without changing
the words. This does not override explicitly requested cropped typography or
blurred/partial entrance effects before the readable beat.
Scope each binding by the user's assigned role before choosing scene content.
An atmosphere/style-only reference supplies light, palette, texture and requested
effects, not incidental source objects, people or exact captions. Record those
exclusions in its binding and keep them out of the target unless separately
authorized. Scene and identity references retain their own distinct authority.
For an edit of an existing video, modify only the requested dimensions; do not
recreate a similar scene. Preserve the source camera, lighting, identity and
non-replaced audio. Missing audio analysis limits factual descriptions, not the
ability to preserve or reuse an authorized signal. Do not invent unheard source
sounds or forbid signal reuse merely because its analysis is unavailable.
The transport task type ref2va does not determine task_mode: replacing dialogue
inside an existing video is an edit, even when the replacement uses a reference.
For an action/expression/performance-only reference, keep the continuous action
and its observed order and pacing. Action-phase timestamps are not cut points;
do not introduce cuts, camera coverage or a new stopping/ending beat unless the
user or authorized editing evidence supports them. Distinguish performance
transfer from source editing and from camera/editing-structure transfer.
Keep the distinguishing geometry, material, color and markings of the target
product AND the identifying appearance of the primary people and clothing from
their authoritative sources; do not compress these into generic nouns. For a
multi-view board, combine complementary observations of the same supported
subject across front, side and back views, rather than taking only the first
entity summary. Preserve relevant hair arrangement, garment neckline/fit/length,
surface pattern and footwear in one concise subject definition when evidenced.
Put those defining details in content_plan.must_keep and actually express them
in h3_prompt; a correct plan with missing prompt details is not completion.
Do not combine different people or products merely because they share a sheet.
Visible proximity in a still does not establish a mechanical connection or an
operating mechanism. Describe unspecified operation without inventing its location.
Choose only the shots needed to fulfill the request. Keep image anchors ordered,
actions continuous, and reference roles isolated. Preserve source typography by
reference if transcription is uncertain. State stable facts once, then describe
each shot's action, camera, ending state and synchronized sound naturally.
Supplementing missing details permits useful coverage and restrained performance,
not an unrequested irreversible plot outcome. Keep later shot start states
consistent with the preceding end state: a subject already at a destination
cannot approach it again without an explicit return. A close-up only describes
features visible in its framing. Do not sacrifice these checks to shot count.
When audio is enabled, design restrained ambience, relevant action or editorial
sounds and suitable music within user permissions. Never claim to have heard an
unanalysed source. Keep source-copy restrictions and silence. All audio must end
within the requested duration. Give every source its official label, but a source
used only for appearance need not have a redundant standalone definition.
Use one consistent ending cue for each audio layer across the shot description
and the two sound sections; it cannot begin its release after it has ended.
Do not read files or call tools. Evidence follows:\n"""


def build_compact_writing_prompt(evidence: Mapping[str, Any]) -> str:
    """Render already-normalized evidence without removing caller constraints."""
    return COMPACT_WRITING_INSTRUCTIONS + json.dumps(
        evidence, ensure_ascii=False, separators=(",", ":")
    )


def write_compact_prompt(
    evidence: Mapping[str, Any],
    invoke: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    """One invocation; preserve authored content and return its planning record.

    This does not claim to create the legacy canonical Context-IR or perform
    semantic validation. The caller chooses providers, skills and logging.
    """
    result = invoke(build_compact_writing_prompt(evidence))
    if not isinstance(result, dict):
        raise ValueError("compact writer must return a JSON object")
    if not isinstance(result.get("h3_prompt"), str) or not result["h3_prompt"].strip():
        raise ValueError("compact writer requires a nonempty h3_prompt")
    if not isinstance(result.get("content_plan"), dict):
        raise ValueError("compact writer requires a content_plan object")
    return result
