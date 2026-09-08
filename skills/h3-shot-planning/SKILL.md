---
name: h3-shot-planning
description: Plan controllable camera movement and editorial cuts for short MiniMax H3 videos. Use when converting user intent and media evidence into shot functions, framing, camera paths, transitions, timing, and continuity-safe H3 timelines.
---

# H3 Shot Planning

Turn each short-video timeline into a small set of purposeful, executable shots. A shot is an editorial decision about what the audience learns, not a bundle of cinematic adjectives.

## Authority and mode

Choose one mode before planning:

- `strict`: the user presents the supplied storyboard as complete and explicitly specifies its shots, timing, movement, or transitions. Preserve them and make only the smallest technical or continuity repair.
- `reference`: the user asks to reproduce a reference video's shot structure, camera, edit rhythm, or motion. Transfer only the authorized dimensions and keep unrelated identity, product, scene, text, lighting, and audio isolated.
- `adaptive`: the request is incomplete. Add the minimum coverage needed to make the requested outcome legible and complete.

An explicitly described shot is not proof that the whole storyboard is complete. If the user marks the Prompt as incomplete, asks the system to supplement it, or otherwise grants timeline completion authority, use `adaptive` while treating every supplied shot as a locked beat. Keep its order, purpose, specified framing, movement, text, sound, and transition, then add only distinct continuation or resolution beats using existing authorized subjects and scenes.

Apply this priority order:

```text
explicit user requirement or prohibition
> direct edit-base preservation
> authorized reference evidence
> continuity and physical feasibility
> conservative planning completion
```

Never let this Skill rewrite an explicit user storyboard, change an authoritative subject or product, invent a brand claim, or turn an optional cinematic idea into a hard requirement.

## Give every shot one job

Assign each shot one unique editorial function:

- `orient`: establish the subject, product, place, or spatial relationship;
- `introduce`: make a new subject or product clearly identifiable;
- `reveal`: expose new information through action, framing, focus, or movement;
- `demonstrate`: show a product operation, transformation, or causal action;
- `isolate`: privilege a decisive face, hand, texture, label, or product detail;
- `compare`: make a before/after or two-subject relation readable;
- `transition`: carry an authorized action, direction, shape, or occlusion across a boundary;
- `resolve`: show the completed state or consequence;
- `end_card`: hold only an explicitly requested or source-authoritative final brand frame.

State the audience gain for the shot: the new information visible by its end. If two adjacent shots have the same function and audience gain, merge them unless the user explicitly requires both.

Do not confuse shot economy with slow pacing. When the user explicitly asks for rapid hard cuts, trailer pacing, montage, or an equivalent edit rhythm, preserve that cadence while giving each short shot a different audience gain. For example, `orient the bridge -> show the interior impact -> reveal the exterior warp event -> resolve on the title/final state` is four distinct beats, not repetition.

Do not create separate shots merely for a flash, blur, refocus, whip, smoke burst, title hold, or other transition effect. Attach the transition to the outgoing or incoming content shot. A cut is justified only when it introduces a meaningful change in subject, viewpoint, scale, space, time, action state, comparison, or product information.

## Build one controllable shot

Describe each shot with these five dimensions, omitting decorative detail that does not affect execution:

1. **Subject** — the stable referenced entity or entities visible in the shot.
2. **Subject motion** — one primary visible action or state change.
3. **Scene** — only the spatial anchors required for action, continuity, or reference fidelity.
4. **Spatial framing** — shot size, subject placement, visible surfaces/body landmarks, and required negative space.
5. **Camera** — static behavior or one motivated primary movement.

Choose between a locked and moving camera from the shot's audience gain. Use a locked camera when stillness improves a title hold, inspection, tension, comparison, or final state. Use a motivated move when it reveals scale, spatial relationship, material response, subject travel, or new information that a fixed frame would communicate less clearly. Never add movement solely because the requested tone is “cinematic”, “premium”, or “commercial”.

Do not make every shot static merely to maximize controllability. In a multi-shot sequence with an explicitly kinetic, fast-cut, action, trailer, or fashion rhythm, normally include at least one motivated camera or subject movement unless the user, edit base, or reference requires locked coverage. Conversely, do not repeat the same push-in, orbit, or handheld behavior in every shot; vary behavior only when the distinct shot functions justify it.

For a moving shot, specify all of the following in one compact sentence:

- start framing;
- action or information cue that motivates the move;
- geometric path such as push, pull, pan, tilt, track, arc, crane, handheld follow, zoom, or rack focus;
- restrained speed and amplitude;
- end framing;
- the new information revealed.

Do not combine incompatible instructions such as “fixed camera” with a push-in, or several simultaneous moves without an explicit sequence and cue. A rack focus changes focus, not camera position; a zoom changes field of view without parallax; a push or track changes camera position.

## Plan cuts and transitions

At every boundary, record the cut reason and continuity anchor. Prefer one of:

- `new_information`: the next shot reveals a materially different fact or detail;
- `action_match`: the same action continues across the cut;
- `state_change`: the cut lands after a visible attachment, removal, activation, hand-off, transformation, or completion;
- `viewpoint_change`: scale or angle changes enough to improve understanding;
- `reference_match`: an authorized reference structure requires this boundary;
- `user_locked`: the user explicitly specified this boundary.

Use hard cuts by default. Add dissolves, wipes, whip transitions, flashes, or occlusion transitions only when the user requests them, the reference visibly supplies them, or they solve a necessary time/place change. Express an effect once at its actual boundary; keep exposure, focus, and framing stable outside it.

Preserve screen direction, subject side, gaze, named hand, prop ownership, product state, wardrobe, scene geography, and motion phase through the boundary. For match-on-action, the outgoing end state and incoming start state must describe the same physical moment. Do not hide a required attach, detach, wear, remove, start, stop, or hand-off inside an unexplained cut.

## Timing and shot budget

Use the fewest shots that communicate both the requested content and the requested pace. For a 4–15 second output, one to four content shots is normally controllable. A user-authorized fast-cut montage may use roughly three to six short shots when each contributes different information; exceed that only when the user or an authorized reference clearly requires denser coverage. This is a heuristic, not a fixed limit.

- Reserve enough time for the primary physical action to become readable.
- Give a product detail or final state a useful hold instead of repeating it in several similar shots.
- When N supplied keyframes define N successive content states and no extra beat is requested, use N content shots; transitions do not add content shots.
- Timeline coverage must start at 0, contain no gaps or overlaps, and end at the requested duration.
- If duration is insufficient, keep user-locked beats and merge or remove only planner-added secondary coverage.
- When an incomplete Prompt supplies only an opening shot and explicitly permits supplementation, do not automatically stretch that opening across the full duration. Preserve it as the first locked beat, then add the smallest physically and narratively plausible consequence or resolution with the same authorized entities.

## Repetition control

State global style, stable lighting, atmosphere, persistent overlays, and unchanged continuity once outside per-shot events. Repeat a detail in a later shot only when it changes, prevents a known continuity failure, or is required for that shot's framing.

Merge adjacent beats that repeat any of the following without new information:

- the same pose, walk, turn, expression, or product hold;
- the same product angle or unchanged close-up;
- the same push-in, orbit, or macro drift;
- the same flash, fire, smoke, sparkle, or lighting sweep;
- the same title or end-card hold.

## Output contract inside Context-IR

Record the mode and compact editorial decisions in `semantic_plan`:

```json
{
  "shot_planning_mode": "strict|reference|adaptive",
  "shot_functions": [
    {
      "shot_id": "01",
      "purpose": "introduce_product",
      "audience_gain": "the product silhouette and defining material become readable",
      "cut_reason": "new_information|action_match|state_change|viewpoint_change|reference_match|user_locked|none"
    }
  ]
}
```

Express the executable result in the existing Context-IR timeline fields. Each shot must have exactly one `primary_change`, one visible `observable_end_state`, compact subject and scene action, one camera instruction, an optional boundary transition, and explicit continuity-critical `state_changes`.

## Final check

Before returning a candidate, verify:

- each shot has a distinct function and audience gain;
- every cut has a valid reason and continuity anchor;
- user-locked shot order, timing, movement, and prohibitions are unchanged;
- reference-derived camera or edit behavior stays within its authorized scope;
- static and moving-camera instructions do not conflict;
- transition effects are not standalone or repeated;
- the primary subject or product receives the clearest framing and sufficient time;
- the final state follows physically from the prior state;
- the plan is shorter when two shots would communicate the same information.

The principles are adapted for H3 from common cinematic shot-direction, storyboard, editing, and continuity practices in the MIT-licensed `calesthio/generative-media-skills` project. This Skill intentionally omits production-management and provider-execution machinery that does not belong in Context-IR.
