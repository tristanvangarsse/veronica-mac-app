#!/usr/bin/env python3
"""Exercise real capture metadata and strict missing-date review through the CLI."""
import argparse
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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import media_audit as audit
import media_maintenance as mm


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--engine',type=Path,default=ROOT/'veronica.py')
    engine=parser.parse_args().engine.resolve()
    prefix=[sys.executable,str(engine)] if engine.suffix=='.py' else [str(engine)]
    with tempfile.TemporaryDirectory(prefix='veronica-embedded-dates-') as td:
        base=Path(td).resolve();media=base/'Photos';folder=media/'1999';folder.mkdir(parents=True)
        state=base/'State'
        photo=folder/'2001-01-01_photo.jpg'
        exif=exif_date('2023:06:15 10:30:00');exif[306]='2026:10:26 15:00:00'
        Image.new('RGB',(100,80),'orange').save(photo,exif=exif)
        missing=folder/'2001-01-01_missing.jpg'
        Image.new('RGB',(100,80),'blue').save(missing)
        invalid=folder/'2001-01-01_invalid.jpg'
        Image.new('RGB',(100,80),'green').save(invalid,exif=exif_date('not a date'))
        png=folder/'2001-01-01_graphic.png'
        text=PngImagePlugin.PngInfo();text.add_text('Creation Time','2022-03-04T12:00:00Z')
        text.add_itxt('XML:com.adobe.xmp','<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:CreateDate="invalid" xmp:Label="keep-me"/></rdf:RDF></x:xmpmeta>')
        Image.frombytes('RGB',(1200,1000),os.urandom(1200*1000*3)).save(png,pnginfo=text)
        video=folder/'2001-01-01_clip.mp4'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i',
                        'color=blue:size=320x240:rate=24','-t','0.5','-c:v','libx264',
                        '-metadata','creation_time=2023-04-05T23:30:00Z',str(video)],check=True,timeout=60)
        audio=folder/'2001-01-01_recording.wav'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i',
                        'sine=frequency=1000:sample_rate=44100','-t','0.5','-metadata',
                        'date=2022-05-06',str(audio)],check=True,timeout=60)
        for path in folder.iterdir():os.utime(path,(1767225600,1767225600))
        before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}

        def run(command,*args,ok=True):
            result=subprocess.run([*prefix,command,'--state-dir',str(state),*map(str,args)],capture_output=True,text=True,timeout=120)
            if ok:assert result.returncode==0,result.stdout+result.stderr
            else:assert result.returncode!=0,result.stdout
            return result
        run('configure-folders','--add',media)
        recipe=json.loads(run('folder-settings','--folder',media).stdout)['recipe']
        recipe['filename_policy']['date_format']='YYYY-MM-DD_'
        recipe['date_scope']={'mode':'all','start':None,'end':None,'legacy':False}
        run('configure-folder','--folder',media,'--recipe-json',json.dumps(recipe))
        run('analyze-all','--run-date','2026-10-26')
        snap=json.loads(run('ui-snapshot').stdout)
        child=Path(snap['folder_settings'][0]['state_dir'])
        path=next(child.glob('plan-*.json'));plan=json.loads(path.read_text())
        items={Path(item['relpath']).name:item for item in plan['items']}
        for name,date in ((photo.name,'2023-06-15'),(png.name,'2022-03-04'),
                          (video.name,'2023-04-05'),(audio.name,'2022-05-06')):
            item=items[name]
            assert item['target']['filename_date']==date,item
            assert Path(item['target']['final_relpath']).name.startswith(date+'_'),item
        for name in (missing.name,invalid.name):
            assert items[name]['operation']=='REVIEW' and items[name]['reason']=='embedded_date_missing',items[name]
            assert not items[name]['executable'] and not items[name]['target'].get('final_relpath')
        assert plan['config_snapshot']['date_evidence_policy']=='embedded_only'
        run('stage','--state-dir',child,'--plan',path,'--max-images','10','--max-videos','0','--max-audio','0')
        with sqlite3.connect(child/'media-maintenance.sqlite') as con:
            output,verification=con.execute('SELECT output_path,verification_json FROM staging_items WHERE relpath=?',(items[png.name]['relpath'],)).fetchone()
        assert json.loads(verification)['embedded_date_preserved'] is True
        assert audit.probe_image(Path(output))['embedded_creation_time']=='2022-03-04T12:00:00Z'
        with Image.open(output) as converted:
            assert b'keep-me' in converted.info['xmp']

        # The review cannot be bypassed by switching to All dates or choosing a
        # previous generic date override. The user explicitly requested review.
        refused=run('resolve-review','--state-dir',child,'--plan',path,'--relpath',items[missing.name]['relpath'],
                    '--resolution','PROCESS_NORMALLY','--yes',ok=False)
        assert refused.returncode!=0
        for mode in ('older_than_two_years','within','outside'):
            recipe['date_scope']={'mode':mode,'start':'2022-01-01' if mode in ('within','outside') else None,
                                 'end':'2023-12-31' if mode in ('within','outside') else None,'legacy':False}
            run('configure-folder','--folder',media,'--recipe-json',json.dumps(recipe))
            run('analyze-all','--run-date','2026-10-26')
            with sqlite3.connect(child/'media-maintenance.sqlite') as con:
                latest=con.execute('SELECT plan_id FROM plans ORDER BY created_at DESC LIMIT 1').fetchone()[0]
            current=json.loads(next(child.glob('plan-*-'+latest[:12]+'.json')).read_text())
            assert all(item['reason']=='embedded_date_missing' for item in current['items'] if Path(item['relpath']).name in (missing.name,invalid.name))
        assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
        # Photo DateTimeOriginal takes priority over generic editing timestamps.
        assert audit.probe_image(photo)['embedded_creation_time']=='2023:06:15 10:30:00'
        # A legitimately registered plan from the old date policy must require
        # a fresh scan, even if its hash and source bytes are otherwise valid.
        old=json.loads(json.dumps(plan));old['config_snapshot'].pop('date_evidence_policy')
        old['plan_id']=mm.sha256_text(mm.canonical_json({k:v for k,v in old.items() if k not in ('plan_id','created_at')}))
        legacy_path=child/'legacy-date-plan.json';legacy_path.write_text(json.dumps(old))
        with sqlite3.connect(child/'media-maintenance.sqlite') as con:
            con.row_factory=sqlite3.Row
            registered=dict(con.execute('SELECT * FROM plans WHERE plan_id=?',(plan['plan_id'],)).fetchone())
            registered.update(plan_id=old['plan_id'],plan_sha256=mm.sha256_text(mm.canonical_json(old)))
            con.execute('INSERT INTO plans ('+','.join(registered)+') VALUES ('+','.join('?' for _ in registered)+')',tuple(registered.values()))
        rejected=run('stage','--state-dir',child,'--plan',legacy_path,'--max-images','1','--max-videos','0',ok=False)
        assert 'embedded-date policy' in rejected.stderr,rejected.stderr
        assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
        source=base/'main.swift'
        source.write_text('''import Foundation
let item = ReviewItem(root: "/tmp", stateDir: "/tmp/state", relpath: "file.jpg", reason: "embedded_date_missing", sourceSize: 100, planPath: nil)
assert(item.title.lowercased().contains("date") && !item.canProcessNormally)
assert(item.explanation.contains("left unchanged") && item.explanation.contains("will not guess"))
print("Missing embedded dates cannot be approved for normal processing: PASS")
''')
        binary=base/'check'
        subprocess.run(['/usr/bin/swiftc',str(ROOT/'macos/Veronica/Sources/Models.swift'),str(source),'-o',str(binary)],check=True,timeout=90)
        subprocess.run([str(binary)],check=True)
    print('Real EXIF/PNG/video/audio dates, conflicting names/folders, missing-date review in every date scope and unchanged sources: PASS')


if __name__=='__main__':main()
