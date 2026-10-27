#!/usr/bin/env python3
"""Exercise the actual frozen engine, including its restricted image subprocess."""
import argparse
import datetime as dt
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
p=argparse.ArgumentParser();p.add_argument('--engine',default=str(ROOT/'macos/Veronica/Resources/VeronicaEngine/veronica-engine'));a=p.parse_args()
engine=Path(a.engine)
if not engine.is_file():raise SystemExit('Build the frozen engine before running release security tests')
subprocess.run([sys.executable,str(ROOT/'scripts/release_manifest.py'),'--check',str(engine)],check=True)
def run(*args,ok=True):
 r=subprocess.run([str(engine),*map(str,args)],capture_output=True,text=True,timeout=120)
 if ok:assert r.returncode==0,r.stdout+r.stderr
 return r
with tempfile.TemporaryDirectory(prefix='veronica-frozen-security-') as td:
 base=Path(td);media=base/'Media';state=base/'State';media.mkdir();source=media/'2023-01-01_photo.JPG'
 Image.new('RGB',(4000,3000),(100,60,30)).save(source,quality=95,exif=exif_date())
 stamp=dt.datetime(2023,1,1,12).timestamp();os.utime(source,(stamp,stamp))
 import hashlib
 digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
 original=digest(source)
 run('configure-optimization','--state-dir',state,'--image-format','jpeg','--image-max-megapixels','10','--jpeg-quality','70','--video-max-edge','1280','--audio-min-size-mb','10')
 run('plan','--root',media,'--state-dir',state,'--run-date','2026-10-15')
 plan=next(state.glob('plan-*.json'));payload=json.loads(plan.read_text());item=payload['items'][0];assert item['operation']=='CONVERT_IMAGE',item
 run('stage','--plan',plan,'--state-dir',state,'--max-images','1','--max-videos','0','--max-audio','0')
 with sqlite3.connect(state/'media-maintenance.sqlite') as con:sid,status=con.execute('SELECT staging_id,status FROM staging_items').fetchone()
 assert status=='STAGED_VERIFIED',status
 run('commit','--state-dir',state,'--staging-id',sid,'--relpath',item['relpath'],'--yes')
 with sqlite3.connect(state/'media-maintenance.sqlite') as con:cid,qpath=con.execute('SELECT commit_id,quarantine_path FROM commit_items').fetchone()
 assert digest(qpath)==original
 run('rollback','--state-dir',state,'--commit-id',cid,'--yes')
 assert digest(source)==original and source.name in os.listdir(media)
 # A forged frozen plan must fail before mutating the restored source.
 item['target']['final_relpath']='../outside.jpg';plan.write_text(json.dumps(payload))
 assert run('stage','--plan',plan,'--state-dir',state,'--max-images','1','--max-videos','0','--max-audio','0',ok=False).returncode!=0
 assert digest(source)==original and not (base/'outside.jpg').exists()
print('Frozen engine isolated image decoding, commit, rollback and plan integrity: PASS')
# The JPEG-first reader allowlist must also work for PNG in the packaged runtime.
with tempfile.TemporaryDirectory(prefix='veronica-frozen-png-') as td:
 base=Path(td);media=base/'Media';state=base/'State';media.mkdir();source=media/'2023-01-01_noise.png'
 Image.effect_noise((1200,1000),60).convert('RGB').save(source,exif=exif_date())
 stamp=dt.datetime(2023,1,1,12).timestamp();os.utime(source,(stamp,stamp));original=digest(source)
 run('plan','--root',media,'--state-dir',state,'--run-date','2026-10-16')
 plan=next(state.glob('plan-*.json'));payload=json.loads(plan.read_text());item=payload['items'][0]
 assert item['operation']=='CONVERT_IMAGE' and item['reason']=='image_recompress_at_original_dimensions',item
 run('stage','--plan',plan,'--state-dir',state,'--max-images','1','--max-videos','0','--max-audio','0')
 with sqlite3.connect(state/'media-maintenance.sqlite') as con:sid,status=con.execute('SELECT staging_id,status FROM staging_items').fetchone()
 assert status=='STAGED_VERIFIED',status
 run('commit','--state-dir',state,'--staging-id',sid,'--relpath',item['relpath'],'--yes')
 with sqlite3.connect(state/'media-maintenance.sqlite') as con:cid,qpath,fpath=con.execute('SELECT commit_id,quarantine_path,final_path FROM commit_items').fetchone()
 assert digest(qpath)==original
 with Image.open(fpath) as output:assert output.size==(1200,1000) and output.format=='JPEG'
 run('rollback','--state-dir',state,'--commit-id',cid,'--yes')
 assert digest(source)==original
print('Frozen PNG decoding, small-image recompression, commit and rollback: PASS')
