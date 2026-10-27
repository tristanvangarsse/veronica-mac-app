#!/usr/bin/env python3
"""Folder recipe isolation, migrations, preset snapshots and stale-work safety."""
import argparse
import contextlib
import copy
import datetime as dt
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import media_audit as audit
import media_maintenance as mm
import media_security as sec


def call(function, **values):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = function(argparse.Namespace(**values))
    if result:
        raise AssertionError(output.getvalue())
    try:
        return json.loads(output.getvalue())
    except json.JSONDecodeError:
        return output.getvalue()


class FolderSettings(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="veronica-folder-settings-")
        self.base = Path(self.temp.name).resolve()
        self.state = self.base / "State"
        self.first = self.base / "Photos"
        self.second = self.base / "Elsewhere"
        self.first.mkdir(); self.second.mkdir()
        self.add(self.first, self.second)
    def tearDown(self):
        self.temp.cleanup()
    def add(self, *folders):
        return call(mm.cmd_configure_folders, state_dir=str(self.state), add=list(map(str, folders)), remove=[])
    def payload(self, folder):
        return mm.folder_settings_payload(self.state, folder)
    def configure(self, folder, recipe):
        return call(mm.cmd_configure_folder, state_dir=str(self.state), folder=str(folder), recipe_json=json.dumps(recipe))
    def set_default(self, identifier):
        return call(mm.cmd_set_default_preset, state_dir=str(self.state), preset_id=identifier)
    def plan(self, folder):
        state = mm.scan_folder_state_dir(self.state, folder)
        call(mm.cmd_plan, root=str(folder), state_dir=str(state), config=None, run_date="2026-10-16")
        return state, max(state.glob("plan-*.json"), key=lambda path:path.stat().st_mtime_ns)

    def test_copies_defaults_once_and_preserves_independent_edits(self):
        first = self.payload(self.first)["recipe"]
        self.assertEqual(first["optimization_settings"]["image_max_megapixels"], 20)
        self.assertEqual(first["optimization_settings"]["jpeg_quality"], 70)
        first["optimization_settings"]["jpeg_quality"] = 82
        first["media_processing"].update(audio=False, audio_extensions=[])
        self.configure(self.first, first)
        self.set_default("smaller-files")
        third = self.base / "New folder"; third.mkdir(); self.add(third)
        self.assertEqual(self.payload(third)["recipe"]["optimization_settings"]["image_max_megapixels"],10)
        self.assertEqual(self.payload(self.first)["recipe"], first)
        self.assertEqual(self.payload(self.second)["recipe"]["optimization_settings"]["image_max_megapixels"],20)
        parent = mm.load_product_settings(self.state); parent.update(jpeg_quality=40, process_audio=False)
        mm.save_product_settings(self.state,parent)
        mm.prepare_scan_folder_state(self.state,self.first)
        self.assertEqual(self.payload(self.first)["recipe"],first)

    def test_presets_are_snapshots_and_builtin_recipes_are_immutable(self):
        recipe = self.payload(self.first)["recipe"]
        recipe["optimization_settings"]["jpeg_quality"] = 80
        custom = call(mm.cmd_save_preset,state_dir=str(self.state),name="My photos",recipe_json=json.dumps(recipe),preset_id=None)
        self.set_default(custom["id"])
        call(mm.cmd_apply_preset,state_dir=str(self.state),folder=str(self.first),preset_id=custom["id"])
        recipe["optimization_settings"]["jpeg_quality"] = 60
        call(mm.cmd_save_preset,state_dir=str(self.state),name="Renamed",recipe_json=json.dumps(recipe),preset_id=custom["id"])
        self.assertEqual(self.payload(self.first)["recipe"]["optimization_settings"]["jpeg_quality"],80)
        self.assertIsNone(self.payload(self.first)["preset_id"])
        call(mm.cmd_delete_preset,state_dir=str(self.state),preset_id=custom["id"])
        self.assertEqual(mm.settings_presets(self.state)[1],"balanced")
        self.assertEqual(self.payload(self.first)["recipe"]["optimization_settings"]["jpeg_quality"],80)
        with self.assertRaises(ValueError):
            call(mm.cmd_save_preset,state_dir=str(self.state),name="Balanced",recipe_json=json.dumps(recipe),preset_id="balanced")
        with self.assertRaises(ValueError):
            call(mm.cmd_delete_preset,state_dir=str(self.state),preset_id="balanced")

    def test_existing_child_preferences_and_legacy_root_history_are_retained(self):
        child = mm.scan_folder_state_dir(self.state,self.first)
        mm.save_product_settings(child,{"jpeg_quality":89,"image_max_megapixels":8,"process_audio":False})
        mm.prepare_scan_folder_state(self.state,self.first)
        self.assertEqual(self.payload(self.first)["recipe"]["optimization_settings"]["jpeg_quality"],89)
        legacy = self.base / "Legacy state"
        mm.save_product_settings(legacy,{"archive_root":str(self.first),"jpeg_quality":84,"image_max_megapixels":12})
        con = mm.init_db(legacy/"media-maintenance.sqlite",self.first); con.close()
        mm.prepare_scan_folder_state(legacy,self.first)
        self.assertEqual(mm.scan_folder_state_dir(legacy,self.first),legacy)
        before = mm.recipe_product_settings(legacy)
        call(mm.cmd_set_default_preset,state_dir=str(legacy),preset_id="smaller-files")
        self.assertEqual(mm.recipe_product_settings(legacy),before)
        with sec.database(legacy/"media-maintenance.sqlite") as con:
            self.assertEqual(con.execute("SELECT value FROM meta WHERE key='root'").fetchone()[0],str(self.first))
        self.assertEqual(before["optimization_settings"]["jpeg_quality"],84)

    def test_changed_recipe_blocks_stage_and_every_commit_entry(self):
        state, plan = self.plan(self.first)
        self.assertFalse(self.payload(self.first)["needs_analysis"])
        identifier = mm.load_plan(plan,state)["plan_id"]
        recipe = self.payload(self.first)["recipe"]
        recipe["optimization_settings"]["jpeg_quality"] = 75
        self.configure(self.first, recipe)
        self.assertTrue(self.payload(self.first)["needs_analysis"])
        with self.assertRaisesRegex(ValueError,"Analyze"):
            mm.load_plan(plan,state)
        with self.assertRaises(ValueError):
            call(mm.cmd_stage,state_dir=str(state),plan=str(plan),config=None,max_images=1,max_videos=0,max_audio=0,sample_strategy="first",require_personal_tag_sample=False)
        for function in (mm.commit_one,mm.commit_one_audio,mm.commit_one_video):
            with patch.object(mm,"load_staging_report",return_value={"plan_id":identifier}):
                with self.assertRaises(ValueError):
                    function(argparse.Namespace(state_dir=str(state),staging_id="a"*16,relpath="missing.jpg",config=None,yes=True))
        with self.assertRaises(ValueError):
            mm.commit_one_rename(argparse.Namespace(state_dir=str(state),plan=str(plan),relpath="missing.jpg",yes=True))
        snapshot = mm._ui_snapshot_for_folder(self.first,state,20)
        self.assertIsNone(snapshot["latest_plan"])
        self.assertEqual(snapshot["unresolved_reviews"],[])
        self.plan(self.first)
        self.assertFalse(self.payload(self.first)["needs_analysis"])

    def test_default_or_preset_metadata_changes_do_not_invalidate_analyzed_folder(self):
        state, path = self.plan(self.first)
        before = mm.load_plan(path,state)["recipe_digest"]
        self.set_default("smaller-files")
        custom = call(mm.cmd_save_preset,state_dir=str(self.state),name="Just a copy",recipe_json=json.dumps(self.payload(self.first)["recipe"]),preset_id=None)
        call(mm.cmd_delete_preset,state_dir=str(self.state),preset_id=custom["id"])
        self.assertEqual(mm.load_plan(path,state)["recipe_digest"],before)
        self.assertFalse(self.payload(self.first)["needs_analysis"])

    def test_legacy_cli_edits_current_recipe_without_changing_defaults(self):
        state, plan = self.plan(self.first)
        initial_default = mm.settings_presets(self.state)
        call(mm.cmd_configure_optimization,state_dir=str(state),image_format="png",image_max_megapixels=9,photo_library_max_megapixels=None,jpeg_quality=85,video_max_edge=1920,audio_min_size_mb=20,allow_camera_metadata_drop="false")
        self.assertEqual(self.payload(self.first)["recipe"]["optimization_settings"]["jpeg_quality"],85)
        with self.assertRaises(ValueError): mm.load_plan(plan,state)
        call(mm.cmd_configure_filenames,state_dir=str(state),enabled="false",date_format="YYMMDD-",max_bytes=100)
        self.assertFalse(self.payload(self.first)["recipe"]["filename_policy"]["enabled"])
        call(mm.cmd_configure_media_types,state_dir=str(state),images="true",videos="false",audio="false",image_extensions="jpg,png",video_extensions=None,audio_extensions=None)
        self.assertFalse(self.payload(self.first)["recipe"]["media_processing"]["videos"])
        call(mm.cmd_configure_date_scope,state_dir=str(state),mode="all",start=None,end=None)
        self.assertEqual(self.payload(self.first)["recipe"]["date_scope"]["mode"],"all")
        call(mm.cmd_restore_manual_defaults,state_dir=str(state))
        self.assertEqual(self.payload(self.first)["recipe"]["optimization_settings"]["jpeg_quality"],70)
        self.assertEqual(mm.settings_presets(self.state),initial_default)

    def test_active_child_operation_blocks_edit_and_removal(self):
        state = mm.scan_folder_state_dir(self.state,self.first)
        code = "import pathlib,sys,time;sys.path.insert(0,sys.argv[1]);import media_security as s;\nwith s.state_access(pathlib.Path(sys.argv[2]),sys.argv[3]):\n print('ready',flush=True);time.sleep(30)"
        worker = subprocess.Popen([sys.executable,"-c",code,str(ROOT),str(state),str(self.first)],stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual(worker.stdout.readline().strip(),"ready")
            recipe = self.payload(self.first)["recipe"]; recipe["optimization_settings"]["jpeg_quality"] = 85
            with self.assertRaisesRegex(RuntimeError,"Another Veronica task"):
                self.configure(self.first,recipe)
            with self.assertRaisesRegex(RuntimeError,"Another Veronica task"):
                call(mm.cmd_configure_folders,state_dir=str(self.state),add=[],remove=[str(self.first)])
            self.assertEqual(self.payload(self.first)["recipe"]["optimization_settings"]["jpeg_quality"],70)
        finally:
            worker.terminate();worker.wait(timeout=10);worker.stdout.close()

    def test_nested_and_symlink_alias_roots_rejected_in_all_folder_runs(self):
        nested = self.first / "2024"; nested.mkdir()
        with self.assertRaises((ValueError,SystemExit)): self.add(nested)
        alias = self.base/"Alias";alias.symlink_to(self.first,target_is_directory=True)
        self.add(alias)  # A duplicate of the same canonical folder is harmless and stays one entry.
        self.assertEqual(len(mm.configured_scan_folders(self.state)),2)
        data = mm.load_product_settings(self.state);data["scan_folders"] = [str(self.first),str(nested)];mm.save_product_settings(self.state,data)
        with self.assertRaises(ValueError):
            call(mm.cmd_analyze_all,state_dir=str(self.state),config=None,run_date=None,events_jsonl=None)
        with self.assertRaises(ValueError):
            call(mm.cmd_annual_all,state_dir=str(self.state),yes=True)

    def test_media_and_state_folders_cannot_contain_one_another(self):
        with self.assertRaisesRegex(ValueError,"separate"):
            self.add(self.base)
        inside_state=self.state/"Another media folder";inside_state.mkdir()
        with self.assertRaisesRegex(ValueError,"separate"):
            self.add(inside_state)
        for root,state in ((self.base,self.state),(inside_state,self.state),(self.state,self.state)):
            with self.assertRaisesRegex(ValueError,"separate"):
                call(mm.cmd_plan,root=str(root),state_dir=str(state),config=None,run_date=None)
        self.assertEqual(list(self.state.glob("plan-*.json")),[])
        data=mm.load_product_settings(self.state);data["scan_folders"]=[str(self.base)];mm.save_product_settings(self.state,data)
        with self.assertRaisesRegex(ValueError,"separate"):
            call(mm.cmd_analyze_all,state_dir=str(self.state),config=None,run_date=None,events_jsonl=None)
        with self.assertRaisesRegex(ValueError,"separate"):
            call(mm.cmd_annual_all,state_dir=str(self.state),yes=True)

    def test_personal_folder_names_do_not_change_conversion_or_protection(self):
        cfg=mm.load_config(None)
        row={"name":"2023-01-01.jpg","extension":".jpg","detected_kind":"image","extension_kind":"image","tags":[],"is_symlink":False,"best_date":"2023-01-01","date_confidence":"HIGH","size":10000,"animated":False,"action":"CANDIDATE","megapixels":21,"has_alpha":False}
        for name in ("Streams","Photo_Library","Imagehead","Vacation"):
            item=mm.make_item({**row,"relpath":name+"/Original/photo.jpg"},1,cfg)
            self.assertEqual(item["target"]["max_megapixels"],20)
            self.assertEqual(cfg["excluded_directory_names"], [])
            auditor=audit.Auditor(self.first,{**cfg,"excluded_directory_names":["Original"]},dt.date(2026,10,16),self.state,False,False)
            decision=auditor.decide({**row,"relpath":name+"/Original/photo.jpg"})
            self.assertEqual(decision.action,"PRESERVE")
            self.assertEqual(decision.reason,"excluded_directory")
            unrestricted = audit.Auditor(self.first,{**cfg,"excluded_directory_names":[]},dt.date(2026,10,16),self.state,False,False)
            self.assertEqual(unrestricted.decide({**row,"relpath":name+"/Original/photo.jpg"}).action,"CANDIDATE")
            self.assertEqual(auditor.decide({**row,"relpath":name+"/photo.raw","extension_kind":"master_image","extension":".raw"}).action,"PRESERVE")

    def test_recipe_and_preset_validation_rejects_invalid_values(self):
        recipe = self.payload(self.first)["recipe"]
        for key,val in (("jpeg_quality",float("nan")),("image_max_megapixels",float("inf")),("image_max_megapixels",0),("video_max_edge",True)):
            invalid=copy.deepcopy(recipe);invalid["optimization_settings"][key]=val
            with self.assertRaises(ValueError):mm.validate_recipe(invalid)
        for name in ("", " ", "a\nname", "a"*81):
            with self.assertRaises(ValueError):mm.validate_preset_name(name)
        for identifier in ("../escape","/absolute","A",None):
            with self.assertRaises(ValueError):mm.validate_preset_id(identifier)
        invalid=copy.deepcopy(recipe);invalid["date_scope"]={"mode":"within","start":"2025-01-01","end":"2024-01-01"}
        with self.assertRaises(ValueError):mm.validate_recipe(invalid)
        for names in (["../escape"], ["one/two"], [".."], ["one\nline"], "Original", ["x"]*101):
            invalid=copy.deepcopy(recipe);invalid["media_processing"]["excluded_directory_names"]=names
            with self.assertRaises(ValueError):mm.validate_recipe(invalid)
        optional=copy.deepcopy(recipe);optional["date_scope"]={"mode":"all"}
        self.assertIsNone(mm.validate_recipe(optional)["date_scope"]["start"])
        # The recipe digest must not change when a relative age cutoff rolls over.
        before=mm.recipe_digest(mm.scan_folder_state_dir(self.state,self.first))
        self.assertEqual(before,mm.recipe_digest(mm.scan_folder_state_dir(self.state,self.first)))

if __name__ == "__main__":
    unittest.main()
