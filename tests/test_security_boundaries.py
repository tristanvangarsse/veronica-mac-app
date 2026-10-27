#!/usr/bin/env python3
"""Security regressions use only disposable libraries and harmless decoder inputs."""
import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import media_audit as audit
import media_maintenance as mm
import media_security as sec
from PIL import Image
from fixture_dates import exif_date


def command(*args, check=True):
    r=subprocess.run([sys.executable,str(ROOT/'veronica.py'),*map(str,args)],capture_output=True,text=True,timeout=120)
    if check and r.returncode:raise AssertionError(r.stdout+r.stderr)
    return r


class SecurityBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='veronica-security-regression-')
        self.base=Path(self.temp.name).resolve()
        self.media=self.base/'Media';self.state=self.base/'State'
        self.media.mkdir()
    def tearDown(self):self.temp.cleanup()
    def plan(self,large=False,name=None):
        self.source=self.media/(name or ('2023-01-01_photo.jpg' if large else '230101-photo.jpg'))
        Image.new('RGB',(4000,3000) if large else (100,100),(100,60,30)).save(self.source,quality=95,exif=exif_date())
        stamp=dt.datetime(2023,1,1,12).timestamp();os.utime(self.source,(stamp,stamp))
        mm.save_product_settings(self.state, {"filename_date_format":"YYYY-MM-DD_", "image_max_megapixels":10})
        config=self.base/'policy.json';config.write_text(json.dumps({"recompress_images_below_target":False}))
        command('plan','--root',self.media,'--state-dir',self.state,'--run-date','2026-10-15','--config',config)
        self.pp=next(self.state.glob('plan-*.json'));self.plan_data=json.loads(self.pp.read_text());self.item=self.plan_data['items'][0]
        return self.item
    def stage(self, name=None):
        self.plan(True,name=name)
        command('stage','--plan',self.pp,'--state-dir',self.state,'--max-images','1','--max-videos','0','--max-audio','0')
        with sec.database(self.state/'media-maintenance.sqlite') as con:
            self.sid,self.output,self.status=con.execute('SELECT staging_id,output_path,status FROM staging_items').fetchone()
        self.assertEqual(self.status,'STAGED_VERIFIED')
        return argparse.Namespace(state_dir=str(self.state),staging_id=self.sid,relpath=self.item['relpath'],config=None,yes=True)
    def test_changed_plan_and_changed_root_rejected(self):
        self.plan();original=sec.digest(self.source)
        self.plan_data['items'][0]['target']['final_relpath']='../outside.jpg';self.pp.write_text(json.dumps(self.plan_data))
        r=command('commit-rename','--plan',self.pp,'--state-dir',self.state,'--relpath',self.item['relpath'],'--yes',check=False)
        self.assertNotEqual(r.returncode,0);self.assertEqual(sec.digest(self.source),original);self.assertFalse((self.base/'outside.jpg').exists())
    def test_recomputed_plan_id_cannot_bypass_registered_digest(self):
        self.plan();p=self.plan_data;p['items'][0]['target']['final_relpath']='other.jpg'
        p['plan_id']=mm.sha256_text(mm.canonical_json({k:v for k,v in p.items() if k not in ('plan_id','created_at')}));self.pp.write_text(json.dumps(p))
        with self.assertRaises(ValueError):mm.load_plan(self.pp)
    def test_created_at_only_tamper_rejected(self):
        self.plan();self.plan_data['created_at']='changed';self.pp.write_text(json.dumps(self.plan_data))
        with self.assertRaises(ValueError):mm.load_plan(self.pp)
    def test_state_cannot_be_repointed(self):
        self.plan();other=self.base/'Other';other.mkdir()
        with self.assertRaises(ValueError):mm.init_db(self.state/'media-maintenance.sqlite',other)
        with sec.database(self.state/'media-maintenance.sqlite') as con:self.assertEqual(con.execute("SELECT value FROM meta WHERE key='root'").fetchone()[0],str(self.media))
    def test_cleanup_external_record_rejected(self):
        self.plan();victim=self.base/'Unrelated';victim.mkdir();sentinel=victim/'keep';sentinel.write_text('keep')
        with sec.database(self.state/'media-maintenance.sqlite') as con:
            con.execute('INSERT INTO staging_runs(staging_id,plan_id,started_at,status,staging_dir) VALUES(?,?,?,?,?)',('a'*16,self.plan_data['plan_id'],'now','COMPLETE',str(victim)))
        with self.assertRaises(ValueError):mm.cmd_cleanup_superseded(argparse.Namespace(state_dir=str(self.state),plan=None,apply=True))
        self.assertEqual(sentinel.read_text(),'keep')
    def test_cleanup_symlink_and_traversal_rejected(self):
        self.plan();outside=self.base/'Other';outside.mkdir();(outside/'keep').write_text('keep')
        (self.state/'staging').mkdir();(self.state/'staging'/('b'*16)).symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ValueError):sec.remove_staging(self.state,'b'*16)
        for value in ('../Other','/tmp','../'*3):
            with self.assertRaises(ValueError):sec.identifier(value)
        self.assertTrue((outside/'keep').exists())
    def test_full_source_guard_detects_middle_change(self):
        p=self.media/'large.bin';p.write_bytes(b'A'*(4*1024*1024));st=p.stat()
        item=dict(relpath=p.name,source_size=st.st_size,source_mtime_ns=st.st_mtime_ns,source_quick_hash=audit.quick_hash(p),source_full_hash=sec.digest(p))
        with p.open('r+b') as f:f.seek(2*1024*1024);f.write(b'B')
        os.utime(p,ns=(st.st_atime_ns,st.st_mtime_ns))
        self.assertFalse(mm.verify_source_against_item(self.media,item)[0]);self.assertNotEqual(audit.quick_hash(p),item['source_quick_hash'])
    def test_legacy_identity_requires_analysis(self):
        self.plan();item=dict(self.item);item.pop('source_full_hash')
        self.assertEqual(mm.verify_source_against_item(self.media,item),(False,'plan_requires_fresh_analysis'))
    def test_staged_bytes_changed_rejected(self):
        args=self.stage();before=sec.digest(self.source)
        Image.new('RGB',(3000,3000),'blue').save(self.output)
        with self.assertRaises((ValueError,SystemExit)):mm.commit_one(args,quiet=True)
        self.assertEqual(sec.digest(self.source),before)
    def test_destination_is_never_overwritten(self):
        source=self.media/'a';target=self.media/'b';source.write_bytes(b'original');target.write_bytes(b'other')
        with self.assertRaises(FileExistsError):sec.move_no_replace(source,target,self.media,self.media)
        self.assertEqual(source.read_bytes(),b'original');self.assertEqual(target.read_bytes(),b'other')
    def test_parent_symlink_cannot_escape_move(self):
        source=self.media/'a';source.write_bytes(b'original');other=self.base/'Other';other.mkdir();(self.media/'link').symlink_to(other)
        with self.assertRaises(ValueError):sec.move_no_replace(source,self.media/'link/b',self.media,self.media)
        with self.assertRaises(OSError):sec.ensure_parent(self.media/'link/escaped/file',self.media)
        self.assertFalse((other/'escaped').exists())
        self.assertFalse((other/'b').exists());self.assertTrue(source.exists())
    def test_copy_refuses_preexisting_symlink(self):
        src=self.media/'a';src.write_bytes(b'original');victim=self.base/'victim';victim.write_bytes(b'keep');target=self.media/'tmp';target.symlink_to(victim)
        with self.assertRaises(OSError):sec.copy_new(src,target,self.media,self.media)
        self.assertEqual(victim.read_bytes(),b'keep')
    def test_cross_process_lock(self):
        with sec.operation_lock(self.state):
            code='import sys; from pathlib import Path; import media_security as s;\nwith s.operation_lock(Path(sys.argv[1])): print("acquired")'
            r=subprocess.run([sys.executable,'-c',code,str(self.state)],cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertNotEqual(r.returncode,0);self.assertNotIn('acquired',r.stdout)
    def test_racing_source_change_is_not_committed(self):
        args=self.stage();move=sec.move_no_replace;changed=[]
        def race(source,target,sroot,troot):
            if source==self.source and 'quarantine' in target.parts:
                Image.new('RGB',(4000,3000),'blue').save(source,quality=95);changed.append(sec.digest(source))
            return move(source,target,sroot,troot)
        with patch.object(sec,'move_no_replace',side_effect=race):
            with self.assertRaises(SystemExit):mm.commit_one(args,quiet=True)
        self.assertEqual(sec.digest(self.source),changed[0])
        with sec.database(self.state/'media-maintenance.sqlite') as con:self.assertEqual(con.execute("SELECT count(*) FROM commits WHERE status='COMMITTED'").fetchone()[0],0)
    def test_abrupt_commit_and_rollback_recovery(self):
        # Terminate at every real move in commit and rollback, including the
        # non-overwriting link/unlink window in separate tests below.
        for action in ('commit','rollback'):
            for phase in (1,2):
                with self.subTest(action=action,phase=phase),tempfile.TemporaryDirectory(prefix='veronica-crash-case-') as td:
                    case=SecurityBoundaries();case.setUp()
                    try:
                        args=case.stage(name="2023-01-01_photo.JPG");original_hash=sec.digest(case.source)
                        if action=='rollback':
                            result=mm.commit_one(args,quiet=True);cid=result['commit_id']
                        else:cid=''
                        script='''import argparse,os,sys
from pathlib import Path
import media_security as sec
import media_maintenance as mm
state,sid,rel,action,cid,phase=sys.argv[1:];count=0;move=sec.move_no_replace
def stop(*args):
 global count
 result=move(*args);count+=1
 if count==int(phase):os._exit(99)
 return result
sec.move_no_replace=stop
args=argparse.Namespace(state_dir=state,staging_id=sid,relpath=rel,config=None,yes=True,commit_id=cid)
mm.commit_one(args,quiet=True) if action=='commit' else mm.cmd_rollback(args)
'''
                        r=subprocess.run([sys.executable,'-c',script,str(case.state),case.sid,case.item['relpath'],action,cid,str(phase)],cwd=ROOT,capture_output=True,text=True,timeout=30)
                        self.assertEqual(r.returncode,99,r.stdout+r.stderr)
                        with sec.operation_lock(case.state):sec.recover_transactions(case.state)
                        self.assertEqual(sec.digest(case.source),original_hash)
                        with sec.database(case.state/'media-maintenance.sqlite') as con:
                            status=con.execute('SELECT status FROM commits').fetchone()[0]
                        self.assertEqual(status,'ROLLED_BACK' if action=='rollback' else 'RECOVERED_ROLLED_BACK')
                    finally:case.tearDown()
    def test_change_during_final_verification_is_rejected(self):
        args=self.stage();verify=mm.verify_staged_output;changed=[]
        def update(src,out,item,cfg):
            result=verify(src,out,item,cfg)
            if 'quarantine' in src.parts:
                Image.new('RGB',(4000,3000),'green').save(src,quality=95);changed.append(sec.digest(src))
            return result
        with patch.object(mm,'verify_staged_output',side_effect=update):
            with self.assertRaises(SystemExit):mm.commit_one(args,quiet=True)
        self.assertEqual(sec.digest(self.source),changed[0])
        with sec.operation_lock(self.state):sec.recover_transactions(self.state)
        self.assertEqual(sec.digest(self.source),changed[0])
    def test_recovery_preserves_a_newer_conflicting_file(self):
        args=self.stage();original=sec.digest(self.source);move=sec.move_no_replace
        class Interrupted(BaseException):pass
        def stop(src,dst,sroot,troot):
            result=move(src,dst,sroot,troot)
            if 'quarantine' in dst.parts:raise Interrupted()
            return result
        with patch.object(sec,'move_no_replace',side_effect=stop):
            with self.assertRaises(Interrupted):mm.commit_one(args,quiet=True)
        self.source.write_bytes(b'new user content')
        with sec.operation_lock(self.state):
            with self.assertRaises(RuntimeError):sec.recover_transactions(self.state)
        self.assertEqual(self.source.read_bytes(),b'new user content')
        q=next((self.state/'quarantine').rglob('*.jpg'));self.assertEqual(sec.digest(q),original)
    def test_link_before_unlink_is_recoverable(self):
        args=self.stage();original=sec.digest(self.source)
        class Interrupted(BaseException):pass
        unlink=sec.os.unlink
        def stop(path,*rest,**kwargs):
            if str(path)==self.source.name and kwargs.get('dir_fd') is not None:raise Interrupted()
            return unlink(path,*rest,**kwargs)
        with patch.object(sec.os,'unlink',side_effect=stop):
            with self.assertRaises(Interrupted):mm.commit_one(args,quiet=True)
        with sec.operation_lock(self.state):sec.recover_transactions(self.state)
        self.assertEqual(sec.digest(self.source),original)
    def test_rename_interruption_recovers_original_name(self):
        self.plan(name='230101-photo.JPG');self.assertEqual(self.item['operation'],'RENAME')
        original=sec.digest(self.source);move=sec.move_no_replace;calls=[]
        class Interrupted(BaseException):pass
        def stop(*args):
            result=move(*args);calls.append(1)
            if len(calls)==2:raise Interrupted()
            return result
        args=argparse.Namespace(state_dir=str(self.state),plan=str(self.pp),relpath=self.item['relpath'],yes=True)
        with patch.object(sec,'move_no_replace',side_effect=stop):
            with self.assertRaises(Interrupted):mm.commit_one_rename(args,quiet=True)
        with sec.operation_lock(self.state):sec.recover_transactions(self.state)
        self.assertEqual(sec.digest(self.source),original);self.assertIn(self.source.name,os.listdir(self.media))
    def test_preserved_symlink_does_not_block_safe_plan_items(self):
        self.plan();outside=self.base/'Outside';outside.write_bytes(b'keep')
        (self.media/'link.jpg').symlink_to(outside)
        mm.save_product_settings(self.state, {"filename_date_format":"YYYY-MM-DD_", "image_max_megapixels":10})
        config=self.base/'policy.json';config.write_text(json.dumps({"recompress_images_below_target":False}))
        command('plan','--root',self.media,'--state-dir',self.state,'--run-date','2026-10-15','--config',config)
        plan_path=max(self.state.glob('plan-*.json'),key=lambda p:p.stat().st_mtime_ns)
        plan=mm.load_plan(plan_path)
        self.assertEqual(next(i for i in plan['items'] if i['relpath']=='link.jpg')['operation'],'PRESERVE')
        self.assertEqual(outside.read_bytes(),b'keep')
    def test_media_target_symlink_is_rejected(self):
        self.plan();outside=self.base/'Outside';outside.mkdir();(self.media/'alias').symlink_to(outside)
        with self.assertRaises(ValueError):sec.inside(self.media,'alias/file.jpg')
        self.assertEqual(list(outside.iterdir()),[])

    def test_startup_recovers_a_configured_child_folder(self):
        parent=self.base/'ParentState'
        command('configure-folders','--state-dir',parent,'--add',self.media)
        self.state=mm.scan_folder_state_dir(parent,self.media)
        args=self.stage();original=sec.digest(self.source);move=sec.move_no_replace
        class Interrupted(BaseException):pass
        def stop(src,dst,sroot,troot):
            result=move(src,dst,sroot,troot)
            if 'quarantine' in dst.parts:raise Interrupted()
            return result
        with patch.object(sec,'move_no_replace',side_effect=stop):
            with self.assertRaises(Interrupted):mm.commit_one(args,quiet=True)
        self.assertFalse(self.source.exists())
        snapshot=command('ui-snapshot','--state-dir',parent)
        self.assertEqual(sec.digest(self.source),original)
        self.assertTrue(json.loads(snapshot.stdout)['configured'])
    def test_two_states_cannot_mutate_the_same_library(self):
        self.plan();other=self.base/'OtherState'
        with sec.state_access(self.state):
            r=command('plan','--root',self.media,'--state-dir',other,'--run-date','2026-10-15',check=False)
        self.assertNotEqual(r.returncode,0)
        self.assertIn('Another Veronica task',r.stderr)
        self.assertFalse((other/'media-maintenance.sqlite').exists())
    def test_migration_obeys_source_and_destination_locks(self):
        self.plan();destination=self.base/'MigratedState'
        for locked in (self.state,destination):
            with self.subTest(locked=locked),sec.operation_lock(locked,create_state=False):
                r=command('migrate-state','--from-dir',self.state,'--to-dir',destination,'--apply',check=False)
            self.assertNotEqual(r.returncode,0)
            self.assertTrue(self.state.exists());self.assertFalse(destination.exists())
    def test_library_root_replacement_cannot_redirect_a_plan(self):
        self.plan();moved=self.base/'MovedMedia';self.media.rename(moved)
        outside=self.base/'OutsideMedia';outside.mkdir();(outside/self.source.name).write_bytes(b'keep')
        self.media.symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ValueError):mm.load_plan(self.pp)
        self.assertEqual((outside/self.source.name).read_bytes(),b'keep')
    def test_timeout_kills_descendants_after_the_leader_exits(self):
        pidfile=self.base/'child.pid'
        code="import subprocess,sys,os;from pathlib import Path;p=subprocess.Popen([sys.executable,'-I','-c','import time;time.sleep(30)']);Path(sys.argv[1]).write_text(str(p.pid));os._exit(0)"
        with self.assertRaises(subprocess.TimeoutExpired):
            sec.bounded_run([sys.executable,'-I','-c',code,str(pidfile)],timeout=1,writes=[pidfile])
        pid=int(pidfile.read_text())
        for _ in range(20):
            status=subprocess.run(['/bin/ps','-p',str(pid),'-o','stat='],capture_output=True,text=True).stdout.strip()
            if not status or status.startswith('Z'):break
            time.sleep(.05)
        self.assertTrue(not status or status.startswith('Z'),status)
    def test_unknown_data_is_preserved(self):
        unknown={'codec_type':'data','codec_tag_string':'zzzz','tags':{'handler_name':'Scientific measurements'}}
        known={'codec_type':'data','codec_tag_string':'mebx','tags':{'handler_name':'Core Media Metadata'}}
        self.assertFalse(mm.is_droppable_camera_metadata_stream(unknown));self.assertTrue(mm.is_droppable_camera_metadata_stream(known))
        src={'streams':[{'codec_type':'video'},unknown]};out={'streams':[{'codec_type':'video'}]}
        self.assertFalse(mm.camera_metadata_drop_allowed(src,out,mm.DEFAULT_CONFIG))
    def test_disguised_psd_is_rejected(self):
        p=self.media/'2023-01-01_fake.jpg';width,height=100,100
        p.write_bytes(b'8BPS'+struct.pack('>H',1)+b'\0'*6+struct.pack('>HIIHH',3,height,width,8,3)+struct.pack('>IIIH',0,0,0,0)+b'\x60'*(3*width*height))
        before=sec.digest(p);result=audit.probe_image(p)
        self.assertIn('probe_error',result);self.assertEqual(sec.digest(p),before)
    def test_worker_cannot_read_or_write_other_files_or_network(self):
        approved=self.media/'allowed';approved.write_text('allowed');outside=self.base/'secret';outside.write_text('private')
        output=self.base/'unauthorized'
        code='''import socket,sys
from pathlib import Path
assert Path(sys.argv[1]).read_text()=="allowed"
for path,mode in [(sys.argv[2],"r"),(sys.argv[3],"w")]:
 try:open(path,mode)
 except PermissionError:pass
 else:raise AssertionError("Filesystem escape")
try:socket.create_connection(("127.0.0.1",9),timeout=.2)
except PermissionError:pass
else:raise AssertionError("Network allowed")
print("restricted")
'''
        result=sec.bounded_run([sys.executable,'-I','-B','-c',code,str(approved),str(outside),str(output)],reads=[approved])
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(outside.read_text(),'private');self.assertFalse(output.exists())
    def test_timeout_and_output_limits(self):
        with self.assertRaises(subprocess.TimeoutExpired):sec.bounded_run([sys.executable,'-I','-c','import time;time.sleep(30)'],timeout=.2)
        with self.assertRaises(RuntimeError):sec.bounded_run([sys.executable,'-I','-c','print("x"*100000)'],max_output=1000)
    def test_untrusted_environment_is_removed(self):
        with patch.dict(os.environ,{'PYTHONPATH':'/untrusted','DYLD_INSERT_LIBRARIES':'/untrusted.dylib','BASH_ENV':'/untrusted'}):
            env=sec.clean_environment()
        self.assertTrue({'PYTHONPATH','DYLD_INSERT_LIBRARIES','BASH_ENV'}.isdisjoint(env))
    def test_private_state_permissions(self):
        self.plan()
        self.assertEqual(self.state.stat().st_mode & 0o777,0o700)
        self.assertEqual((self.state/'media-maintenance.sqlite').stat().st_mode & 0o777,0o600)


if __name__=='__main__':unittest.main()
