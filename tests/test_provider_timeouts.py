"""Offline transport timeout controls; all HTTP uses MockTransport."""
import asyncio
import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
from spotify_pipeline.engine import Engine, fingerprint, load_config, validate_config, primary_classification_schema

ROOT = Path(__file__).resolve().parents[1]

class ProviderTimeoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config(ROOT / 'config/hero.json')

    def make_engine(self, overrides=None):
        e = Engine.__new__(Engine)
        e.config = copy.deepcopy(self.config)
        e.config.pop('provider_timeout_seconds', None)
        if overrides is not None:
            e.config['provider_timeout_seconds'] = overrides
        e.providers = {}
        return e

    def test_default_transport_timeout_is_unchanged(self):
        with patch.dict(os.environ, {'TYPESAFE_API_KEY':'synthetic', 'OPENAI_API_KEY':'synthetic', 'NEBIUS_API_KEY':'synthetic'}):
            for name in ('jev', 'openai', 'nebius', 'decisions'):
                e = self.make_engine()
                self.assertEqual(e._provider(name)._timeout, 60.0, name)

    def test_override_is_provider_specific(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY':'synthetic', 'NEBIUS_API_KEY':'synthetic'}):
            e = self.make_engine({'nebius': 180})
            self.assertEqual(e._provider('nebius')._timeout, 180)
            self.assertEqual(e._provider('decisions')._timeout, 60.0)
            self.assertEqual(e._provider('openai')._timeout, 60.0)

    def test_invalid_timeout_settings_rejected(self):
        for setting in (None, [], {'unsupported': 180}, {'nebius': True}, {'nebius': '180'},
                        {'nebius': float('nan')}, {'nebius': float('inf')}, {'nebius': 0},
                        {'nebius': -1}, {'nebius': 3601}):
            with self.subTest(setting=setting), self.assertRaisesRegex(ValueError, 'provider_timeout_seconds'):
                c = copy.deepcopy(self.config)
                c['provider_timeout_seconds'] = setting
                validate_config(c)

    def test_supported_bounds_accepted(self):
        for value in (0.001, 60, 180.0, 3600):
            c = copy.deepcopy(self.config)
            c['provider_timeout_seconds'] = {'nebius': value}
            validate_config(c)

    def test_operational_changes_preserve_label_fingerprint(self):
        c = copy.deepcopy(self.config)
        c['provider_timeout_seconds'] = {'nebius': 180}
        c['verification_workers'] = 32
        self.assertEqual(fingerprint(c), fingerprint(self.config))
        self.assertEqual(fingerprint(c), 'spotify-f84b2a9afdaa455fd81d26077cab1ccebc7a62bb1b46bab461d9ae593bcb584a')

    def test_provider_reuse_preserved(self):
        with patch.dict(os.environ, {'NEBIUS_API_KEY':'synthetic'}):
            e = self.make_engine({'nebius': 180})
            first = e._provider('nebius')
            self.assertIs(e._provider('nebius'), first)

    def test_injected_provider_not_replaced(self):
        sentinel = object()
        e = self.make_engine({'nebius': 180})
        e.providers['nebius'] = sentinel
        self.assertIs(e._provider('nebius'), sentinel)

    def test_httpx_receives_timeout_and_body_unchanged(self):
        async def check():
            seen = []
            def handler(request):
                seen.append((request.extensions['timeout'], json.loads(request.content)))
                return httpx.Response(200, json={'ok': True})
            with patch.dict(os.environ, {'NEBIUS_API_KEY':'synthetic'}):
                default = self.make_engine()._provider('nebius')
                extended = self.make_engine({'nebius': 180})._provider('nebius')
                kwargs = dict(model='zai-org/GLM-5.3', prompt='synthetic', payload={'reviews': []},
                              schema=primary_classification_schema(), reasoning_effort='low', max_output_tokens=6000)
                body = default.build_request(**kwargs)
                self.assertEqual(body, extended.build_request(**kwargs))
                for provider in (default, extended):
                    provider._transport = httpx.MockTransport(handler)
                    await provider._post(body)
                    await provider.aclose()
            self.assertEqual(seen[0][1], seen[1][1])
            self.assertTrue(all(v == 60.0 for v in seen[0][0].values()))
            self.assertTrue(all(v == 180 for v in seen[1][0].values()))
        asyncio.run(check())

if __name__ == '__main__':
    unittest.main()
