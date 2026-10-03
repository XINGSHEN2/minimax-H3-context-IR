import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.perception import QwenTransport, PerceptionProviderConfig
class RemoteAssetTests(unittest.TestCase):
    def provider(self):
        return QwenTransport(PerceptionProviderConfig(model='Qwen3.8-27B',options={'asset_upload_base_url':'http://upload:30100','image_base_url':'http://qwen:9012','video_base_url':'http://qwen:9012'}))
    def test_upload_once_and_invalidate_changed_file(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'input video.mp4';f.write_bytes(b'abc');p=self.provider()
            with patch('backend.perception.subprocess.run',return_value=subprocess.CompletedProcess([],0,'{"url":"http://asset/video.mp4"}','')) as call:
                self.assertEqual(p._media_url(f),'http://asset/video.mp4');p._media_url(f)
                self.assertEqual(call.call_count,1)
                self.assertIn('http://upload:30100/v1/assets',call.call_args.args[0])
                f.write_bytes(b'abcd');p._media_url(f);self.assertEqual(call.call_count,2)
    def test_upload_failure_stops_inference(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'image.png';f.write_bytes(b'abc')
            for response in [subprocess.CompletedProcess([],22,'failure','HTTP 500'),subprocess.CompletedProcess([],0,'{"url":"file:///tmp/image.png"}','')]:
                p=self.provider()
                with patch('backend.perception.subprocess.run',return_value=response),patch.object(p,'_request_json') as inference:
                    with self.assertRaises(RuntimeError):p._media_url(f)
                    inference.assert_not_called()
