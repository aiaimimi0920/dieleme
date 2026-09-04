from __future__ import annotations

from tools.test.avm_http_contract_context import *  # noqa: F401,F403


class AVMHttpContractPart11:
    def test_area_result_routes_reject_invalid_json(self):
        for path in ('/api/area_result', '/api/collection/details/area_result'):
            with self.subTest(path=path):
                req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=b'{', headers={'Content-Type': 'application/json'}, method='POST')
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode('utf-8'))
                self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_infer_location_routes_reject_invalid_json(self):
        for path in ('/api/infer_location', '/api/collection/details/infer_location'):
            with self.subTest(path=path):
                req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=b'{', headers={'Content-Type': 'application/json'}, method='POST')
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode('utf-8'))
                self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_approve_area_routes_reject_invalid_json(self):
        for path in ('/api/approve_area', '/api/collection/details/approve_area'):
            with self.subTest(path=path):
                req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=b'{', headers={'Content-Type': 'application/json'}, method='POST')
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode('utf-8'))
                self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_analyze_html_routes_reject_invalid_json(self):
        for path in ('/api/analyze_html', '/api/collection/details/html'):
            with self.subTest(path=path):
                req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=b'{', headers={'Content-Type': 'application/json'}, method='POST')
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode('utf-8'))
                self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

__all__ = ["AVMHttpContractPart11"]
