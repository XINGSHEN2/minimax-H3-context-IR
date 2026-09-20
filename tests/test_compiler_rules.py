import copy,unittest
from backend.compiler import transport_issues,COMPILER_REVISION,prepare_writer_evidence
import json, tempfile, time
from pathlib import Path
from unittest.mock import patch
from backend.compiler import compile_prompt

def invoke_compiler(evidence, invoke):
    # Test adapter exercises the actual production entry, with no repair loop.
    source=copy.deepcopy(evidence)
    source['task']={'type':'ref2va','aspect_ratio':'16:9', **source['task']}
    for asset in source['assets']: asset.setdefault('uri','/tmp/reference.png')
    with tempfile.TemporaryDirectory() as directory:
        out=Path(directory)
        with patch('backend.evidence.build_writer_evidence',return_value=source), patch('backend.agent.invoke_reasoning_json',side_effect=lambda prompt,*args,**kwargs:invoke(prompt)):
            try: compile_prompt(source,out,{}, {'stages_seconds':{}},time.perf_counter())
            except ValueError: pass
        result=json.loads((out/'compilation_result.json').read_text())
        result.update(json.loads((out/'result_status.json').read_text()))
        result['transport_audit']=json.loads((out/'h3_prompt_audit.json').read_text())
        result['compiler_revision']=result['transport_audit']['compiler_revision']
        return result

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
    def test_editorial_rules_and_revision(self):
        calls=[]
        result=invoke_compiler(self.e,lambda p:(calls.append(p) or copy.deepcopy(self.r)))
        for heading in ['第二阶段：最终分镜','第三阶段：锁定计划并交接 H3','同一分析中','developments','development_ids','最小充分补全','不得借写作过程新增、删除、合并或重新拆分','最终响应契约','不输出 action_units 或 shot_merge_audit','每个 Shot 至少承载一个 development','H3 Shot Planning Skill']:
            self.assertIn(heading,calls[0])
        self.assertEqual(result['compiler_revision'],COMPILER_REVISION)
        from backend.prompt_instructions import COMPACT_WRITING_INSTRUCTIONS
        self.assertTrue(calls[0].startswith(COMPACT_WRITING_INSTRUCTIONS))
        self.assertEqual(calls[0].count(COMPACT_WRITING_INSTRUCTIONS),1)
        self.assertEqual(len(calls),1)
    def test_six_sections_are_required(self):
        self.r['h3_prompt'] = '<Picture 1> incomplete body'
        errors, warnings = transport_issues(self.r, self.e)
        self.assertTrue(any('missing required sections' in error for error in errors))
        self.assertFalse(warnings)

    def test_complete_six_section_prompt_passes(self):
        self.assertFalse(transport_issues(self.r,self.e)[0])
    def test_user_constraints_preserved_in_model_input(self):
        self.e['user_request']='保留八个镜头，文字 ABC 原样保留'
        self.e['directives']=[{'type':'preserve','value':'八个镜头'}]
        calls=[]
        invoke_compiler(self.e,lambda p:(calls.append(p) or copy.deepcopy(self.r)))
        self.assertIn(self.e['user_request'],calls[0]);self.assertIn('八个镜头',calls[0])
    def test_many_locked_shots_not_rejected(self):
        self.r['content_plan']['shots']=[{'start_seconds':i*.5,'end_seconds':(i+1)*.5} for i in range(10)]
        self.assertFalse(transport_issues(self.r,self.e)[0])
    def test_observation_scores_removed_without_mutation(self):
        self.e['assets'][0]['visible_text']=[{'text':'ABC','confidence':.95,'source':'visible','legibility':'exact','uncertainty':'last letter unclear','region':[0,1,2,3]}]
        self.e['directives']=[{'confidence':.8,'text':'Keep ABC'}]
        before=copy.deepcopy(self.e)
        result=prepare_writer_evidence(self.e)
        text=result['assets'][0]['visible_text'][0]
        self.assertNotIn('confidence',text)
        self.assertEqual(text['uncertainty'],'last letter unclear')
        self.assertEqual(text['region'],[0,1,2,3])
        self.assertEqual(text['legibility'],'exact')
        self.assertEqual(result['directives'],self.e['directives'])
        self.assertEqual(self.e,before)
        self.assertEqual(prepare_writer_evidence(result),result)
    def test_actual_call_uses_projection_and_conflict_policy(self):
        self.e['assets'][0]['confidence']=.95
        calls=[]
        invoke_compiler(self.e,lambda p:(calls.append(p) or copy.deepcopy(self.r)))
        self.assertNotIn('"confidence":0.95',calls[0])
        self.assertIn('其拼写与 OCR 冲突',calls[0])
        self.assertIn('仅描述素材时',calls[0])
        self.assertEqual(len(calls),1)
    def test_execution_rules_are_delegated_to_system_skill(self):
        calls=[]
        self.e['user_request']='Keep fast cuts, flash-white transitions and the original soundtrack.'
        result=invoke_compiler(self.e,lambda p:(calls.append(p) or copy.deepcopy(self.r)))
        for phrase in ['第三阶段：锁定计划并交接 H3',
                       '按照 system prompt 中的 H3 Prompt Writing Skill',
                       '按照 system prompt 中的 H3 Sound Planning Skill',
                       '音频不得新增或改变视觉事件',
                       'editing_treatments','最终响应契约']:
            self.assertIn(phrase,calls[0])
        for moved_phrase in ['每个边界只允许一个转场事件',
                             '同一次、同方向、尚未结束',
                             '声音必须有明确物理触发']:
            self.assertNotIn(moved_phrase,calls[0])
        self.assertIn(self.e['user_request'],calls[0])
        self.assertEqual(result['llm_calls'],1)
        self.assertFalse(result['transport_audit']['semantic_quality_verified'])
    def test_content_authority_and_completion_without_extra_call(self):
        calls=[]
        self.e['user_request']='Follow the reference action; keep its ending. Reference voice timbre only.'
        result=invoke_compiler(self.e,lambda p:(calls.append(p) or copy.deepcopy(self.r)))
        for phrase in ['以原始 user_request 为依据','补全原则：保留有作用的补全',
                       '不能以相似动作替代','用户明确的内容、动作、顺序、时间、镜头、素材用途和结局必须保留',
                       '按照 system prompt 中的 H3 Prompt Writing Skill',
                       '音频不得新增或改变视觉事件',
                       '非用户明示的内容必须具有必要的因果或展示依据',
                       '关键参考证据缺失']:
            self.assertIn(phrase,calls[0])
        self.assertIn(self.e['user_request'],calls[0])
        self.assertEqual(result['llm_calls'],1)
        self.assertEqual(result['status'],'ready_for_review')
    def test_completion_keeps_input_and_single_call_for_each_request_scope(self):
        # Wiring regression, not a claim that a live model obeys these policies.
        for request in ['做一支高级包袋广告',
                        '开场人物背对镜头站在门前，生成15秒短片',
                        '严格复刻视频动作，只替换人物，保持结尾不变']:
            with self.subTest(request=request):
                evidence=copy.deepcopy(self.e)
                evidence['user_request']=request
                calls=[]
                result=invoke_compiler(evidence,lambda p:(calls.append(p) or copy.deepcopy(self.r)))
                self.assertEqual(len(calls),1)
                self.assertIn(request,calls[0])
                self.assertIn('派生的 creative:false 不自动禁止未指定的创作',calls[0])
                self.assertIn('不授权删除编辑底片中的旁人',calls[0])
                self.assertEqual(result['content_plan'],self.r['content_plan'])
                self.assertFalse(result['transport_audit']['semantic_quality_verified'])
if __name__=='__main__':unittest.main()
