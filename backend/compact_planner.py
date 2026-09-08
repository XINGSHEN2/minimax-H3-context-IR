"""Experimental shorter planning instructions; never selected by the public API."""
import json

from backend.agent import _compact_final_editor_source, schema_template


def build_compact_planning_prompt(source):
    return """Compile the user's request and supplied media evidence into Context-IR.
Use the supplied H3 Prompt Writing and Shot Planning Skills. You are text-only;
do not call tools or claim to inspect raw media. Return one JSON object only.

Decide the target film before filling the schema:
1. Preserve explicit user content, timing, shot instructions and prohibitions.
   Distinguish a complete storyboard from an opening that the user permits you
   to complete. In the latter case, keep the specified opening and make the
   remaining duration serve a modest continuation or resolution using existing
   subjects, not a padded repetition. A still, short or single-shot result is
   appropriate when the user's actual goal calls for it, not because the schema
   shows one example shot. A cut must describe a visible editorial boundary;
   merely writing 'cut' after the final frame does not create a second shot.
2. Decide what the viewer must see, who/what supplies it, and the new information
   each shot contributes. Allocate time by action and requested pace. Keep related
   small actions together when readable; preserve all required physical steps.
   Use one motivated camera behavior per shot; do not repeat moves for decoration.
3. Keep facts separate from permission. Each asset supplies only user-authorized
   dimensions. Mood references do not automatically supply people, products or
   literal text. Exact-frame/edit-base preservation does retain relevant source
   content. Reliable OCR proves spelling, not permission. For authorized but
   uncertain text, preserve its source design and location without guessing.
4. Form one stable appearance profile for each real subject. Combine supported
   complementary views, keeping distinguishing components, clothing and visible
   material qualities. Uncertain orientation does not erase observed shape;
   unseen is not absent; leather-like is not a confirmed material composition.
   Carry the same qualified facts into bindings and constraints. Do not create
   a new subject per view or invent identity links across unrelated references.
5. Infer prominence from the user, never asset count or registry fields. A joint
   goal remains joint. primary_subject_id is one technical anchor, not a mandate
   to demote everyone else. Show important details through appropriate framing,
   not by repeating that they 'must be preserved' without showing where.
6. Preserve continuity of hands, ownership, clothing, location, direction and
   motion phase. Completion permits a minimal causal bridge, not a new product,
   person, brand claim or unrelated plot. Still images supply no observed motion;
   authorized target motion is completion, not source evidence.

Compile these decisions consistently into the required shape:
- semantic_plan is the compact decision record; subjects own stable appearance;
  bindings own source/attribute authority; timeline owns actions and camera;
  policies own permissions. Do not independently invent a second plan in each.
- Keep input asset IDs, types, reference labels and directive IDs unchanged.
  Bind each source to explicit target subject IDs. Cite existing directive IDs
  for source inheritance; global instructions need no synthetic asset binding.
- Every Picture needs an explainable keyframe_role. Frame anchors map to shots;
  appearance/style references are not motion sources. Without a performance
  Video, performance_plan has empty source_asset_ids and beats, and all beat_refs
  are empty. Never manufacture video events from stills.
- For a performance Video, preserve actual observed event IDs and their order,
  applying user replacements to target actions. The compiler maps source timing.
  Motion-only transfer does not grant video camera/edit authority; use a continuous
  shot unless other instructions authorize cuts. Never fill missing evidence by
  inventing a perfectly measured reference timeline.
- One reference_relationship per asset; choose official task types and retention
  values matching its actual role. Style scope does not spread to a separately
  preserved end card. Copy exact user text in its original language; all other
  semantic descriptions are English.
- Policies follow user specifications, edit-base preservation, authorized evidence,
  then conservative completion. A planner preference is not an explicit user lock.
  A rule for one shot must not become a whole-video prohibition. Fill only useful
  constraints/events; empty arrays are preferable to invented examples.
- Timeline starts at zero, has no gaps or overlaps, and ends at target duration.
  Each shot has stable subject_refs, an observable change/end state and physical
  continuity. Reserve useful time for the specified ending before filling earlier
  shots. Do not invent exact timings claimed to come from an image.
- If audio is disabled, audio_plan is empty. If enabled, design restrained
  scene-appropriate sound; do not claim to hear unanalyzed source audio or invent
  speech. Audio never determines the visual task's subject priority.
- Record assumptions/uncertainties in intent. Do not return task, assets,
  perception, runtime or copied input intent fields: the compiler injects them.
  Do not author binding_ids, binding_refs or primary_binding_ids: they are derived.

The shape below illustrates fields and enums, not a desired shot count, duration
allocation, subject hierarchy, default policy or factual content. Replace all
examples with your decisions and omit irrelevant example entries.
Required shape:
""" + json.dumps(schema_template(source), ensure_ascii=False) + "\nInput:\n" + json.dumps(
        _compact_final_editor_source(source), ensure_ascii=False)
