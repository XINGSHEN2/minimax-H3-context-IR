"""Production v19 serialization after intent resolution and perception."""
import copy
import json
import time


def finish_single_call(source, output_dir, reasoning, timings, started, progress=None):
    from backend.agent import _compact_final_editor_source, invoke_reasoning_json, CORE_SKILLS
    from backend.single_call_compiler import RULES, COMPILER_REVISION, prepare_writer_evidence, transport_issues
    from backend.compact_writer import build_compact_writing_prompt
    from backend.context_ir import build_h3_request

    def save(name, value):
        (output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    evidence = prepare_writer_evidence(_compact_final_editor_source(source))
    save('evidence_input.json', evidence)
    instruction = RULES + '\n' + build_compact_writing_prompt(evidence)
    (output_dir / 'compiler_instructions.txt').write_text(instruction, encoding='utf-8')
    tick = time.perf_counter()
    result = invoke_reasoning_json(instruction, reasoning, output_dir / 'writer_1.log', list(CORE_SKILLS))
    timings['stages_seconds']['single_call_compile'] = round(time.perf_counter() - tick, 3)
    errors, warnings = transport_issues(result, evidence)
    save('compilation_result.json', result)
    audit = {'schema_version': 'h3_prompt_contract.v1', 'passed': not errors,
             'errors': errors, 'warnings': warnings, 'semantic_quality_verified': False,
             'compiler_revision': COMPILER_REVISION, 'llm_calls': 1}
    save('h3_prompt_audit.json', audit)
    timings.update(compiler_revision=COMPILER_REVISION, prompt_llm_calls=1,
                   total_seconds=round(time.perf_counter() - started, 3))
    save('stage_timings.json', timings)
    save('result_status.json', {'status': 'needs_review' if errors else 'ready_for_review', 'llm_calls': 1})
    if errors:
        # Retain diagnostic artifacts; never silently invoke another writer or
        # issue a generation request for invalid output.
        raise ValueError('v19 transport validation failed: ' + json.dumps(errors, ensure_ascii=False))
    plan = result['content_plan']
    save('content_plan.json', plan)
    # Explicitly a lightweight record, NOT a fabricated canonical Context-IR.
    record = {'schema_version': 'h3_compilation.light.v1', 'compiler_revision': COMPILER_REVISION,
              'task': copy.deepcopy(source['task']), 'assets': copy.deepcopy(source['assets']),
              'content_plan': plan, 'uncertainties': result.get('uncertainties', []),
              'perception': source.get('perception')}
    save('context_ir.json', record)
    save('llm_optimization.json', {'enabled': False, 'reason': 'v19 single-call writer; no final director',
                                  'compiler_revision': COMPILER_REVISION, 'llm_calls': 1})
    prompt_path = output_dir / 'h3_prompt.txt'
    prompt_path.write_text(result['h3_prompt'], encoding='utf-8')
    request_source = copy.deepcopy(source)
    request_source['asset_bindings'] = []
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
