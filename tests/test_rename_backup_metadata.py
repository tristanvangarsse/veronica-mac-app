#!/usr/bin/env python3
"""Rename-only originals must retain their macOS attributes through rollback."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import sqlite3
import subprocess
import sys
import tempfile
from PIL import Image
from fixture_dates import exif_date
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import media_audit as audit


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--engine',type=Path,default=ROOT/'veronica.py')
    engine=parser.parse_args().engine.resolve()
    prefix=[sys.executable,str(engine)] if engine.suffix=='.py' else [str(engine)]
    with tempfile.TemporaryDirectory(prefix='veronica-rename-metadata-') as td:
        base=Path(td).resolve();media=base/'Media';state=base/'State';media.mkdir()
        source=media/'personal photograph.JPG'
        Image.new('RGB',(100,100),'blue').save(source,exif=exif_date())
        attributes={
            'com.apple.metadata:_kMDItemUserTags':plistlib.dumps(['Personal\n6','Important\n1'],fmt=plistlib.FMT_BINARY),
            'com.apple.metadata:kMDItemFinderComment':plistlib.dumps('Keep this comment',fmt=plistlib.FMT_BINARY),
            'com.apple.ResourceFork':b'original resource fork\x00\x01\x02'
        }
        for key,value in attributes.items():
            subprocess.run(['/usr/bin/xattr','-wx',key,value.hex(),str(source)],check=True)
        original=hashlib.sha256(source.read_bytes()).hexdigest();stat=source.stat()
        cfg=base/'config.json';cfg.write_text(json.dumps({'recompress_images_below_target':False}))
        def run(command,*args):
            result=subprocess.run([*prefix,command,'--state-dir',str(state),*map(str,args)],text=True,capture_output=True,timeout=90)
            assert result.returncode==0,result.stdout+result.stderr
            return result
        run('plan','--root',media,'--config',cfg,'--run-date','2026-10-26')
        frozen=next(state.glob('plan-*.json'));plan=json.loads(frozen.read_text());item=plan['items'][0]
        assert item['operation']=='RENAME',item
        run('commit-rename','--plan',frozen,'--relpath',item['relpath'],'--yes')
        with sqlite3.connect(state/'media-maintenance.sqlite') as con:
            cid,backup,final=con.execute('SELECT commit_id,quarantine_path,final_path FROM commit_items').fetchone()
        for path in [Path(backup),Path(final)]:
            assert hashlib.sha256(path.read_bytes()).hexdigest()==original
            assert path.stat().st_mtime_ns==stat.st_mtime_ns
            assert abs(path.stat().st_birthtime-stat.st_birthtime)<0.001
            for key,value in attributes.items():assert audit._darwin_getxattr(path,key)==value,(path,key)
        run('rollback','--commit-id',cid,'--yes')
        assert source.is_file() and not Path(final).exists()
        for key,value in attributes.items():assert audit._darwin_getxattr(source,key)==value,key
        assert hashlib.sha256(source.read_bytes()).hexdigest()==original
    print('Rename backup and rollback preserve Finder tags, comments, resource forks, file dates and exact bytes: PASS')
if __name__=='__main__':main()
