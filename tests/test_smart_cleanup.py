#!/usr/bin/env python3
"""Good images/videos must complete beside damaged originals; savings must be real."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from PIL import Image
from fixture_dates import exif_date

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', type=Path, default=ROOT / 'veronica.py')
    engine = parser.parse_args().engine.resolve()
    prefix = [sys.executable, str(engine)] if engine.suffix == '.py' else [str(engine)]
    with tempfile.TemporaryDirectory(prefix='veronica-smart-cleanup-') as td:
        base = Path(td).resolve()
        media = base / 'Photos and video'
        state = base / 'Preferences'
        media.mkdir()
        for name in ('a-damaged.jpg', 'b-good.jpg', 'c-good.jpg'):
            Image.frombytes('RGB', (1400, 1000), os.urandom(1400*1000*3)).save(media/name, quality=100, subsampling=0, exif=exif_date())
        damaged = media/'a-damaged.jpg'
        damaged.write_bytes(damaged.read_bytes()[:damaged.stat().st_size//2])
        video = media/'clip.mp4'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i',
                        'testsrc2=size=1440x810:rate=24','-t','1.5','-c:v','libx264','-crf','5',
                        '-pix_fmt','yuv420p','-metadata','creation_time=2023-01-01T12:00:00Z',str(video)],check=True,timeout=60)
        before = {p.name: (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest()) for p in media.iterdir()}

        def run(command, *args):
            result = subprocess.run([*prefix,command,'--state-dir',str(state),*map(str,args)],
                                    capture_output=True,text=True,timeout=180)
            assert result.returncode == 0, result.stdout+result.stderr
            return json.loads(result.stdout) if result.stdout.startswith('{') else result.stdout

        run('configure-folders','--add',media)
        recipe = run('folder-settings','--folder',media)['recipe']
        recipe['date_scope'] = {'mode':'all','start':None,'end':None,'legacy':False}
        recipe['filename_policy']['enabled'] = False
        run('configure-folder','--folder',media,'--recipe-json',json.dumps(recipe))
        run('analyze-all')
        events = base/'events.jsonl'
        # A batch containing only the damaged image must make progress, then
        # proceed to later windows without a retry loop or blocking valid files.
        cleanup = run('annual-all','--yes','--image-batch','1','--events-jsonl',events)
        snapshot = run('ui-snapshot')
        assert snapshot['optimized_outputs'] == 3, (snapshot,cleanup)
        assert snapshot['renamed_outputs'] == 0
        assert snapshot['pending_staged_outputs'] == 0
        unreadable_page = run('scan-results','--search','a-damaged.jpg')
        assert unreadable_page['items'][0]['category'] == 'unchanged'
        assert 'couldn’t read' in unreadable_page['items'][0]['detail']
        assert damaged.stat().st_size == before[damaged.name][0]
        assert hashlib.sha256(damaged.read_bytes()).hexdigest() == before[damaged.name][1]
        for name in ('b-good.jpg','c-good.jpg','clip.mp4'):
            assert hashlib.sha256((media/name).read_bytes()).hexdigest() != before[name][1]
            assert (media/name).stat().st_size < before[name][0]
        actual_saving = sum(size-(media/name).stat().st_size for name,(size,_) in before.items())
        assert actual_saving == snapshot['total_saving_bytes'] and actual_saving > 0
        child = Path(snapshot['folder_settings'][0]['state_dir'])
        with sqlite3.connect(child/'media-maintenance.sqlite') as con:
            statuses = dict(con.execute('SELECT status,COUNT(*) FROM staging_items GROUP BY status'))
            assert statuses == {'SOURCE_UNREADABLE':1,'STAGED_VERIFIED':3}, statuses
            for relative, original_hash, quarantine in con.execute('SELECT relpath,source_original_sha256,quarantine_path FROM commit_items'):
                assert hashlib.sha256(Path(quarantine).read_bytes()).hexdigest() == before[relative][1] == original_hash
        report = next(child.glob('annual-*.md')).read_text()
        assert 'COMPLETE_WITH_SKIPPED_FILES' in report and 'unreadable_unchanged=1' in report
        rows=[json.loads(line) for line in events.read_text().splitlines()]
        assert sum(row.get('status')=='SOURCE_UNREADABLE' for row in rows)==1

        harness = base/'main.swift'
        harness.write_text('''import Foundation
let stopped = CleanupOutcome(completed: false, optimized: 0, renamed: 2, savedBytes: 0, unreadable: 0, kept: 0)
assert(stopped.title == "Cleanup stopped" && stopped.formattedSaving == "0 bytes")
let kept = CleanupOutcome(completed: true, optimized: 0, renamed: 0, savedBytes: 0, unreadable: 0, kept: 1)
assert(kept.title == "No space saved" && kept.subtitle.contains("originals were kept"))
let done = CleanupOutcome(completed: true, optimized: 3, renamed: 0, savedBytes: 500000, unreadable: 1, kept: 0)
assert(done.title == "Cleanup finished" && done.subtitle.contains("left unchanged"))
print("Honest stopped, zero-saving and skipped-file completion summaries: PASS")
''')
        executable=base/'summary-check'
        subprocess.run(['/usr/bin/swiftc',str(ROOT/'macos/Veronica/Sources/Models.swift'),str(harness),'-o',str(executable)],check=True,timeout=90)
        subprocess.run([str(executable)],check=True)
    print('Real image/video cleanup, unreadable-source isolation, exact savings and retained-original verification: PASS')


if __name__ == '__main__':
    main()
