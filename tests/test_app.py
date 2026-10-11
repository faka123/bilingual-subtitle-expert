import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest
from fastapi.testclient import TestClient
from subtitle_app.api import app


class AppTests(unittest.TestCase):
    def test_sample_process_input_change_and_clear(self):
        test = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'streamlit_app.py')).run()
        self.assertEqual(len(test.exception), 0)
        next(button for button in test.button if button.label == '加载示例数据').click().run()
        next(button for button in test.button if button.label == '🚀 开始排版' and button.key != 'btn_format_text').click().run()
        self.assertEqual(len(test.exception), 0)
        self.assertTrue(test.session_state['processed'])
        self.assertEqual(test.session_state['stats']['matched_entries'], 6)
        self.assertIn('Shenyang', test.session_state['output_srt'])
        test.text_area(key='proofread_text').set_value('你好世界\nHello world').run()
        self.assertNotIn('processed', test.session_state.filtered_state)
        next(button for button in test.button if button.label == '🗑️ 清空').click().run()
        self.assertEqual(len(test.exception), 0)
        self.assertEqual(test.text_area(key='proofread_text').value, '')
        self.assertEqual(test.text_area(key='srt_text').value, '')
        self.assertEqual(test.session_state['input_generation'], 1)

    def test_api_empty_input_rejected_and_anomaly_preserved(self):
        client = TestClient(app)
        self.assertEqual(client.post('/api/bilingual-subtitle', json={'proofread': {'pairs': []}, 'timeline': {'items': []}}).status_code, 422)
        result = client.post('/api/bilingual-subtitle', json={
            'proofread': {'pairs': [{'chinese': '你好世界', 'english': 'Hello world'}]},
            'timeline': {'items': [{'index': 5, 'start': '00:00:03,000', 'end': '00:00:02,000', 'text': '你好世界'}]},
        })
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['englishPart'][0]['index'], 6)
        self.assertEqual(result.json()['chinesePart'][0]['start'], '00:00:03,000')


if __name__ == '__main__':
    unittest.main()
