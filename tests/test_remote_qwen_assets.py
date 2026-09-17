import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.perception import LocalQwen3VL32BProvider, PerceptionProviderConfig
class RemoteAssetTests(unittest.TestCase):
    def provider(self):
        return LocalQwen3VL32BProvider(PerceptionProviderConfig(model='Qwen3.8-27B',options={'asset_upload_base_url':'http://upload:30100','image_base_url':'http://qwen:9012','video_base_url':'http://qwen:9012'}))
    def test_upload_once_and_invalidate_changed_file(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'input video.mp4';f.write_bytes(b'abc');p=self.provider()
            with patch('backend.perception.subprocess.run',return_value=subprocess.CompletedProcess([],0,'{"url":"http://asset/video.mp4"}','')) as call:
                self.assertEqual(p._media_url(f),'http://asset/video.mp4');p._media_url(f)
                self.assertEqual(call.call_count,1)
                self.assertIn('http://upload:30100/v1/assets',call.call_args.args[0])
                f.write_bytes(b'abcd');p._media_url(f);self.assertEqual(call.call_count,2)
    def test_media_payloads(self):
        with tempfile.TemporaryDirectory() as d:
            for suffix,kind in [('.png','image_url'),('.mp4','video_url')]:
                f=Path(d)/('input'+suffix);f.write_bytes(b'abc');p=self.provider()
                with patch.object(p,'_media_url',return_value='http://asset/input'+suffix),patch.object(p,'_request_json',return_value={'choices':[{'message':{'content':'{"summary":"ok"}'}}]}) as call:
                    params={'fps':2,'max_frames':256} if suffix=='.mp4' else {}
                    p._run_task(f,'Describe',Path(d)/'out',1024,**params);payload=call.call_args.args[2]
                    self.assertEqual(payload['messages'][0]['content'][1][kind]['url'],'http://asset/input'+suffix)
                    self.assertFalse(payload['stream']);self.assertEqual(payload['model'],'Qwen3.8-27B')
                    if params:self.assertEqual((payload['fps'],payload['max_frames']),(2,256))
    def test_upload_failure_stops_inference(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'image.png';f.write_bytes(b'abc')
            for response in [subprocess.CompletedProcess([],22,'failure','HTTP 500'),subprocess.CompletedProcess([],0,'{"url":"file:///tmp/image.png"}','')]:
                p=self.provider()
                with patch('backend.perception.subprocess.run',return_value=response),patch.object(p,'_request_json') as inference:
                    with self.assertRaises(RuntimeError):p._run_task(f,'Describe',Path(d)/'out',1024)
                    inference.assert_not_called()
