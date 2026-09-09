import copy,unittest
from backend.single_call_compiler import compile_once,transport_issues,COMPILER_REVISION,prepare_writer_evidence
class Tests(unittest.TestCase):
    def setUp(self):
        self.e={'task':{'duration_seconds':5},'assets':[{'asset_id':'image_1','media_type':'image'}]}
        self.r={'content_plan':{'bindings':[{'asset_id':'image_1'}],'shots':[{'start_seconds':0,'end_seconds':5}]},'h3_prompt':'<Picture 1> valid body'}
    def test_once_and_warning(self):
        calls=[];before=copy.deepcopy(self.e)
        result=compile_once(self.e,lambda p:(calls.append(p) or copy.deepcopy(self.r)))
        self.assertEqual(len(calls),1);self.assertEqual(result['status'],'ready_for_review');self.assertEqual(self.e,before)
    def test_unknown_reference(self):
        self.r['h3_prompt']='<Video 1> invented';self.assertTrue(transport_issues(self.r,self.e)[0])
    def test_one_repair(self):
        bad=copy.deepcopy(self.r);bad['content_plan']['bindings'][0]['asset_id']='image_2';answers=iter([bad,self.r])
        self.assertEqual(compile_once(self.e,lambda _:next(answers))['llm_calls'],2)
    def test_failure_not_success(self):
        self.r['content_plan']['shots'][0]['end_seconds']=6
        self.assertEqual(compile_once(self.e,lambda _:self.r)['status'],'needs_review')
    def test_nan(self):
        self.r['content_plan']['shots'][0]['end_seconds']=float('nan');self.assertTrue(transport_issues(self.r,self.e)[0])
    def test_editorial_rules_and_revision(self):
        calls=[]
        result=compile_once(self.e,lambda p:(calls.append(p) or copy.deepcopy(self.r)))
        for heading in ['EDITORIAL CONSTRUCTION','INFORMATION PLACEMENT','EVIDENCE CALIBRATION','CAUSAL AND STATE CHECK','developments','development_ids','There is no target shot count']:
            self.assertIn(heading,calls[0])
        self.assertEqual(result['compiler_revision'],COMPILER_REVISION)
        self.assertEqual(len(calls),1)
    def test_new_notes_are_not_validation_gates(self):
        self.assertFalse(transport_issues(self.r,self.e)[0])
    def test_user_constraints_preserved_in_model_input(self):
        self.e['user_request']='保留八个镜头，文字 ABC 原样保留'
        self.e['directives']=[{'type':'preserve','value':'八个镜头'}]
        calls=[]
        compile_once(self.e,lambda p:(calls.append(p) or copy.deepcopy(self.r)))
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
        compile_once(self.e,lambda p:(calls.append(p) or copy.deepcopy(self.r)))
        self.assertNotIn('"confidence":0.95',calls[0])
        self.assertIn('Cross-check user-mentioned names and text against OCR',calls[0])
        self.assertIn('casual',calls[0])
        self.assertEqual(len(calls),1)
    def test_continuity_and_foley_rules_in_same_call(self):
        calls=[]
        self.e['user_request']='Keep fast cuts, flash-white transitions and the original soundtrack.'
        result=compile_once(self.e,lambda p:(calls.append(p) or copy.deepcopy(self.r)))
        for phrase in ['SHOT-BOUNDARY CONTINUITY','EVENT-DRIVEN SOUND',
                       'outgoing action phase','cease when walking stops',
                       'continues off-screen','Natural decay may cross a',
                       'Keep user-required fast cuts','locked source track',
                       'Do not invent exact contact timestamps']:
            self.assertIn(phrase,calls[0])
        self.assertIn(self.e['user_request'],calls[0])
        self.assertEqual(result['llm_calls'],1)
        self.assertFalse(result['transport_audit']['semantic_quality_verified'])
    def test_content_authority_and_completion_without_extra_call(self):
        calls=[]
        self.e['user_request']='Follow the reference action; keep its ending. Reference voice timbre only.'
        result=compile_once(self.e,lambda p:(calls.append(p) or copy.deepcopy(self.r)))
        for phrase in ['CONTENT AUTHORITY','CREATIVE COMPLETION',
                       'A similar','necessary physical prerequisites',
                       'Delete redundant phrasing, not the content',
                       'Do not invent copy intervals',
                       'do not invent a final pose',
                       'critical reference evidence is missing']:
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
                result=compile_once(evidence,lambda p:(calls.append(p) or copy.deepcopy(self.r)))
                self.assertEqual(len(calls),1)
                self.assertIn(request,calls[0])
                self.assertIn('not unspecified creative choices',calls[0])
                self.assertIn('not permission to delete bystanders',calls[0])
                self.assertEqual(result['content_plan'],self.r['content_plan'])
                self.assertFalse(result['transport_audit']['semantic_quality_verified'])
if __name__=='__main__':unittest.main()
