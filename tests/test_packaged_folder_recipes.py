#!/usr/bin/env python3
"""Exercise separate folder recipes through real conversion, commit and rollback."""
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
from PIL import Image
from fixture_dates import exif_date

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--engine',default=str(ROOT/'macos/Veronica/Resources/VeronicaEngine/veronica-engine'))
options=parser.parse_args()
engine=Path(options.engine)
if not engine.is_file():raise SystemExit('Build the frozen engine before running packaged folder recipe tests')
def run(*args):
    result=subprocess.run([str(engine),*map(str,args)],capture_output=True,text=True,timeout=180)
    assert result.returncode==0,result.stdout+result.stderr
    return result.stdout

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

with tempfile.TemporaryDirectory(prefix='veronica-packaged-folders-') as td:
    base=Path(td).resolve();state=base/'State';folders=[base/'Everyday photos',base/'Portfolio copies']
    for folder in folders:folder.mkdir()
    image=Image.effect_noise((4000,3000),60).convert('RGB')
    for folder in folders:
        path=folder/'2023-01-01_sample.png';image.save(path,exif=exif_date())
        stamp=dt.datetime(2023,1,1,12).timestamp();os.utime(path,(stamp,stamp))
    originals={str(folder):digest(folder/'2023-01-01_sample.png') for folder in folders}
    run('configure-folders','--state-dir',state,'--add',folders[0],'--add',folders[1])
    outputs=[]
    for folder,limit,fmt in zip(folders,(5,8),('jpeg','png')):
        payload=json.loads(run('folder-settings','--state-dir',state,'--folder',folder))
        recipe=payload['recipe'];recipe['optimization_settings']['image_max_megapixels']=limit
        recipe['optimization_settings']['image_output_format']=fmt
        payload=json.loads(run('configure-folder','--state-dir',state,'--folder',folder,'--recipe-json',json.dumps(recipe)))
        child=Path(payload['state_dir'])
        run('plan','--state-dir',child,'--root',folder,'--run-date','2026-10-16')
        plan=next(child.glob('plan-*.json'));item=json.loads(plan.read_text())['items'][0]
        assert item['operation']=='CONVERT_IMAGE' and item['target']['max_megapixels']==limit,item
        run('stage','--state-dir',child,'--plan',plan,'--max-images','1','--max-videos','0','--max-audio','0')
        with sqlite3.connect(child/'media-maintenance.sqlite') as con:
            sid,status=con.execute('SELECT staging_id,status FROM staging_items').fetchone()
        assert status=='STAGED_VERIFIED',status
        run('commit','--state-dir',child,'--staging-id',sid,'--relpath',item['relpath'],'--yes')
        with sqlite3.connect(child/'media-maintenance.sqlite') as con:
            cid,qpath,fpath=con.execute('SELECT commit_id,quarantine_path,final_path FROM commit_items').fetchone()
        assert digest(qpath)==originals[str(folder)]
        with Image.open(fpath) as converted:
            assert converted.format==('JPEG' if fmt=='jpeg' else 'PNG')
            assert abs(converted.width*converted.height/1_000_000-limit)<.03,converted.size
            outputs.append((converted.format,converted.size))
        run('rollback','--state-dir',child,'--commit-id',cid,'--yes')
        assert digest(folder/'2023-01-01_sample.png')==originals[str(folder)]
    assert outputs[0][1]!=outputs[1][1]
print('Packaged independent folder recipes, real JPEG/PNG conversion, commit and exact original rollback: PASS')
