import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

SPEC = importlib.util.spec_from_file_location('cbz', Path(__file__).resolve().parents[2] / 'scripts/cbz/cbz.py')
cbz = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cbz
SPEC.loader.exec_module(cbz)


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'input'
        self.output = self.root / 'output'
        self.assets = self.root / 'assets'
        self.assets.mkdir()
        self.config = self.root / 'volumes.json'
        self.series = {'title': 'Test & Series', 'folder': 'Test', 'requireCover': False,
                       'outputFolder': 'Test', 'volumes': [{'volume': 0, 'chapters': [1, 1.5, 2]}]}
        for chapter in ('1', '1.5', '2'):
            path = self.source / 'Test' / f'Ch. {chapter}'
            path.mkdir(parents=True)
            (path / '10.jpg').write_bytes(b'tenth page')
            (path / '2.jpg').write_bytes(b'second page')

    def run_cli(self, command, *extra):
        self.config.write_text(json.dumps({'series': [self.series]}), encoding='utf-8')
        argv = [command, '--config', str(self.config), '--root', str(self.source),
                '--output', str(self.output), '--assets-root', str(self.assets), *extra]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cbz.main(argv)

    def archives(self):
        return list(self.output.rglob('*.cbz'))

    def test_plan_has_no_writes(self):
        self.assertEqual(self.run_cli('plan'), 0)
        self.assertFalse(self.output.exists())

    def test_build_natural_order_decimal_chapters_and_xml(self):
        self.assertEqual(self.run_cli('build', '--volume', '0'), 0)
        target = self.archives()[0]
        self.assertEqual(cbz.verify(target), 6)
        with zipfile.ZipFile(target) as z:
            self.assertEqual(z.read(z.namelist()[0]), b'second page')
            self.assertIn('ch1.5', z.namelist()[2])
            info = ET.fromstring(z.read('ComicInfo.xml'))
            self.assertEqual(info.findtext('Series'), 'Test & Series')
            self.assertIsNone(info.find('Pages'))

    def test_partial_requires_opt_in_and_is_labelled(self):
        self.series['volumes'][0]['chapters'].append(3)
        self.assertEqual(self.run_cli('build'), 1)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.run_cli('build', '--allow-partial'), 0)
        self.assertTrue(self.archives()[0].name.endswith('.incomplete.cbz'))
        with zipfile.ZipFile(self.archives()[0]) as z:
            self.assertIn('Chapter 3', ET.fromstring(z.read('ComicInfo.xml')).findtext('Notes'))

    def test_missing_optional_is_not_partial(self):
        self.series['volumes'][0]['optionalChapters'] = [-12.5]
        self.assertEqual(self.run_cli('build'), 0)

    def test_cover_is_first_and_counted(self):
        self.series['volumes'][0]['cover'] = 'cover.png'
        (self.assets / 'cover.png').write_bytes(b'cover bytes')
        self.assertEqual(self.run_cli('build'), 0)
        with zipfile.ZipFile(self.archives()[0]) as z:
            self.assertEqual(z.namelist()[0], '000_cover.png')
            info = ET.fromstring(z.read('ComicInfo.xml'))
            self.assertEqual(info.find('Pages/Page').attrib, {'Image': '0', 'Type': 'FrontCover'})
            self.assertEqual(info.findtext('PageCount'), '7')

    def test_overwrite_refused_and_failed_rebuild_keeps_original(self):
        self.assertEqual(self.run_cli('build'), 0)
        target = self.archives()[0]
        previous = target.read_bytes()
        self.assertEqual(self.run_cli('build'), 2)
        with patch.object(cbz, 'verify', side_effect=ValueError('verification failed')):
            self.assertEqual(self.run_cli('build', '--force'), 2)
        self.assertEqual(target.read_bytes(), previous)
        self.assertEqual(list(target.parent.glob('*.tmp')), [])
        self.assertEqual(self.run_cli('build', '--force'), 0)

    def test_explicit_order_preserved(self):
        self.series['volumes'][0]['chapters'] = [2, 1.5, 1]
        self.assertEqual(self.run_cli('build'), 0)
        with zipfile.ZipFile(self.archives()[0]) as z:
            self.assertIn('ch2_', z.namelist()[0])

    def test_duplicate_chapter_assignment_rejected(self):
        self.series['volumes'].append({'volume': 1, 'chapters': [2]})
        self.assertEqual(self.run_cli('build'), 2)
        self.assertFalse(self.output.exists())

    def test_chapter_cbz_input(self):
        for chapter in ('1', '1.5', '2'):
            with zipfile.ZipFile(self.source / 'Test' / f'Ch. {chapter}.cbz', 'w') as z:
                z.writestr('10.png', b'page ten')
                z.writestr('2.png', b'page two')
                z.writestr('ComicInfo.xml', '<ComicInfo/>')
        self.series['chapterFolderPattern'] = 'Ch. {chapter}.cbz'
        self.assertEqual(self.run_cli('build'), 0)
        with zipfile.ZipFile(self.archives()[0]) as z:
            self.assertEqual(z.read(z.namelist()[0]), b'page two')

    def test_report_includes_unassigned_chapters(self):
        (self.source / 'Test' / 'Ch. 99').mkdir()
        report = self.root / 'report.json'
        self.assertEqual(self.run_cli('plan', '--report', str(report)), 0)
        self.assertEqual(json.loads(report.read_text())[0]['unassignedChapters'], ['99'])

    def test_path_escape_and_empty_selection_rejected(self):
        self.series['outputFolder'] = '../escape'
        self.assertEqual(self.run_cli('build'), 2)
        self.assertEqual(self.run_cli('plan', '--series', 'Missing'), 2)

    def test_corrupt_page_count_rejected(self):
        target = self.root / 'bad.cbz'
        with zipfile.ZipFile(target, 'w') as z:
            z.writestr('1.jpg', b'image')
            z.writestr('ComicInfo.xml', '<ComicInfo><PageCount>2</PageCount></ComicInfo>')
        with self.assertRaisesRegex(ValueError, 'PageCount'):
            cbz.verify(target)

    def test_cover_download_validates_bytes_and_saves_provenance(self):
        from PIL import Image
        content = io.BytesIO()
        Image.new('RGB', (300, 450), 'blue').save(content, format='PNG')
        self.series['coverFolder'] = 'Test'
        self.series['volumes'][0]['coverUrl'] = 'https://publisher.example/cover'
        with patch.object(cbz.urllib.request, 'urlopen', return_value=io.BytesIO(content.getvalue())):
            self.assertEqual(self.run_cli('covers'), 0)
        cover = self.assets / 'covers/Test/v00.png'
        self.assertTrue(cover.is_file())
        record = json.loads(cover.with_suffix('.png.source.json').read_text())
        self.assertEqual((record['width'], record['height']), (300, 450))
        with patch.object(cbz.urllib.request, 'urlopen', side_effect=AssertionError('Should reuse cover')):
            self.assertEqual(self.run_cli('covers'), 0)

    def test_html_cover_is_rejected_without_publishing(self):
        self.series['coverFolder'] = 'Test'
        self.series['volumes'][0]['coverUrl'] = 'https://publisher.example/blocked.jpg'
        with patch.object(cbz.urllib.request, 'urlopen', return_value=io.BytesIO(b'<html>Blocked</html>')):
            self.assertEqual(self.run_cli('covers'), 2)
        self.assertFalse((self.assets / 'covers').exists())


if __name__ == '__main__':
    unittest.main()
