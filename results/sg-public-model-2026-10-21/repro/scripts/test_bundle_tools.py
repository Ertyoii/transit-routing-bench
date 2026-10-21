"""Small synthetic tests only: no network, Go, datasets or routers."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import sourcehash
import retrieve_inputs
import install_helpers

class BundleToolsTests(unittest.TestCase):
    def test_source_hash_matches_framing_and_excludes_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'a.go').write_bytes(b'package a')
            (root / 'artifacts').mkdir()
            (root / 'artifacts/ignore.go').write_bytes(b'excluded')
            expected = hashlib.sha256(b'4:a.go:9:package a').hexdigest()
            self.assertEqual(sourcehash.source_hash(root), expected)

    def prepare(self, d, body=b'abc'):
        root = Path(d)
        bundle = root / 'bundle'
        bundle.mkdir()
        item = {'id': 'gtfs', 'url': 'https://example.invalid/source', 'destination': 'data/input.bin', 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
        (bundle / 'SOURCE_PINS.json').write_text(json.dumps({'source_inputs': [item]}))
        return root / 'out', bundle, item

    def invoke(self, root, bundle, extra, opener=None):
        args = ['retrieve_inputs.py', '--root', str(root)] + extra
        with mock.patch.object(retrieve_inputs, 'BUNDLE', bundle), mock.patch.object(sys, 'argv', args), mock.patch.object(retrieve_inputs.urllib.request, 'build_opener', return_value=opener), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            retrieve_inputs.main()

    def test_retrieval_without_terms_fails_before_network(self):
        with tempfile.TemporaryDirectory() as d:
            root, bundle, _ = self.prepare(d)
            with self.assertRaises(SystemExit):
                self.invoke(root, bundle, [])

    def test_verify_only_checks_existing_bytes_without_network(self):
        with tempfile.TemporaryDirectory() as d:
            root, bundle, item = self.prepare(d)
            dest = root / item['destination']
            dest.parent.mkdir(parents=True)
            dest.write_bytes(b'abc')
            self.invoke(root, bundle, ['--verify-only'])
            dest.write_bytes(b'bad')
            with self.assertRaises(ValueError):
                self.invoke(root, bundle, ['--verify-only'])

    def test_mismatch_removes_only_own_partial(self):
        with tempfile.TemporaryDirectory() as d:
            root, bundle, item = self.prepare(d)
            response = io.BytesIO(b'bad')
            response.geturl = lambda: 'https://example.invalid/source'
            opener = mock.Mock()
            opener.open.return_value = response
            with self.assertRaises(ValueError):
                self.invoke(root, bundle, ['--accept-provider-terms'], opener)
            destination = root / item['destination']
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_name(destination.name + '.partial').exists())
            partial = destination.with_name(destination.name + '.partial')
            partial.write_bytes(b'previous attempt')
            with self.assertRaises(FileExistsError):
                self.invoke(root, bundle, ['--accept-provider-terms'], opener)
            self.assertEqual(partial.read_bytes(), b'previous attempt')

    def test_helper_install_expands_json_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bundle = root / 'bundle'
            (bundle / 'helpers/data').mkdir(parents=True)
            (bundle / 'helpers/data/meta.json').write_text(json.dumps({'path': '${SG_ROOT}/data'}))
            destination = root / 'output'
            with mock.patch.object(install_helpers, 'BUNDLE', bundle), mock.patch.object(sys, 'argv', ['install_helpers.py', '--root', str(destination)]), contextlib.redirect_stdout(io.StringIO()):
                install_helpers.main()
                self.assertEqual(json.loads((destination / 'data/meta.json').read_text())['path'], str(destination / 'data'))
                with self.assertRaises(ValueError):
                    install_helpers.main()

if __name__ == '__main__':
    unittest.main()
