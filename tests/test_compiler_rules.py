import copy, json, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch

from backend.compiler import COMPILER_REVISION, compile_prompt, extract_shot_descriptions, prepare_writer_evidence, transport_issues

VALID_H3 = '''subject_definitions:
<Picture 1> is the reference.
summary:
A concise target video.
retention_analysis:
<Picture 1> is preserved.
detailed_description:
[Shot 1] A continuous view.
overall_soundscape:
Quiet room tone.
non_diegetic_music:
N/A'''

def invoke_compiler(evidence, invoke):
    source=copy.deepcopy(evidence)
    source['task']={'type':'ref2va','aspect_ratio':'16:9', **source['task']}
    for asset in source['assets']: asset.setdefault('uri','/tmp/reference.png')
    with tempfile.TemporaryDirectory() as directory:
        out=Path(directory)
        with patch('backend.evidence.build_writer_evidence',return_value=source), patch(
            'backend.agent.invoke_reasoning_json',side_effect=lambda prompt,*args,**kwargs:invoke(prompt)
        ):
            try: compile_prompt(source,out,{}, {'stages_seconds':{}},time.perf_counter())
            except ValueError: pass
        result=json.loads((out/'compilation_result.json').read_text())
        result.update(json.loads((out/'result_status.json').read_text()))
        result['transport_audit']=json.loads((out/'h3_prompt_audit.json').read_text())
        result['compiler_revision']=result['transport_audit']['compiler_revision']
        return result

class Tests(unittest.TestCase):
    def setUp(self):
        self.e={'task':{'duration_seconds':5},'assets':[{'asset_id':'image_1','media_type':'image'}]}
        self.r={'content_plan':{'bindings':[{'asset_id':'image_1'}],'shots':[{'start_seconds':0,'end_seconds':5}]},'h3_prompt':VALID_H3}

    def test_once_and_warning(self):
        calls=[];before=copy.deepcopy(self.e)
        result=invoke_compiler(self.e,lambda p:(calls.append(p) or copy.deepcopy(self.r)))
        self.assertEqual(len(calls),1);self.assertEqual(result['status'],'ready_for_review');self.assertEqual(self.e,before)

    def test_unknown_reference(self):
        self.r['h3_prompt']='<Video 1> invented';self.assertTrue(transport_issues(self.r,self.e)[0])

    def test_invalid_output_does_not_retry(self):
        bad=copy.deepcopy(self.r);bad['content_plan']['bindings'][0]['asset_id']='image_2';answers=iter([bad,self.r])
        self.assertEqual(invoke_compiler(self.e,lambda _:next(answers))['llm_calls'],1)

    def test_failure_not_success(self):
        self.r['content_plan']['shots'][0]['end_seconds']=6
        self.assertEqual(invoke_compiler(self.e,lambda _:self.r)['status'],'needs_review')

    def test_nan(self):
        self.r['content_plan']['shots'][0]['end_seconds']=float('nan');self.assertTrue(transport_issues(self.r,self.e)[0])

    def test_four_skill_orchestration_and_revision(self):
        calls=[];result=invoke_compiler(self.e,lambda p:(calls.append(p) or copy.deepcopy(self.r)))
        for phrase in ('H3 Outline Planning Skill','H3 Shot Planning Skill','H3 Sound Planning Skill',
                       'H3 Prompt Writing Skill','content_plan、h3_prompt、uncertainties','不输出 action_units 或 shot_merge_audit'):
            self.assertIn(phrase,calls[0])
        for domain_rule in ('其拼写与 OCR 冲突','同一现象从微弱','摄影机运动本身通常没有声音'):
            self.assertNotIn(domain_rule,calls[0])
        self.assertEqual(result['compiler_revision'],COMPILER_REVISION)
        self.assertEqual(len(calls),1)

    def test_six_sections_are_required(self):
        self.r['h3_prompt']='<Picture 1> incomplete body'
        errors,_=transport_issues(self.r,self.e)
        self.assertTrue(any('missing required sections' in error for error in errors))

    def test_complete_six_section_prompt_passes(self):
        self.assertFalse(transport_issues(self.r,self.e)[0])

    def test_user_constraints_preserved(self):
        self.e['user_request']='保留八个镜头，文字 ABC 原样保留'
        self.e['directives']=[{'type':'preserve','value':'八个镜头'}]
        calls=[];invoke_compiler(self.e,lambda p:(calls.append(p) or copy.deepcopy(self.r)))
        self.assertIn(self.e['user_request'],calls[0]);self.assertIn('八个镜头',calls[0])

    def test_many_locked_shots_not_rejected(self):
        self.r['content_plan']['shots']=[{'start_seconds':i*.5,'end_seconds':(i+1)*.5} for i in range(10)]
        self.r['h3_prompt']=VALID_H3.replace('[Shot 1] A continuous view.', '\n'.join(f'[Shot {i}] A distinct view.' for i in range(1,11)))
        self.assertFalse(transport_issues(self.r,self.e)[0])

    def test_shot_extraction_preserves_final_text(self):
        prompt=VALID_H3.replace('[Shot 1] A continuous view.', '[Shot 1] First action.\n[Shot 2] Second action mentions Shot 1 without a label.')
        descriptions, errors=extract_shot_descriptions(prompt)
        self.assertEqual(errors, [])
        self.assertEqual(descriptions, ['First action.', 'Second action mentions Shot 1 without a label.'])

    def test_projection_does_not_mutate(self):
        self.e['assets'][0]['confidence']=.95
        before=copy.deepcopy(self.e);result=prepare_writer_evidence(self.e)
        self.assertNotIn('confidence',result['assets'][0]);self.assertEqual(self.e,before)

    def test_quality_flag_remains_honest(self):
        result=invoke_compiler(self.e,lambda _:copy.deepcopy(self.r))
        self.assertFalse(result['transport_audit']['semantic_quality_verified'])

if __name__=='__main__': unittest.main()
