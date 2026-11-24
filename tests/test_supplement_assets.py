import gzip
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "supplement_assets.py"
spec = importlib.util.spec_from_file_location("assets", MODULE)
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


def digest(value):
    return hashlib.sha256(value).hexdigest()


class AssetsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / "cache"
        self.data = {"Course 1/lab/one.bin": b"a" * 8192, "Course 5/lab/two.bin": bytes(range(256)) * 20}
        self.archive = self.make_archive(self.data)
        self.parts = [self.archive[:113], self.archive[113:]]
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                value = owner.parts[int(self.path.strip('/'))]
                header = self.headers.get('Range')
                owner.requests.append(header)
                offset = int(header.split('=')[1].split('-')[0]) if header else 0
                if getattr(owner, 'ignore_range', False): offset = 0
                self.send_response(206 if offset else 200)
                if offset: self.send_header('Content-Range', f'bytes {offset}-{len(value)-1}/{len(value)}')
                self.send_header('Content-Length', str(len(value)-offset))
                self.end_headers()
                if getattr(owner, 'disconnect_once', False):
                    owner.disconnect_once = False
                    self.wfile.write(value[offset:offset+37])
                    self.wfile.flush()
                    self.close_connection = True
                    return
                self.wfile.write(value[offset:])

            def log_message(self, *_): pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.manifest = {
            'version': 1, 'release_tag': 'test-v1',
            'archive': {'format': 'tar.gz', 'name': 'test.tar.gz', 'size': len(self.archive), 'sha256': digest(self.archive),
                'parts': [{'name': f'test.tar.gz.{i:03d}', 'size': len(value), 'sha256': digest(value),
                           'url': f'http://127.0.0.1:{self.server.server_port}/{i}'} for i,value in enumerate(self.parts)]},
            'files': [{'path': name, 'size': len(value), 'sha256': digest(value), 'course': int(Path(name).parts[0].split()[1])}
                      for name,value in self.data.items()]}
        self.path = self.root/'manifest.json'
        self.save()

    @staticmethod
    def make_archive(files):
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode='w') as archive:
            for name, value in files.items():
                info = tarfile.TarInfo(name); info.size = len(value)
                archive.addfile(info, io.BytesIO(value))
        return gzip.compress(raw.getvalue(), mtime=0)

    def save(self): self.path.write_text(json.dumps(self.manifest), encoding='utf-8')

    def ensure(self, **kwargs):
        return assets.ensure_assets(self.root, self.path, cache=self.cache, **kwargs)

    def test_split_download_restore_and_no_network_on_second_run(self):
        self.assertEqual(self.ensure(), 2)
        for name,value in self.data.items(): self.assertEqual((self.root/name).read_bytes(), value)
        times = {name:(self.root/name).stat().st_mtime_ns for name in self.data}
        with patch.object(assets, 'download_part', side_effect=AssertionError('unexpected download')):
            self.assertEqual(self.ensure(), 0)
        self.assertEqual(times, {name:(self.root/name).stat().st_mtime_ns for name in self.data})

    def test_partial_install_preserves_existing_and_reuses_archive_cache(self):
        self.ensure(courses=[1])
        first = self.root/'Course 1/lab/one.bin'; timestamp = first.stat().st_mtime_ns
        self.assertFalse((self.root/'Course 5/lab/two.bin').exists())
        with patch.object(assets.urllib.request, 'urlopen', side_effect=AssertionError('unexpected download')):
            self.assertEqual(self.ensure(), 1)
        self.assertEqual(timestamp, first.stat().st_mtime_ns)

    def test_corrupt_file_is_backed_up_and_repaired(self):
        self.ensure(); target=self.root/'Course 1/lab/one.bin'; target.write_bytes(b'local changes')
        self.assertEqual(self.ensure(), 1)
        self.assertEqual(target.read_bytes(), self.data['Course 1/lab/one.bin'])
        self.assertEqual(next((self.cache/'backups/Course 1/lab').iterdir()).read_bytes(), b'local changes')

    def test_resume_partial_volume(self):
        self.cache.mkdir(); item=self.manifest['archive']['parts'][1]
        (self.cache/(item['name']+'.part')).write_bytes(self.parts[1][:50])
        assets.download_part(item, self.cache, delay=lambda _:None)
        self.assertIn('bytes=50-', self.requests)
        self.assertEqual((self.cache/item['name']).read_bytes(), self.parts[1])

    def test_range_ignored_restarts_without_duplicate_bytes(self):
        self.ignore_range=True; self.test_resume_partial_volume()

    def test_interrupted_download_is_resumed(self):
        self.disconnect_once = True
        item = self.manifest['archive']['parts'][1]
        assets.download_part(item, self.cache, delay=lambda _:None)
        self.assertIn('bytes=37-', self.requests)
        self.assertEqual((self.cache/item['name']).read_bytes(), self.parts[1])

    def test_bad_cached_volume_is_downloaded_again(self):
        self.ensure(); item=self.manifest['archive']['parts'][0]
        (self.cache/item['name']).write_bytes(b'bad')
        assets.download_part(item, self.cache, delay=lambda _:None)
        self.assertEqual((self.cache/item['name']).read_bytes(), self.parts[0])

    def test_missing_assets_check_only_does_not_download(self):
        with self.assertRaisesRegex(RuntimeError, 'missing or invalid'): self.ensure(check_only=True)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.ensure(courses=[3]), 0)

    def test_bad_hash_is_rejected_before_extraction(self):
        self.manifest['archive']['parts'][0]['sha256']='0'*64; self.save()
        with patch.object(assets.time, 'sleep', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'SHA-256'): self.ensure()
        self.assertFalse((self.root/'Course 1').exists())

    def test_archive_path_traversal_and_symlinks_rejected(self):
        self.manifest['files'][0]['path']='../outside'; self.save()
        with self.assertRaises(ValueError): self.ensure()
        self.assertEqual(self.requests, [])
        info=tarfile.TarInfo('Course 1/lab/one.bin');info.type=tarfile.SYMTYPE;info.linkname='../outside'
        raw=io.BytesIO()
        with tarfile.open(fileobj=raw,mode='w') as tar:tar.addfile(info)
        bad=self.root/'bad.tar.gz';bad.write_bytes(gzip.compress(raw.getvalue()))
        self.cache.mkdir(exist_ok=True)
        self.manifest['files'][0]['path']='Course 1/lab/one.bin'
        with self.assertRaisesRegex(ValueError,'Unexpected archive member'):
            assets.restore_archive(self.root,self.manifest,[bad],set(self.data),self.cache)


class EnvironmentScanTests(unittest.TestCase):
    def test_macos_notebook_sidecars_are_not_parsed_as_source(self):
        location = MODULE.parent/'check_env.py'
        spec = importlib.util.spec_from_file_location('check_env', location)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); course = root/'Course 5 - Test'; course.mkdir()
            (course/'._notebook.ipynb').write_bytes(b'\x00\xa2\xff')
            (course/'example.py').write_text('import json\n', encoding='utf-8')
            with patch.object(module, 'ROOT', root), patch.object(module, 'EXTERNAL', {'json'}):
                module.course_imports(5)


if __name__ == '__main__': unittest.main()
