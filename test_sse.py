"""Offline SSE transport regression checks; no production log writes."""
import io
import logging
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import agent
import api
from request_context import RequestIdFilter, run_metrics


class SSETests(unittest.TestCase):
    def test_completion_and_failure(self):
        logs = io.StringIO()
        handler = logging.StreamHandler(logs)
        handler.addFilter(RequestIdFilter())
        handler.setFormatter(logging.Formatter('%(request_id)s %(message)s'))
        root = logging.getLogger()
        old_handlers, old_level = root.handlers[:], root.level
        root.handlers = [handler]
        root.setLevel(logging.INFO)
        self.addCleanup(setattr, root, 'handlers', old_handlers)
        self.addCleanup(root.setLevel, old_level)
        api.app.state.client = object()

        def events(question, *, client):
            yield agent.TextEvent(chunk='hello\nworld')
            time.sleep(.05)
            metrics = run_metrics.get()
            metrics.steps = 2
            metrics.input_tokens = 17
            metrics.output_tokens = 4
            if question == 'fail':
                raise RuntimeError('PRIVATE')
            metrics.stop_reason = 'end_turn'
            yield agent.DoneEvent(result=agent.AgentResult(
                answer='ok', steps=2, stop_reason='end_turn'))

        http = TestClient(api.app)
        with patch('api.run_agent_stream', side_effect=events):
            for question in ('ok', 'fail'):
                response = http.post('/chat/stream', json={'question': question})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers['cache-control'], 'no-cache')
                self.assertEqual(response.headers['x-accel-buffering'], 'no')
                self.assertIn('event: text\n', response.text)
                self.assertIn('event: error' if question == 'fail' else 'event: done', response.text)
                self.assertNotIn('PRIVATE', response.text)
                lines = [line for line in logs.getvalue().splitlines()
                         if response.headers['x-request-id'] in line and 'event=request_complete' in line]
                self.assertEqual(len(lines), 1)
                self.assertIn('steps=2 input_tokens=17 output_tokens=4', lines[0])
                self.assertIn('outcome=error' if question == 'fail' else 'outcome=success', lines[0])
                self.assertGreaterEqual(float(lines[0].split('latency_ms=')[1].split()[0]), 50)
        with patch('api.run_agent', return_value=agent.AgentResult(answer='ok', steps=1, stop_reason='end_turn')):
            self.assertEqual(http.post('/chat', json={'question': 'A'}).json()['answer'], 'ok')
        with patch('api.run_agent', side_effect=RuntimeError('PRIVATE')):
            response = http.post('/chat', json={'question': 'A'})
            self.assertEqual(response.status_code, 500)
            self.assertNotIn('PRIVATE', response.text)
            self.assertEqual(response.json()['request_id'], response.headers['x-request-id'])
        self.assertEqual(http.post('/chat/stream', json={}).status_code, 422)


if __name__ == '__main__':
    unittest.main()
