"""Opt-in one-call compiler. Does not change the public legacy IR protocol."""
import copy,json,math,re
from backend.compact_writer import build_compact_writing_prompt

COMPILER_REVISION='singlecall.v19.content_first'

RULES='''\nCompile bindings, shot states and final wording in this ONE response. The
content_plan is a short production record, not a legacy canonical Context-IR.
Use the original user_request as authority; resolved_request, directives and
completion_policy are upstream interpretations, not additional user instructions.
Even an explicit_user provenance tag requires support in the original request.
A derived creative:false is not a user prohibition on unspecified staging.
Honor actual user prohibitions and complete-storyboard/reference locks.
Before returning, reconcile the plan and Prompt for
source roles, user-required details, continuity, shot count and duration.
Each binding must use a real asset_id from the provided assets. Each shot must
contain numeric start_seconds and end_seconds; shots cover 0 to the exact target
duration without gaps. Preserve official source numbering from reference_registry.

CONTENT AUTHORITY: Preserve the user's explicit actor, action, target, sequence,
result and source-use scope in the final wording, not only in the plan. A similar
action is not an equivalent substitute. Source observations describe evidence;
they do not veto a requested target edit or authorize unrelated changes. Distinguish
target requirements from casual descriptions of source content. If requirements
conflict or critical reference evidence is missing, record the specific unresolved
point in uncertainties; do not claim it is verified or silently weaken the request.
For action/camera transfer, stay within the authorized reference events and endpoint;
do not invent a final pose or new move just to make an ending feel complete.

EDITORIAL CONSTRUCTION: Build the content progression before dividing it into shots.
In content_plan, include a short developments array before shots: each item has an
id, visible_change and outcome. These are production decisions, not reasoning prose.
A development is a meaningful action, revelation, exchange or graphic animation,
not each gesture, adjective, camera angle or effect. Preserve user-specified shots,
ordering and reference cadence; this planning must not merge away those requirements.

Then allocate shots to those developments using development_ids. Use a cut when it
reveals a new consequence, relationship, spatial fact or purposeful reaction that
the continuing view would not express as well. A returning view should continue
from the already-reached state, not replay establishment or restart an escalation.
Keep useful inserts and cross-cut cause/reaction pairs. Changing only scale, pose,
light intensity or shake is not by itself new content. Several distinct details
can remain in one shot through readable handling, camera movement or focus.

Describe a continuous graphic reveal, including fade, spacing change, sweep and
settling, as one animation unless the user or a deliberate narrative reveal calls
for separating it. Do not replay that reveal merely to bookend the clip. Black-frame
punctuation, flashes and motion blur belong to the boundary of content shots, not
standalone numbered shots, unless the user explicitly requests an independent card
or scene. Include their duration in the adjoining shot's interval so timing remains
contiguous. State which incoming content resolves a transition.

There is no target shot count. Keep necessary detail; merge duplicated functions,
not meaningful content. Fast editing can coexist with a sustained action, and
stillness or rhythmic repetition is valid when it serves the actual request.
Return the plan and its matching complete H3 Prompt in this one response, without
an editor pass or a separate review call. Planner choices are not user must_keep.

CREATIVE COMPLETION: Lock explicit
requirements and source facts, not unspecified creative choices. For an incomplete
generation request, proactively design goal-serving actions, coverage, pacing,
scene details and a coherent ending without requiring separate permission to
supplement. Short input calls for more useful design, not a longer static hold.
A supplied opening locks that beat, not the whole film. Preserve supplied beats
and develop meaningful progression in the available duration; select additions
for the user's subject, commercial focus or emotional goal, not merely to fill time.
Generated staging is a creative choice, not an observed source fact: do not invent
brand names, product capabilities, factual identity relationships or claims of
having observed it. Do not force a new subplot or an outcome that changes the
requested story. A complete locked storyboard or strictly transferred dimension
retains its prescribed sequence and endpoint; other unspecified dimensions remain
open within the request. Reference isolation limits what a source controls; it is
not permission to delete bystanders or backgrounds from an edit base.
Do not invent restrictions such
as interior-only coverage or static-only cameras when not authorized by the user,
edit base or reference role. Transitions belong at boundaries, not in extra shots.

INFORMATION PLACEMENT: Define stable identifying appearance once in the appropriate
subject definition; put shared style, lighting and persistent overlays once in
the global description. Retention entries state scope, not a second full inventory.
At a subject's first visible appearance, include only the identifying details
needed in that framing, as required by the H3 guide. Subsequent shots describe
the visible change, framing, camera, state and synchronized sound. Repeat a stable
detail only when its visibility or a continuity risk requires it. Do not shorten
by dropping a user-required detail, meaningful action, authorized scene anchor or
sound cue; shorten by removing duplicate exposition. Keep required H3 sections.
Concise wording must preserve who does what to whom, the decisive action and its
result. Delete redundant phrasing, not the content that distinguishes the request.

EVIDENCE CALIBRATION: Specificity is not proof. Never turn uncertain OCR, conflicting
attribute descriptions, or an inferred identity match into a definite claim.
Perception is fallible observation, not independent verification. Numeric model
confidence is omitted from observation payloads. A visible/exact label or an empty
uncertainty field does not establish correctness. Repetition in a summary, entity
and OCR field from the same analysis is not independent corroboration.
Cross-check user-mentioned names and text against OCR even when labelled exact.
Distinguish an explicit target-text requirement or user correction from a casual
description of a source. Follow explicit target wording and confirmed corrections.
If descriptive user wording conflicts with OCR and neither spelling is independently
verified, preserve the relevant source letterforms by reference in the H3 Prompt
instead of declaring either transcription exact; record the localized conflict in
uncertainties. Do not silently normalize unrelated labels, similar brand names,
case, or intentional source spelling. Preserve all unaffected evidence and details.
Do not report an OCR correction as visually verified when no reinspection occurred.
Explicit user text is authoritative; otherwise preserve uncertain source lettering
by reference rather than spelling a guessed transcription. Retain supported common
appearance and record only the unresolved distinction in uncertainties. Do not
merge people across images without identity evidence or user authorization. Missing
audio evidence does not authorize replacing requested singing with wordless vocals,
inventing lyrics, or denying permitted source reuse. Preserve the requested source
relationship and state the evidence limitation. Do not invent camera direction or
amplitude merely to make an unverified motion description sound more specific.
Referencing timbre, style or rhythm does not authorize copying an audio signal or
its words. Do not invent copy intervals or upgrade reference to reuse. Conversely,
retain explicitly authorized reuse without pretending absent analysis verified it.

CAUSAL AND STATE CHECK: Within this same response, reconcile both content_plan and
h3_prompt against the original request. Preserve immediate reactions and event
order; do not insert unrelated beats between a cause and its required immediate
response or force unsupported second-by-second timing. Track the few states that
matter: location, current left/right slot, named hand, prop ownership and grip,
worn/removed state and action completion. A changed grip, handoff or attachment
must have a readable bridge; otherwise keep the prior state.
Before a required action, check only its necessary physical prerequisites: a free
hand, accessible prop, released grip or completed attachment. Make any necessary
release, placement or regrip legible within the existing action where possible;
do not spawn extra shots or an inventory of every limb. Never resolve a prerequisite
by replacing the requested action with an easier but different one. Track original
identity separately from current position after a swap. Do not repeat an arrival,
return a departed object, or reset an action merely to restore source composition.
Preserve a locked edit/reference endpoint; otherwise choose an ending that serves
the user's goal and follows from the action. Keep audio-layer endings consistent
between shots and sound sections.
SHOT-BOUNDARY CONTINUITY: For a continuous action across a cut, briefly connect
the outgoing action phase to the incoming phase, retaining screen direction,
placement and the relevant camera/framing relationship. Continue the action, not
its opening pose; do not replay a step, arrival or turn at the new angle. For an
authorized time/place jump, make that discontinuity legible instead of fabricating
an action match. Keep user-required fast cuts, flashes, VHS effects and camera
changes; do not replace them with mandatory dissolves or slowed pacing. Confine
transition effects to their intended boundaries, with no unintended framing,
exposure or camera-path resets inside a shot. State only continuity-critical
details, not a repeated inventory or a mandatory new field for every boundary.

EVENT-DRIVEN SOUND: Place synchronized physical sounds in their shot, tied to a
physical trigger and stop condition; specify carryover only where needed. Footfalls
follow actual foot contacts, not music beats, and cease when walking stops. During
a close-up, carry them only if the established action continues off-screen; a
stationary pose must not inherit a walking loop. Apply the same source-state rule
to engines, handling, impacts and other action sounds. Natural decay may cross a
cut, but new impacts require new actions. Music may accent edits independently;
never invent physical contacts to satisfy its downbeats. If the user explicitly
requires choreographed synchronization, align the action and its sound together.
Keep authorized audio reuse and explicit sound design unchanged, recording a
conflict rather than silently retiming a locked source track. overall_soundscape
summarizes ambience and physical-sound character without turning local events into
continuous tracks; non_diegetic_music describes the score. Reconcile these sections
with shot-level starts, stops and silence. Do not invent exact contact timestamps
or claim frame-accurate synchronization from evidence that does not establish it.

Fix contradictions before returning, without an additional audit call or verbose
self-review. Optional planning notes are not new program validation gates.
Do not introduce an independent director/auditor. Return only the result JSON.
'''

def transport_issues(result,evidence):
    errors=[];warnings=[]
    if not isinstance(result,dict):return ['Response must be a JSON object'],[]
    prompt=result.get('h3_prompt')
    if not isinstance(prompt,str) or not prompt.strip():errors.append('h3_prompt must be nonempty')
    plan=result.get('content_plan')
    if not isinstance(plan,dict):return errors+['content_plan must be an object'],warnings
    ids={a['asset_id'] for a in evidence.get('assets',[])}
    bindings=plan.get('bindings')
    if not isinstance(bindings,list):errors.append('bindings must be an array')
    else:
        for b in bindings:
            if not isinstance(b,dict) or b.get('asset_id') not in ids:errors.append('Binding references an unknown asset_id: '+str(b.get('asset_id') if isinstance(b,dict) else b))
    shots=plan.get('shots')
    duration=float(evidence['task']['duration_seconds'])
    if not isinstance(shots,list) or not shots:errors.append('shots must be a nonempty array')
    else:
        last=0.
        for s in shots:
            try:
                a,b=s['start_seconds'],s['end_seconds']
                assert type(a) in (int,float) and type(b) in (int,float) and math.isfinite(a) and math.isfinite(b)
                assert abs(a-last)<0.002 and b>a and b<=duration+0.002
                last=b
            except (AssertionError,TypeError,KeyError):errors.append('Shot times must be numeric, contiguous, increasing and within target duration');break
        if abs(last-duration)>0.002:errors.append('Shot plan must end at exact target duration '+str(duration))
    if isinstance(prompt,str):
        for label,kind in [('Picture','image'),('Video','video')]:
            count=sum(a.get('media_type')==kind for a in evidence.get('assets',[]))
            if any(int(n)<1 or int(n)>count for n in re.findall(r'<'+label+r'\s+(\d+)>',prompt)):errors.append('Prompt references nonexistent '+label)
        if any(h not in prompt for h in ['subject_definitions','summary','retention_analysis','detailed_description','overall_soundscape','non_diegetic_music']):warnings.append('Some official section labels are absent; inspect wording, no automatic rewrite')
    return errors,warnings

def prepare_writer_evidence(evidence):
    """Drop observation self-scores, not user constraints or source evidence.

    Operates on a copy of the compact writer's assets only. Original analysis,
    source tags, uncertainty descriptions, text and non-confidence numbers stay.
    """
    def clean(value):
        if isinstance(value,dict):
            return {k:clean(v) for k,v in value.items()
                    if not (k in {'confidence','confidence_score'} and type(v) in (int,float))}
        if isinstance(value,list):return [clean(v) for v in value]
        return copy.deepcopy(value)
    prepared=copy.deepcopy(evidence)
    if 'assets' in prepared:prepared['assets']=clean(prepared['assets'])
    return prepared

def compile_once(evidence,invoke):
    evidence=prepare_writer_evidence(evidence)
    instruction=RULES+'\n'+build_compact_writing_prompt(evidence)
    result=invoke(instruction)
    errors,warnings=transport_issues(result,evidence)
    attempts=1
    if errors:
        result=invoke(instruction+'\nRepair ONLY these transport errors, keeping semantic content unchanged:\n'+json.dumps(errors)+'\nPrevious response:\n'+json.dumps(result,ensure_ascii=False))
        attempts+=1
        errors,warnings=transport_issues(result,evidence)
    return {'schema_version':'h3_compilation.light.v1',**result,'compiler_revision':COMPILER_REVISION,'transport_audit':{'errors':errors,'warnings':warnings,'semantic_quality_verified':False},'llm_calls':attempts,'status':'ready_for_review' if not errors else 'needs_review'}
