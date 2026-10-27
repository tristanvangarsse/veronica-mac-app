#!/usr/bin/env python3
"""Real per-file date saves, source guards, payload preservation and fresh plans."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from PIL import Image, PngImagePlugin
from fixture_dates import exif_date
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import media_dates as dates
import media_maintenance as mm


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', type=Path, default=ROOT/'veronica.py')
    engine = parser.parse_args().engine.resolve()
    prefix = [sys.executable, str(engine)] if engine.suffix == '.py' else [str(engine)]
    with tempfile.TemporaryDirectory(prefix='veronica-manual-dates-') as td:
        base = Path(td).resolve(); media = base/'Photos'; media.mkdir(); state=base/'State'
        Image.new('RGB',(160,120),'blue').save(media/'missing.jpg')
        Image.new('RGB',(160,120),'orange').save(media/'dated.jpg', exif=exif_date('2022:03:04 15:30:10'))
        png=PngImagePlugin.PngInfo();png.add_text('Author','keep this author')
        Image.new('RGB',(160,120),'red').save(media/'graphic.png',pnginfo=png)
        (media/'notes.txt').write_text('Not media; do not edit')
        for ext in ('mp4','m4a','mp3','wav','aiff','flac'):
            source = ['-f','lavfi','-i','color=blue:size=160x120:rate=24','-t','0.3','-c:v','libx264'] if ext=='mp4' else ['-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','0.3']
            subprocess.run(['ffmpeg','-v','error',*source,'-metadata','title=Keep my title',str(media/('recording.'+ext))], check=True,timeout=30)
        for p in media.iterdir():os.utime(p,(1700000000,1700000000))
        subprocess.run(['/usr/bin/xattr','-w','com.apple.metadata:veronica-date-test','keep this attribute',str(media/'missing.jpg')],check=True)
        before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in media.iterdir()}
        stats={p.name:p.stat() for p in media.iterdir()}
        def run(command,*args,ok=True):
            r=subprocess.run([*prefix,command,'--state-dir',str(state),*map(str,args)],text=True,capture_output=True,timeout=180)
            assert (r.returncode==0)==ok,r.stdout+r.stderr
            return r
        run('configure-folders','--add',media)
        recipe=json.loads(run('folder-settings','--folder',media).stdout)['recipe']
        recipe['date_scope']={'mode':'all','start':None,'end':None,'legacy':False}
        run('configure-folder','--folder',media,'--recipe-json',json.dumps(recipe))
        run('analyze-all','--run-date','2026-10-26')
        snapshot=json.loads(run('ui-snapshot').stdout)
        child=Path(snapshot['folder_settings'][0]['state_dir'])
        def results():return json.loads(run('scan-results','--limit','200','--offset','0','--category','all','--search','').stdout)
        initial=results();items={i['relpath']:i for i in initial['items']}
        assert items['missing.jpg']['embedded_date'] is None and items['missing.jpg']['can_edit_date']
        assert not items['notes.txt']['can_edit_date']
        def save(item, day, ok=True):
            return run('set-file-date','--state-dir',child,'--plan',item['plan_path'],'--relpath',item['relpath'],'--date',day,'--yes',ok=ok)
        invalid=save(items['missing.jpg'],'2020-02-31',ok=False)
        assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in media.iterdir()}
        fingerprints={p.name:dates.content_identity(p) for p in media.iterdir() if p.suffix.lower() in dates.SUPPORTED}
        for name in sorted(fingerprints, key=lambda name: (name!='missing.jpg', name)):
            current={i['relpath']:i for i in results()['items']}
            saved=save(current[name],'2020-06-15')
            print(name + ': saved and verified', flush=True)
            assert dt.date(2020,6,15)==mm.audit.parse_embedded_date(dates.embedded(media/name)),name
            assert dates.content_identity(media/name)==fingerprints[name],name
            assert (media/name).stat().st_mtime_ns==stats[name].st_mtime_ns,name
            assert abs((media/name).stat().st_birthtime-stats[name].st_birthtime)<0.001,name
            latest={i['relpath']:i for i in results()['items']}
            assert latest[name]['embedded_date']=='2020-06-15',latest[name]
            if name=='missing.jpg':
                assert latest[name]['category']=='changes',latest[name]
                assert mm.audit._darwin_getxattr(media/name,'com.apple.metadata:veronica-date-test')==b'keep this attribute'
                for other,sha in before.items():
                    if other!=name:assert hashlib.sha256((media/other).read_bytes()).hexdigest()==sha,other
                # Old inspected state must not edit another file after this save.
                assert 'scan changed' in save(items['dated.jpg'],'2021-01-01',ok=False).stderr.lower()
        assert '15:30:10' in dates.embedded(media/'dated.jpg')
        with Image.open(media/'graphic.png') as image:assert image.info['Author']=='keep this author'
        with sqlite3.connect(child/'media-maintenance.sqlite') as con:
            rows=con.execute("SELECT source_original_sha256,quarantine_path FROM commit_items WHERE operation='SET_EMBEDDED_DATE'").fetchall()
            assert len(rows)==len(fingerprints)
            for sha,path in rows:assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha
        # New dates remain available to normal cleanup; a date save is not a
        # terminal optimization disposition.
        assert not mm.already_committed_relpaths(child/'media-maintenance.sqlite')
        current={i['relpath']:i for i in results()['items']}
        (media/'missing.jpg').write_bytes((media/'missing.jpg').read_bytes()+b'changed externally')
        changed=hashlib.sha256((media/'missing.jpg').read_bytes()).hexdigest()
        save(current['missing.jpg'],'2021-01-01',ok=False)
        assert hashlib.sha256((media/'missing.jpg').read_bytes()).hexdigest()==changed
        # Force a planner failure after installation and prove the journal
        # restores the exact original instead of leaving a partially saved edit.
        if engine.suffix == '.py':
            from unittest.mock import patch
            run('analyze-all','--run-date','2026-10-26')
            current={i['relpath']:i for i in results()['items']}
            inspected=current['dated.jpg']
            original=(media/'dated.jpg').read_bytes()
            with patch.object(mm.cmd_plan, '__wrapped__', side_effect=RuntimeError('injected planner failure')):
                try:
                    mm.cmd_set_file_date(argparse.Namespace(state_dir=str(child), plan=inspected['plan_path'], relpath='dated.jpg', date='2021-04-05', yes=True))
                except RuntimeError as error:
                    assert 'injected' in str(error)
                else:raise AssertionError('The forced failure should not report a successful save')
            assert (media/'dated.jpg').read_bytes()==original
            assert not list((child/'transactions').glob('*.json'))
        print('Per-file embedded dates: real image/video/audio saves, exact content, filesystem dates, attributes, fresh plans and stale-source guards: PASS')
if __name__=='__main__':main()
