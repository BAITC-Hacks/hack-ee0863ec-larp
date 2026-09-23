import http.client
import json
import unittest

from hackalem.catalog import ROOT
from hackalem.cors import origin_key
from tests import test_web as web_tests


class CORSUnitTests(unittest.TestCase):
    def test_origin_validation(self):
        self.assertEqual(origin_key('http://LOCALHOST:80'), origin_key('http://localhost'))
        for value in ['http://[', 'null', 'https://host:99999', 'ftp://host', 'http://host/path',
                      'http://user@host', 'http://host#fragment', 'http://host?a=1', '*', 'http://host two']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                origin_key(value)


class CORSTests(unittest.TestCase):
    setUp = web_tests.ServerTests.setUp
    start = web_tests.ServerTests.start
    url = web_tests.ServerTests.url

    def request(self, method='GET', path='/api/options', headers=None, body=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.web.server_port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def allow_frontend(self):
        self.web.app.allowed_origins = frozenset({origin_key('http://localhost:5173')})

    def test_malformed_origin_returns_json_400(self):
        status, _, body = self.request('POST', '/api/recommend',
                                       {'Origin': 'http://[', 'Content-Type': 'application/json'}, b'{}')
        self.assertEqual(status, 400)
        self.assertIn('Origin', json.loads(body)['error'])

    def test_unlisted_origin_stays_forbidden(self):
        status, headers, _ = self.request(headers={'Origin': 'http://localhost:5173'})
        self.assertEqual(status, 403)
        self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_allowed_preflight_and_actual_request(self):
        self.allow_frontend()
        origin = 'http://localhost:5173'
        status, headers, body = self.request('OPTIONS', '/api/recommend', {
            'Origin': origin, 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'content-type'})
        self.assertEqual(status, 204)
        self.assertEqual(body, b'')
        self.assertEqual(headers['Access-Control-Allow-Origin'], origin)
        self.assertEqual(headers['Access-Control-Allow-Methods'], 'POST')
        raw = json.loads((ROOT / 'examples/dense.json').read_text(encoding='utf-8'))
        raw['budget_kzt'] = 0
        status, headers, body = self.request('POST', '/api/recommend',
                                            {'Origin': origin, 'Content-Type': 'application/json'}, json.dumps(raw).encode())
        self.assertEqual(status, 200)
        self.assertEqual(headers['Access-Control-Allow-Origin'], origin)
        self.assertEqual(json.loads(body)['cards'], [])

    def test_cors_headers_are_on_errors_and_options(self):
        self.allow_frontend()
        for method, path, body, expected in [('POST', '/api/recommend', b'{}', 400),
                                              ('GET', '/api/options', None, 200)]:
            status, headers, _ = self.request(method, path, {'Origin': 'http://localhost:5173', 'Content-Type': 'application/json'}, body)
            self.assertEqual(status, expected)
            self.assertEqual(headers['Access-Control-Allow-Origin'], 'http://localhost:5173')
            self.assertIn('Origin', headers['Vary'])

    def test_preflight_rejects_other_methods_headers_and_opaque_origins(self):
        self.allow_frontend()
        for extra, expected in [({'Access-Control-Request-Method': 'DELETE'}, 405),
                                ({'Access-Control-Request-Headers': 'authorization'}, 403),
                                ({'Origin': 'null'}, 403)]:
            headers = {'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST', **extra}
            self.assertEqual(self.request('OPTIONS', '/api/recommend', headers)[0], expected)

    def test_same_origin_needs_no_configuration(self):
        self.assertEqual(self.request(headers={'Origin': self.url(self.web)})[0], 200)
