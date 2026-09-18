"""The v20 production compiler and deterministic output checks."""
import copy
import json
import math
import os
import re
import time

COMPILER_REVISION='singlecall.v40.1.outline_authority'
REQUIRED_H3_SECTIONS = (
    'subject_definitions', 'summary', 'retention_analysis',
    'detailed_description', 'overall_soundscape', 'non_diegetic_music',
)
def configured_h3_text_max_chars():
    """Only report a deployment limit when explicitly configured."""
    value = os.environ.get('CONTEXT_IR_H3_TEXT_MAX_CHARS', '').strip()
    if not value:
        return None
    limit = int(value)
    if limit <= 0:
        raise ValueError('CONTEXT_IR_H3_TEXT_MAX_CHARS must be positive')
    return limit


def transport_issues(result,evidence):
    errors=[];warnings=[]
    if not isinstance(result,dict):return ['Response must be a JSON object'],[]
    prompt=result.get('h3_prompt')
    if not isinstance(prompt,str) or not prompt.strip():errors.append('h3_prompt must be nonempty')
    elif (limit := configured_h3_text_max_chars()) is not None and len(prompt) > limit:
        warnings.append(f'h3_prompt has {len(prompt)} characters including whitespace; configured H3 text limit is {limit}. Preserve requirements; do not truncate automatically.')
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
        section_matches = {
            name: list(re.finditer(r'(?mi)^\s*' + re.escape(name) + r'\s*:', prompt))
            for name in REQUIRED_H3_SECTIONS
        }
        missing = [name for name, matches in section_matches.items() if not matches]
        duplicate = [name for name, matches in section_matches.items() if len(matches) > 1]
        if missing:
            errors.append('h3_prompt missing required sections: ' + ', '.join(missing))
        if duplicate:
            errors.append('h3_prompt has duplicate required sections: ' + ', '.join(duplicate))
        if not missing and not duplicate:
            ordered = [section_matches[name][0] for name in REQUIRED_H3_SECTIONS]
            if [match.start() for match in ordered] != sorted(match.start() for match in ordered):
                errors.append('h3_prompt required sections must appear in official order')
            else:
                for index, name in enumerate(REQUIRED_H3_SECTIONS):
                    start = ordered[index].end()
                    end = ordered[index + 1].start() if index + 1 < len(ordered) else len(prompt)
                    if not prompt[start:end].strip():
                        errors.append('h3_prompt required section is empty: ' + name)
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


def compile_prompt(source, output_dir, reasoning, timings, started, progress=None):
    from backend.agent import invoke_reasoning_json, CORE_SKILLS
    from backend.evidence import build_writer_evidence
    from backend.prompt_instructions import build_compact_writing_prompt
    from backend.contracts import build_h3_request

    def save(name, value):
        (output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    evidence = prepare_writer_evidence(build_writer_evidence(source))
    save('evidence_input.json', evidence)
    instruction = build_compact_writing_prompt(evidence)
    (output_dir / 'compiler_instructions.txt').write_text(instruction, encoding='utf-8')
    tick = time.perf_counter()
    result = invoke_reasoning_json(instruction, reasoning, output_dir / 'writer_1.log', list(CORE_SKILLS))
    timings['stages_seconds']['single_call_compile'] = round(time.perf_counter() - tick, 3)
    if progress:
        progress('validation')
    errors, warnings = transport_issues(result, evidence)
    save('compilation_result.json', result)
    audit = {'schema_version': 'h3_prompt_contract.v1', 'passed': not errors,
             'errors': errors, 'warnings': warnings, 'semantic_quality_verified': False,
             'compiler_revision': COMPILER_REVISION, 'llm_calls': 1,
             'h3_prompt_chars': len(result.get('h3_prompt', '')) if isinstance(result.get('h3_prompt'), str) else None,
             'h3_v2_endpoint_max_chars': configured_h3_text_max_chars()}
    save('h3_prompt_audit.json', audit)
    timings.update(compiler_revision=COMPILER_REVISION, prompt_llm_calls=1,
                   total_seconds=round(time.perf_counter() - started, 3))
    save('stage_timings.json', timings)
    save('result_status.json', {'status': 'needs_review' if errors else 'ready_for_review', 'llm_calls': 1})
    if errors:
        # Retain diagnostic artifacts; never silently invoke another writer or
        # issue a generation request for invalid output.
        raise ValueError('v20 transport validation failed: ' + json.dumps(errors, ensure_ascii=False))
    plan = result['content_plan']
    save('content_plan.json', plan)
    save('story_outline.json', plan.get('developments', []))
    # Explicitly a lightweight record, NOT a fabricated canonical Context-IR.
    record = {'schema_version': 'h3_compilation.light.v1', 'compiler_revision': COMPILER_REVISION,
              'task': copy.deepcopy(source['task']), 'assets': copy.deepcopy(source['assets']),
              'content_plan': plan, 'uncertainties': result.get('uncertainties', []),
              'perception': source.get('perception')}
    save('context_ir.json', record)
    prompt_path = output_dir / 'h3_prompt.txt'
    prompt_path.write_text(result['h3_prompt'], encoding='utf-8')
    request_source = copy.deepcopy(source)
    if source['task']['type'].lower() in {'i2va', 'fl2va', 'l2va'}:
        # Frame position is an input contract, never inferred from writer prose.
        for asset in source['assets']:
            frame = asset.get('frame_index')
            if frame not in (0, -1):
                raise ValueError('Keyframe tasks require explicit asset.frame_index (0 or -1)')
    request = build_h3_request(request_source, str(prompt_path), str(output_dir / 'h3_outputs'))
    save('h3_request.json', request)
    if progress:
        progress('prompt')
    return 0
