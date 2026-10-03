import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.perception import MultimodalPerception, validate_analysis
from backend.evidence import build_writer_evidence


def item(aid, kind='image'):
    return {'asset_id': aid, 'summary': '观察',
            'visual': {'entities': [{'entity_id': 'person_1', 'summary': '黑衣人物', 'features': []}],
                       'relations': [], 'events': [], 'visible_text': []},
            'audio': {'status': 'not_applicable' if kind == 'image' else 'analyzed',
                      'speech_segments': [], 'sound_events': []},
            'audio_visual_links': [], 'uncertainties': []}


class PerceptionV3Tests(unittest.TestCase):
    def test_namespace_and_cross_image_refs_survive_revalidation(self):
        assets=[{'asset_id': aid, 'media_type': 'image'} for aid in ['img_a','img_b']]
        raw={'assets':[item('img_a'),item('img_b')], 'cross_asset_relations':[
            {'references':[{'asset_id':a['asset_id'],'entity_id':'person_1'} for a in assets]}]}
        value=validate_analysis(raw,assets,{})
        self.assertEqual(value['cross_asset_relations'][0]['references'][1]['entity_id'],'img_b:person_1')
        self.assertEqual(value,validate_analysis(value,assets,{}))
        raw['cross_asset_relations'][0]['references'][0]['asset_id']='missing'
        with self.assertRaises(ValueError): validate_analysis(raw,assets,{})

    def test_time_bounds_and_missing_audio(self):
        asset={'asset_id':'video_1','media_type':'video'}
        record=item('video_1','video')
        record['visual']['events']=[{'event_id':'event_1','time_range':[0,27],'entity_ids':['person_1'],'action':'说话'}]
        raw={'assets':[record],'cross_asset_relations':[]}
        meta={'video_1':{'duration_seconds':15.07,'has_audio':True}}
        checked=validate_analysis(raw,[asset],meta)
        self.assertIsNone(checked['assets'][0]['visual']['events'][0]['time_range'])
        self.assertEqual(checked['assets'][0]['visual']['events'][0]['rejected_time_range'],[0,27])
        record['visual']['events'][0]['time_range']=None
        result=validate_analysis(raw,[asset],meta)
        self.assertEqual(result['assets'][0]['visual']['events'][0]['timing_status'],'unknown')
        meta['video_1']['has_audio']=False
        with self.assertRaises(ValueError): validate_analysis(raw,[asset],meta)

    def test_speech_and_links_reach_writer(self):
        asset={'asset_id':'video_1','media_type':'video'}; record=item('video_1','video')
        record['visual']['events']=[{'event_id':'event_1','time_range':[12,14],'entity_ids':['person_1'],'action':'展示袋子'}]
        record['audio']['speech_segments']=[{'segment_id':'speech_1','time_range':[12,14],'text':'买了一些小零食'}]
        record['audio_visual_links']=[{'event_id':'event_1','segment_id':'speech_1'}]
        value=validate_analysis({'assets':[record],'cross_asset_relations':[]},[asset],{'video_1':{'duration_seconds':15.07,'has_audio':True}})
        result=build_writer_evidence({'assets':[asset],'perception':value,'user_request':'换最后一句'})
        self.assertEqual(result['assets'][0]['audio']['speech_segments'][0]['text'],'买了一些小零食')
        self.assertEqual(result['reference_registry'][-1]['official_label'],'<Audio 1>')
        self.assertEqual(result['reference_registry'][-1]['source_asset_id'],'video_1')
        self.assertEqual(result['assets'][0]['audio_visual_links'][0]['event_id'],'video_1:event_1')

    def test_audio_cannot_invent_visuals(self):
        with self.assertRaises(ValueError):
            validate_analysis({'assets':[item('audio_1','audio')],'cross_asset_relations':[]},
                [{'asset_id':'audio_1','media_type':'audio'}],{'audio_1':{'has_audio':True,'duration_seconds':4}})

    def test_images_are_one_call_and_omni_receives_measured_duration(self):
        assets=[{'asset_id':i,'media_type':k,'uri':'https://example.com/'+i}
                for i,k in [('a','image'),('b','image'),('v','video'),('s','audio')]]
        service=MultimodalPerception({"omni_fps":4,"omni_video_max_pixels":65536}); calls=[]
        def transport(method,path,payload,**kwargs):
            calls.append((payload,kwargs))
            blocks=payload['messages'][0]['content']
            ids=[b['text'].split('=',1)[1] for b in blocks if b.get('type')=='text' and b['text'].startswith('asset_id=')]
            records=[]
            for aid in ids:
                kind=next(a['media_type'] for a in assets if a['asset_id']==aid)
                record=item(aid,kind)
                if kind=='audio': record['visual']['entities']=[]
                records.append(record)
            return {'choices':[{'message':{'content':json.dumps({'assets':records,'cross_asset_relations':[]})}}]}
        with tempfile.TemporaryDirectory() as d, patch('backend.perception.probe',side_effect=lambda a:{} if a['media_type']=='image' else {'duration_seconds':15.07,'has_audio':True}), patch.object(service.transport,'_request_json',side_effect=transport):
            result=service.analyze({'user_request':'检查原素材','assets':assets},d)
        self.assertEqual(len(calls),3)
        for payload, _ in calls:
            is_video = any(b['type'] == 'video_url' for b in payload['messages'][0]['content'])
            self.assertEqual('fps' in payload, is_video)
            self.assertEqual('video_max_pixels' in payload, is_video)
            if is_video:
                self.assertEqual(payload['fps'], 4)
                self.assertEqual(payload['video_max_pixels'], 65536)
        image_call=next(p for p,k in calls if p['model']=='Qwen3.8-27B')
        self.assertEqual(sum(b['type']=='image_url' for b in image_call['messages'][0]['content']),2)
        for payload,_ in calls:
            if payload['model'].endswith('Instruct'):
                self.assertIn('15.07',payload['messages'][0]['content'][0]['text'])
        self.assertEqual([a['asset_id'] for a in result['assets']],['a','b','v','s'])

    def test_pipeline_does_not_call_intent_resolver(self):
        from backend.agent import run_agent
        source={'user_request':'做一段视频','assets':[], 'task':{'type':'t2va','duration_seconds':5,'aspect_ratio':'16:9'}}
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ',{'DEEPSEEK_API_KEY':'test'}), patch('backend.agent.preflight_reasoning_provider'), patch('backend.agent.resolve_intent',side_effect=AssertionError('must not call')), patch('backend.agent.ensure_perception',side_effect=lambda s,**k:{**s,'perception':{'schema_version':'media_analysis.v3','assets':[],'cross_asset_relations':[]}}), patch('backend.compiler.compile_prompt',return_value=0) as compiler:
            run_agent(source,Path(directory)/'run',None)
            self.assertEqual(compiler.call_args.args[0]['user_request'],'做一段视频')


if __name__=='__main__': unittest.main()


def test_compact_audio_and_invalid_time_are_preserved_for_review():
    from backend.perception import expand_compact
    assets=[{"asset_id":"v","media_type":"video"}]
    meta={"v":{"duration_seconds":15.07,"has_audio":True}}
    raw={"assets":[{"asset_id":"v","summary":"人物说话", "entities":[["p","person","黑衣人物"]],
        "events":[["e",18,27,["p"],"展示袋子"]],"speech":[["s",12,14,"speaker_1","买了一些小零食"]],
        "sounds":[],"links":[["s","e","人物说话"]],"uncertainties":[]} ]}
    value=validate_analysis(expand_compact(raw,assets,meta),assets,meta)
    event=value["assets"][0]["visual"]["events"][0]
    assert event["time_range"] is None
    assert event["timing_status"]=="invalid_model_time"
    assert validate_analysis(value,assets,meta)==value
    assert value["assets"][0]["audio_visual_links"][0]["event_id"]=="v:e"


def test_too_many_images_fail_before_calling_models():
    from unittest.mock import patch
    assets=[{"asset_id":str(i),"media_type":"image","uri":"missing"} for i in range(9)]
    with patch("backend.perception.probe",side_effect=AssertionError("must reject first")):
        import pytest
        with pytest.raises(ValueError,match="at most 8"):
            MultimodalPerception().analyze({"assets":assets,"user_request":"检查"},"/tmp/unused-v3")
