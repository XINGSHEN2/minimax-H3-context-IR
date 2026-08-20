# H3 rendering and audit rules

Context-IR decides what the request means, which source controls each attribute,
and which user requirements are immutable. The H3 renderer only serializes that
validated decision into the official six-section full-reference brief.

The implementation follows these general rules:

- A visible recurring entity has one canonical `subjects[]` profile.
- An ordinary appearance image is cited inside its `<Subject N>` definition.
  A standalone `<Picture N>` definition is reserved for a first frame, last
  frame, keyframe, or composition anchor.
- A structural video binding controls only its declared motion, camera, rhythm,
  or style dimensions and is explicitly not an appearance source.
- Every user directive remains unchanged in `intent.directives`. A compiled
  binding must use the directive's asset, priority, and complete scope.
- Every shot has one primary visible change, an observable end state, and
  optional structured state transitions for continuity-critical properties.
- Static shots explicitly reject camera drift and reframing. Moving shots name
  one primary camera move.
- Analysis-only repetition stays in Context-IR. The final H3 brief keeps the six
  required sections while avoiding repeated action, preservation, and state
  prose.

The renderer rules were informed by MiniMax's public prompt-writing guidance and
the community H3 prompt-enhancer notes at
<https://gist.github.com/Naxdy/43b7422a1e4a79fb8b0489c6c39eaace>.
No third-party system prompt is copied into this repository.
