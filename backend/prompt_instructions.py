"""Single-call content planning and H3 writing, opt-in experimental capability."""
from __future__ import annotations

import json
from typing import Any, Callable, Mapping

COMPACT_WRITING_INSTRUCTIONS = """Write a complete MiniMax H3 Prompt using the supplied user request and media
evidence. Follow the official H3 writing guide and shot-planning skill. Return
one JSON object with content_plan, h3_prompt (string), and uncertainties (array).
content_plan is a concise production record, not reasoning prose. First record
creative_brief: user_locked (requirements with their temporal or attribute scope),
reference_anchors (asset_id and distinguishing visible features relevant to its
assigned role), and open_design (unspecified content and the chosen development).
These are brief decisions, not a chain of thought or a new validation gate.
Then record task_mode
(generate, reference_transfer, edit, or continuation), must_keep
(short list of user requirements and identifying details), bindings (asset_id,
role, retained_attributes, optional_inherited_attributes, excluded_attributes, exclusion_reasons), developments (id, visible_change, outcome), and shots (development_ids, start_seconds, end_seconds, start_state,
action, end_state, sound_cues). Keep it small, then realize the same content in
h3_prompt. This single call produces both; do not introduce an audit stage.
Allocate time to the primary action and communication goal before secondary
reaction holds, decorative transitions or end cards. In incomplete generation,
an opening followed by a requested cut needs subsequent content, not merely a
cut to black at the end. Use purposeful performance to reveal clothing, product,
space or emotion; changing shot size around an unchanged pose is not inherently
progression. Stillness is valid when it serves the requested goal, not as a default
substitute for designing action. No universal walk, shot count or duration ratio.
For a scene reference, carry its supported spatial, lighting and environmental
anchors into visible shot descriptions, not just a generic location name or a
fully_preserved label. For a style-only reference, do not transfer its incidental
scene objects. Source-image poses describe observations, not target motion locks.
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
A primary reference role is not an exclusive whitelist. Distinguish required
retention, optional inheritance and explicit exclusion. An attribute outside
required retention does not automatically belong in excluded_attributes. Give
each exclusion a reason: an explicit user restriction, an authoritative replacement,
a concrete source conflict, or non-scene presentation such as a contact-sheet border.
For an unspecified target scene, prefer a coherent, evidenced setting accompanying
the target subject when it suits the requested action and conflicts with no instruction.
Record this as optional inheritance and a design choice, not as a user must_keep.
Do not replace a usable source setting with a generic wall or plaza merely because
the images primarily identify a person. If candidate settings conflict, choose a
supported fit and state the uncertainty; do not blend incompatible locations.
Explicit new scenes, 'identity only', 'do not use the original background', and
style-only reference scopes override this default. Never copy sheet borders,
multi-view layouts or a plain identity-sheet backdrop as a literal scene by default.
For person-image plus motion-video transfer, the motion source does not displace
a usable target-image setting. Creative freedom develops the requested action
within that setting before inventing a replacement world, unless the request calls for one.
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
For incomplete generation requests, actively complete unspecified actions,
coverage, pacing and staging in service of the user's goal; no separate request
to expand is needed. More detailed requests leave less unspecified space, while
strict replication locks the referenced dimensions, not every unrelated choice.
Distinguish designed target content from observed source facts. Do not invent
factual product claims or change the requested story's outcome. Keep later shot start states
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
