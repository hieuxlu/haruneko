#!/usr/bin/env python3
"""Package chapter folders or chapter CBZs using portable volume settings (Python 3.10+)."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif'}


def natural(value):
    return [(1, int(s)) if s.isdigit() else (0, s.casefold())
            for s in re.split(r'(\d+)', str(value))]


def number(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f'Invalid chapter number: {value}') from exc
    if not result.is_finite():
        raise ValueError(f'Invalid chapter number: {value}')
    return result


def label(value):
    return format(number(value), 'f').rstrip('0').rstrip('.') if number(value) % 1 else str(int(number(value)))


def expand(pattern, **values):
    # Support existing PowerShell {volume:00} as well as Python {volume:02d}.
    pattern = re.sub(r'\{(\w+):(0+)\}', lambda m: '{' + m[1] + ':0' + str(len(m[2])) + 'd}', pattern)
    return pattern.format(**values)


def within(root, relative):
    """Configuration paths are relative and cannot escape their chosen root."""
    root = Path(root).resolve()
    result = (root / relative).resolve()
    if not result.is_relative_to(root):
        raise ValueError(f'Path escapes root {root}: {relative}')
    return result


def load_config(path):
    config = json.loads(Path(path).read_text(encoding='utf-8-sig'), parse_float=Decimal)
    series_list = config.get('series')
    if not isinstance(series_list, list) or not series_list:
        raise ValueError('Config must contain a nonempty series list')
    if set(config.get('imageExtensions', EXTENSIONS)) - EXTENSIONS:
        raise ValueError('imageExtensions contains an unsupported image format')
    titles = set()
    for series in series_list:
        title = series['title']
        if title in titles:
            raise ValueError(f'Duplicate series: {title}')
        titles.add(title)
        seen_volumes, assigned = set(), set()
        if int(series.get('minImagesPerChapter', 1)) < 1:
            raise ValueError(f'{title}: minImagesPerChapter must be positive')
        for volume in series['volumes']:
            v = volume['volume']
            if isinstance(v, bool) or number(v) % 1 or number(v) < 0:
                raise ValueError(f'{title}: volume must be a nonnegative integer')
            if v in seen_volumes:
                raise ValueError(f'{title}: duplicate volume {v}')
            seen_volumes.add(v)
            chapters, _ = volume_chapters(volume)
            overlap = assigned.intersection(chapters)
            if overlap:
                raise ValueError(f'{title}: chapters assigned to multiple volumes: {sorted(overlap)}')
            assigned.update(chapters)
    return config


def volume_chapters(volume):
    if 'chapters' in volume:
        if 'firstChapter' in volume or 'lastChapter' in volume:
            raise ValueError('Use chapters OR firstChapter/lastChapter')
        required = [number(c) for c in volume['chapters']]
    else:
        first, last = number(volume['firstChapter']), number(volume['lastChapter'])
        if first % 1 or last % 1 or first > last:
            raise ValueError('Chapter ranges must have ordered integer endpoints; use chapters for decimals')
        required = [Decimal(c) for c in range(int(first), int(last) + 1)]
    required += [number(c) for c in volume.get('additionalChapters', [])]
    optional = [number(c) for c in volume.get('optionalChapters', [])]
    all_chapters = required + optional
    if not all_chapters or len(set(all_chapters)) != len(all_chapters):
        raise ValueError(f'Empty or duplicate chapter selection in volume {volume["volume"]}')
    return (all_chapters if 'chapters' in volume else sorted(all_chapters)), set(optional)


@dataclass
class Page:
    source: Path
    member: str | None = None

    @property
    def suffix(self):
        return Path(self.member or self.source.name).suffix.lower()

    def write(self, archive, name):
        if self.member is None:
            archive.write(self.source, name)
        else:
            with zipfile.ZipFile(self.source) as chapter:
                with chapter.open(self.member) as src, archive.open(name, 'w', force_zip64=True) as dst:
                    shutil.copyfileobj(src, dst)


def chapter_pages(path, extensions):
    if path.is_dir():
        return [Page(p) for p in sorted(path.rglob('*'), key=lambda p: natural(p.relative_to(path)))
                if p.is_file() and p.suffix.lower() in extensions]
    if path.is_file() and path.suffix.lower() in {'.cbz', '.zip'}:
        with zipfile.ZipFile(path) as archive:
            names = [i.filename for i in archive.infolist()
                     if not i.is_dir() and Path(i.filename).suffix.lower() in extensions]
            if len(names) != len(set(names)):
                raise ValueError(f'Duplicate page names in {path}')
            if archive.testzip():
                raise ValueError(f'CRC failure: {path}')
        return [Page(path, name) for name in sorted(names, key=natural)]
    return []


def cover_path(series, volume, assets_root):
    relative = volume.get('cover')
    if relative:
        return within(assets_root, relative)
    if series.get('coverFolder'):
        folder = within(assets_root, 'covers/' + series['coverFolder'])
        matches = sorted(p for p in folder.glob(f'v{int(volume["volume"]):02d}.*')
                         if p.suffix.lower() in EXTENSIONS and p.is_file())
        if len(matches) > 1:
            raise ValueError(f'Ambiguous cover for volume {volume["volume"]}: {matches}')
        return matches[0] if matches else folder / f'v{int(volume["volume"]):02d}.jpg'
    return None


def selected(config, args):
    found = []
    for series in config['series']:
        if args.series and series['title'] not in args.series and series.get('folder') not in args.series:
            continue
        for volume in series['volumes']:
            if args.volume is None or int(volume['volume']) in args.volume:
                found.append((series, volume))
    if not found:
        raise ValueError('No series/volumes matched the selection')
    if args.series:
        names = {s['title'] for s, _ in found} | {s.get('folder') for s, _ in found}
        if set(args.series) - names:
            raise ValueError('Some requested series did not match')
    if args.volume and set(args.volume) - {int(v['volume']) for _, v in found}:
        raise ValueError('Some requested volumes did not match')
    return found


def make_plan(config, args):
    plans, targets = [], set()
    extensions = {e.lower() for e in config.get('imageExtensions', EXTENSIONS)}
    for series, volume in selected(config, args):
        source = within(args.root, series.get('folder', series['title']))
        chapters, optional = volume_chapters(volume)
        pages, included = [], []
        problems = list(volume.get('knownIssues', []))
        pattern = series.get('chapterFolderPattern', 'Ch. {chapter}')
        for c in chapters:
            chapter = within(source, expand(pattern, chapter=label(c)))
            images = chapter_pages(chapter, extensions)
            if len(images) < int(series.get('minImagesPerChapter', 1)):
                if c not in optional or images:
                    problems.append(f'Chapter {label(c)}: {len(images)} pages (minimum {series.get("minImagesPerChapter", 1)})')
                continue
            included.append(label(c))
            for i, page in enumerate(images, 1):
                pages.append((f'c{len(included):04d}_ch{label(c)}_p{i:05d}{page.suffix}', page))
        cover = cover_path(series, volume, args.assets_root)
        has_cover = bool(cover and cover.is_file())
        if has_cover:
            if cover.suffix.lower() not in EXTENSIONS:
                raise ValueError(f'Unsupported cover extension: {cover}')
            pages.insert(0, ('000_cover' + cover.suffix.lower(), Page(cover)))
        elif series.get('requireCover', True):
            problems.append(f'Missing cover: {cover or "not configured"}')
        name = expand(series.get('outputFilePattern', '{title} v{volume:02d}.cbz'),
                      title=series['title'], volume=int(volume['volume']))
        # Replace Windows-invalid filename characters on every platform.
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', ' -', name).rstrip(' .')
        if not name.lower().endswith('.cbz'):
            raise ValueError('outputFilePattern must end in .cbz')
        if problems:
            name = name[:-4] + '.incomplete.cbz'
        target = within(args.output, series.get('outputFolder', 'CBZ/' + series['title'])) / name
        if any(target == page.source.resolve() for _, page in pages):
            raise ValueError(f'Output would overwrite an input: {target}')
        if target in targets:
            raise ValueError(f'Duplicate output path: {target}')
        targets.add(target)
        row = dict(series=series['title'], volume=int(volume['volume']),
                   expected=[label(c) for c in chapters], included=included,
                   problems=problems, pages=len(pages), cover=str(cover) if has_cover else None,
                   target=str(target), exists=target.exists(),
                   status='ABSENT' if not included else 'PARTIAL' if problems else 'READY')
        # Inventory against the full settings, even when building selected volumes.
        assigned = {c for v in series['volumes'] for c in volume_chapters(v)[0]}
        matcher = re.escape(pattern).replace(re.escape('{chapter}'), r'(?P<chapter>-?\d+(?:\.\d+)?)')
        unassigned = []
        if source.is_dir() and '{chapter}' in pattern:
            for child in source.iterdir():
                match = re.fullmatch(matcher, child.name)
                if match and number(match['chapter']) not in assigned:
                    unassigned.append(match['chapter'])
        row['unassignedChapters'] = sorted(unassigned, key=number)
        plans.append((row, pages, series, volume))
    return plans


def comic_info(row, series, volume):
    root = ET.Element('ComicInfo')
    fields = {'Title': volume.get('title', f'Volume {row["volume"]:02d}'),
              'Series': series['title'], 'Number': row['volume'],
              'PageCount': row['pages'], 'LanguageISO': series.get('language', 'en'),
              'Manga': series.get('manga', 'YesAndRightToLeft')}
    if series.get('volumeCount') is not None:
        fields['Count'] = series['volumeCount']
    for source, dest in [('writer', 'Writer'), ('artist', 'Penciller'),
                         ('publisher', 'Publisher'), ('genre', 'Genre'),
                         ('summary', 'Summary'), ('year', 'Year'), ('isbn', 'GTIN'),
                         ('web', 'Web')]:
        value = volume.get(source, series.get(source))
        if value is not None:
            fields[dest] = value
    if row['problems']:
        fields['Notes'] = 'INCOMPLETE: ' + '; '.join(row['problems'])
    for key, value in fields.items():
        ET.SubElement(root, key).text = str(value)
    if row['cover']:
        ET.SubElement(ET.SubElement(root, 'Pages'), 'Page', Image='0', Type='FrontCover')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def verify(path, expected=None):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError(f'Duplicate ZIP entries: {path}')
        bad = archive.testzip()
        if bad:
            raise ValueError(f'CRC failure: {path}: {bad}')
        info = ET.fromstring(archive.read('ComicInfo.xml'))
        images = [n for n in names if Path(n).suffix.lower() in EXTENSIONS]
        if not images or int(info.findtext('PageCount', '-1')) != len(images):
            raise ValueError(f'PageCount mismatch or empty archive: {path}')
        if expected is not None and names != expected + ['ComicInfo.xml']:
            raise ValueError(f'Archive entries/order mismatch: {path}')
        for page in info.findall('Pages/Page'):
            index = int(page.attrib['Image'])
            if not 0 <= index < len(images):
                raise ValueError(f'Invalid page reference: {path}')
            if (page.get('Type') == 'FrontCover' and any(n.startswith('000_cover') for n in images)
                    and not images[index].startswith('000_cover')):
                raise ValueError(f'Cover reference does not match cover entry: {path}')
    return len(images)


def publish(temp, target, force):
    if force:
        os.replace(temp, target)
    else:
        # Exclusive publication: a racing process cannot be overwritten.
        os.link(temp, target)
        temp.unlink()


def build(plan, force=False):
    row, pages, series, volume = plan
    target = Path(row['target'])
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + target.name + '.', suffix='.tmp', dir=target.parent)
    os.close(fd)
    temp = Path(name)
    try:
        with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for entry, page in pages:
                page.write(archive, entry)
            archive.writestr('ComicInfo.xml', comic_info(row, series, volume))
        verify(temp, [entry for entry, _ in pages])
        publish(temp, target, force)
    finally:
        temp.unlink(missing_ok=True)


def fetch_covers(config, args):
    # Pillow validates actual image bytes, not HTTP headers or URL extensions.
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError('Cover downloads need Pillow: python -m pip install Pillow') from exc
    records = []
    for series, volume in selected(config, args):
        target = cover_path(series, volume, args.assets_root)
        url = volume.get('coverUrl')
        if target and target.exists():
            with Image.open(target) as image:
                image.verify()
            print(f'Existing cover: {target}')
            continue
        if not url:
            print(f'No coverUrl: {series["title"]} v{volume["volume"]}')
            continue
        if target is None:
            raise ValueError('coverUrl needs cover or coverFolder to select a destination')
        if not url.startswith(('https://', 'http://')):
            raise ValueError(f'Cover URL must be HTTP(S): {url}')
        request = urllib.request.Request(url, headers={'User-Agent': 'Haruneko-CBZ/1.0'})
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read(25 * 1024 * 1024 + 1)
        if len(content) > 25 * 1024 * 1024:
            raise ValueError(f'Cover exceeds 25 MiB: {url}')
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            width, height = image.size
            suffix = { 'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 'GIF': '.gif' }.get(image.format)
        if not suffix or width < args.min_width or height < args.min_height:
            raise ValueError(f'Unsupported or too small cover: {url} ({width}x{height})')
        # Explicit file paths must match their bytes; inferred paths use the detected format.
        if volume.get('cover') and target.suffix.lower().replace('.jpeg', '.jpg') != suffix:
            raise ValueError(f'Cover bytes are {suffix}; update configured path: {target}')
        if not volume.get('cover'):
            target = target.with_suffix(suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.' + target.name, suffix='.tmp', dir=target.parent)
        temp = Path(name)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
            publish(temp, target, False)
        finally:
            temp.unlink(missing_ok=True)
        record = dict(series=series['title'], volume=volume['volume'], file=str(target),
                      url=url, width=width, height=height)
        records.append(record)
        # One provenance sidecar per image survives interrupted or filtered runs.
        target.with_suffix(target.suffix + '.source.json').write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'Downloaded: {target} ({width}x{height})')
    return records


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest='command', required=True)
    for command in ('plan', 'build', 'covers'):
        p = sub.add_parser(command)
        p.add_argument('--config', type=Path, required=True)
        p.add_argument('--root', type=Path, default=Path.cwd(), help='Source manga root (default: current directory)')
        p.add_argument('--output', type=Path, help='Root for outputFolder (default: source root)')
        p.add_argument('--assets-root', type=Path, help='Root for cover paths (default: config directory)')
        p.add_argument('--series', nargs='+')
        p.add_argument('--volume', nargs='+', type=int)
        p.add_argument('--report', type=Path, help='Write JSON report to this explicit destination')
        if command == 'build':
            p.add_argument('--allow-partial', action='store_true')
            p.add_argument('--force', action='store_true', help='Atomically replace existing output archives')
        if command == 'covers':
            p.add_argument('--min-width', type=int, default=200)
            p.add_argument('--min-height', type=int, default=300)
    p = sub.add_parser('verify')
    p.add_argument('paths', type=Path, nargs='+', help='CBZ files or directories (recursive)')
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'verify':
            paths = sorted({p for entry in args.paths for p in
                            (entry.rglob('*.cbz') if entry.is_dir() else [entry])})
            if not paths:
                raise ValueError('No CBZ archives found')
            for path in paths:
                print(f'Verified: {path} ({verify(path)} pages)')
            return 0
        args.output = args.output or args.root
        args.assets_root = args.assets_root or args.config.resolve().parent
        config = load_config(args.config)
        if args.command == 'covers':
            rows = fetch_covers(config, args)
            result = 0
        else:
            plans = make_plan(config, args)
            rows = [p[0] for p in plans]
            result = 0
            # Check all conflicts before building any archives.
            if args.command == 'build' and not args.force:
                conflicts = [r['target'] for r in rows if r['exists']]
                if conflicts:
                    raise FileExistsError('Output exists; use --force to replace: ' + ', '.join(conflicts))
            for plan in plans:
                row = plan[0]
                print(f'{row["status"]}: {row["series"]} v{row["volume"]:02d}: '
                      f'{len(row["included"])}/{len(row["expected"])} chapters, {row["pages"]} pages')
                for problem in row['problems']:
                    print('  ' + problem)
                if row['unassignedChapters']:
                    print('  Unassigned local chapters: ' + ', '.join(row['unassignedChapters']))
                if row['status'] == 'ABSENT' or (row['problems'] and not getattr(args, 'allow_partial', False)):
                    result = 1
                    continue
                if args.command == 'build':
                    build(plan, args.force)
                    row['status'] = 'BUILT_PARTIAL' if row['problems'] else 'BUILT'
                    print(f'Verified and created: {row["target"]}')
        if args.report:
            args.report.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
        return result
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile, ET.ParseError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
