#!/usr/bin/env python3
"""First-run preparation is repeatable, private and never acknowledges failure."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import media_maintenance as mm
import media_dates
with tempfile.TemporaryDirectory(prefix='veronica-setup-') as td:
    state=Path(td).resolve()/'Preferences';args=argparse.Namespace(state_dir=str(state))
    status={'python':'/bundled/python','python_version':'3.14.8','pillow':{'available':True,'version':'12.3.0'},
            'tools':{name:{'available':True,'path':'/bundled/'+name} for name in ('ffmpeg','ffprobe','HandBrakeCLI','ExifTool','Perl','file','xattr')}}
    def run():
        out=io.StringIO()
        with contextlib.redirect_stdout(out):mm.cmd_prepare_runtime(args)
        return json.loads(out.getvalue())
    with patch.object(mm,'dependency_status',return_value=status), patch.object(media_dates,'exiftool_command',return_value=['/usr/bin/perl5.34','/bundled/ExifTool']), patch.object(mm.security,'bounded_run',return_value=subprocess.CompletedProcess([],0,'version 1','')) as execute:
        assert run()['prepared_now'] and execute.call_count==4
        receipt=state/'runtime-setup.json';saved=receipt.read_bytes()
        assert receipt.stat().st_mode&0o777==0o600
        assert not run()['prepared_now'] and execute.call_count==4 and receipt.read_bytes()==saved
        status['tools']['ffmpeg']['available']=False
        try:run()
        except RuntimeError as error:assert 'Reinstall' in str(error)
        else:raise AssertionError('Missing component was marked ready')
        assert receipt.read_bytes()==saved
        status['tools']['ffmpeg']['available']=True
        status['pillow']['version']='12.3.1'
        execute.return_value=subprocess.CompletedProcess([],1,'','cannot start')
        try:run()
        except RuntimeError as error:assert 'Reinstall' in str(error)
        else:raise AssertionError('Failed self-test was marked ready')
        assert receipt.read_bytes()==saved
        execute.return_value=subprocess.CompletedProcess([],0,'version 2','')
        assert run()['prepared_now']
        receipt.write_text('interrupted setup')
        assert run()['prepared_now']
        receipt.unlink();outside=Path(td)/'outside';outside.write_text('keep');receipt.symlink_to(outside)
        try:run()
        except ValueError:pass
        else:raise AssertionError('Setup receipt followed a symlink')
        assert outside.read_text()=='keep'
print('First-run setup, repeat-launch cache, failed component retention, update retry and private receipt: PASS')
