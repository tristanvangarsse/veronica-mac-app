import importlib.util
import sys
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))
spec = importlib.util.spec_from_file_location('mm083', PKG / 'media_maintenance.py')
mm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mm)


def run_case(width, height, dar, expected):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = td / 'in.m4v'
        src.write_bytes(b'x')
        dst = td / 'out.tmp'
        preset = td / 'preset.json'
        preset.write_text(json.dumps({'PresetList':[{'PresetName':'TEST'}]}))
        captured = {}

        old_which = mm.security.resolve_tool
        old_probe = mm.ffprobe_json
        old_summary = mm.video_stream_summary
        old_run = mm.security.bounded_run
        old_tags = mm.copy_personal_finder_tags_xattr
        old_fs = mm.restore_stage_filesystem_metadata
        try:
            mm.security.resolve_tool = lambda name: '/usr/local/bin/HandBrakeCLI' if name == 'HandBrakeCLI' else old_which(name)
            mm.ffprobe_json = lambda p: {'streams': []}
            mm.video_stream_summary = lambda info: {
                'width': width, 'height': height,
                'display_aspect_ratio_value': dar,
                'rotation': 0,
            }
            def fake_run(cmd, **kwargs):
                captured['cmd'] = cmd
                Path(cmd[cmd.index('-o') + 1]).write_bytes(b'out')
                return SimpleNamespace(returncode=0, stdout='', stderr='')
            mm.security.bounded_run = fake_run
            mm.copy_personal_finder_tags_xattr = lambda a,b,c: (True,'no_tags',[])
            mm.restore_stage_filesystem_metadata = lambda a,b: {'ok': True}
            result = mm.convert_video_stage(src, dst, {'target': {'preset': str(preset)}}, {'video_max_storage_edge':1280, 'stage_copy_personal_finder_tags':True}, td)
        finally:
            mm.security.resolve_tool = old_which
            mm.ffprobe_json = old_probe
            mm.video_stream_summary = old_summary
            mm.security.bounded_run = old_run
            mm.copy_personal_finder_tags_xattr = old_tags
            mm.restore_stage_filesystem_metadata = old_fs

        cmd = captured['cmd']
        assert '--crop-mode' in cmd and cmd[cmd.index('--crop-mode')+1] == 'none'
        assert '--crop' in cmd and cmd[cmd.index('--crop')+1] == '0:0:0:0'
        assert '--non-anamorphic' in cmd
        assert int(cmd[cmd.index('-w')+1]) == expected[0]
        assert int(cmd[cmd.index('-l')+1]) == expected[1]
        assert result['expected_full_frame_dimensions'] == expected
        assert result['requested_crop'] == [0,0,0,0]


def test_landscape_1080p():
    run_case(1920,1080,16/9,[1280,720])


def test_portrait_1080p():
    run_case(1080,1920,9/16,[720,1280])


def test_small_no_upscale():
    run_case(1080,608,1080/608,[1080,608])

if __name__ == '__main__':
    test_landscape_1080p(); test_portrait_1080p(); test_small_no_upscale(); print('ok')
