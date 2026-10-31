#!/usr/bin/env python3
"""Review every scan decision across folders, with frozen recipes and bounded pages."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from PIL import Image
from fixture_dates import exif_date

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='veronica-result-pages-') as td:
        base = Path(td).resolve()
        state = base / 'State'
        folders = [base / 'Photos', base / 'Other photos']
        for folder in folders:
            folder.mkdir()
        for index in range(24):
            Image.new('RGB', (40, 30), (index * 8, 80, 120)).save(folders[0] / f'photo-{index:03}.jpg', exif=exif_date())
        for index in range(90):
            (folders[0] / f'note-{index:03}.txt').write_text('Keep this document unchanged.')
        Image.new('RGB', (50, 30), (60, 100, 150)).save(folders[1] / 'special.jpg', exif=exif_date())
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for folder in folders for p in folder.iterdir()}

        def run(*args, success=True):
            result = subprocess.run([sys.executable, str(ROOT / 'veronica.py'), *map(str, args), '--state-dir', str(state)],
                                    text=True, capture_output=True, timeout=120)
            if success:
                assert result.returncode == 0, result.stdout + result.stderr
                return json.loads(result.stdout) if result.stdout.startswith('{') else result.stdout
            assert result.returncode != 0, result.stdout
            return result.stdout + result.stderr

        run('configure-folders', '--add', folders[0], '--add', folders[1])
        snapshot = run('ui-snapshot')
        assert snapshot['latest_plan'] is None, 'Adding folders must not scan them'
        for folder, quality, pixels in [(folders[0], 70, 10), (folders[1], 84, 7)]:
            settings = run('folder-settings', '--folder', folder)
            recipe = settings['recipe']
            recipe['date_scope'] = {'mode': 'all', 'start': None, 'end': None, 'legacy': False}
            recipe['filename_policy']['enabled'] = False
            recipe['optimization_settings']['jpeg_quality'] = quality
            recipe['optimization_settings']['image_max_megapixels'] = pixels
            run('configure-folder', '--folder', folder, '--recipe-json', json.dumps(recipe))
        run('analyze-all')
        snapshot = run('ui-snapshot')
        scan_id = snapshot['latest_plan']['plan_id']
        first = run('scan-results', '--scan-id', scan_id, '--limit', 100)
        assert first['total'] == 115 and len(first['items']) == 100, first
        second = run('scan-results', '--scan-id', scan_id, '--offset', 100, '--limit', 100)
        all_items = first['items'] + second['items']
        assert len(all_items) == 115
        assert len({(x['root'], x['relpath']) for x in all_items}) == 115
        assert first['counts'] == {'all': 115, 'changes': 25, 'review': 0, 'unchanged': 90}, first['counts']
        changes = run('scan-results', '--category', 'changes')
        assert changes['total'] == 25
        assert all(x['category'] == 'changes' for x in changes['items'])
        photo = next(x for x in changes['items'] if x['root'] == str(folders[0]))
        special = next(x for x in changes['items'] if x['root'] == str(folders[1]))
        assert 'quality 70' in photo['detail'] and '10 MP' in photo['detail'], photo
        assert 'quality 84' in special['detail'] and '7 MP' in special['detail'], special
        assert 'verification' in photo['detail']
        focused = run('scan-results', '--focus-root', folders[1], '--focus-relpath', 'special.jpg')
        assert focused['offset'] == 100 and any(x['relpath']=='special.jpg' for x in focused['items'])
        search = run('scan-results', '--search', 'SPECIAL.JPG')
        assert search['total'] == 1 and search['items'][0]['relpath'] == 'special.jpg'
        unchanged = run('scan-results', '--category', 'unchanged', '--limit', 7)
        assert unchanged['total'] == 90 and len(unchanged['items']) == 7
        assert all(x['detail'].startswith('Leave unchanged') for x in unchanged['items'])
        assert 'scan changed' in run('scan-results', '--scan-id', 'wrong-id', success=False)
        run('scan-results', '--limit', 201, success=False)
        run('scan-results', '--offset', -1, success=False)

        # Decode the real CLI response using the exact app models.
        payload = base / 'page.json'; payload.write_text(json.dumps(first))
        source = base / 'main.swift'
        source.write_text('''import Foundation
let page = try JSONDecoder().decode(ScanResultsPage.self, from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
assert(page.items.count == 100 && page.total == 115)
assert(page.counts["changes"] == 25)
assert(page.items.contains { $0.actionTitle == "Optimize image" })
assert(page.items.contains { $0.actionTitle == "Keep unchanged" })
print("Swift full scan results contract: PASS")
''')
        subprocess.run(['/usr/bin/swiftc', str(ROOT / 'macos/Veronica/Sources/Models.swift'), str(source), '-o', str(base / 'contract')], check=True, timeout=90)
        subprocess.run([str(base / 'contract'), str(payload)], check=True)

        recipe = run('folder-settings', '--folder', folders[0])['recipe']
        recipe['optimization_settings']['jpeg_quality'] = 80
        run('configure-folder', '--folder', folders[0], '--recipe-json', json.dumps(recipe))
        assert 'Scan folders again' in run('scan-results', '--scan-id', scan_id, success=False)
        run('analyze-all')
        assert 'scan changed' in run('scan-results', '--scan-id', scan_id, success=False)
        after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for folder in folders for p in folder.iterdir()}
        assert before == after, 'Scanning and reviewing must leave every source unchanged'

        # Missing dates in readable media can be repaired. Empty/unreadable
        # media must not invite a date write which cannot succeed safely.
        (folders[0] / 'empty.jpg').write_bytes(b'')
        (folders[0] / 'unreadable.jpg').write_bytes(b'Generated invalid image')
        Image.new('RGB', (40, 30), 'purple').save(folders[0] / 'undated.jpg')
        review_sources = {p.name: p.read_bytes() for p in folders[0].glob('*.jpg')}
        run('analyze-all')
        review = {x['relpath']: x for x in run('scan-results', '--category', 'review')['items']}
        assert review['empty.jpg']['reason'] == 'empty_file' and not review['empty.jpg']['can_edit_date']
        assert review['unreadable.jpg']['reason'] == 'media_probe_failed' and not review['unreadable.jpg']['can_edit_date']
        assert review['undated.jpg']['reason'] == 'embedded_date_missing' and review['undated.jpg']['can_edit_date']
        assert review_sources == {p.name: p.read_bytes() for p in folders[0].glob('*.jpg')}
    print('Full scan results, pagination, independent recipes, stale-plan rejection and read-only review: PASS')


if __name__ == '__main__':
    main()
