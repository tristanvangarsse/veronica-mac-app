#!/usr/bin/env python3
"""Decode and round-trip real folder and preset payloads using the app's Swift models."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='veronica-folder-contract-') as td:
    base = Path(td)
    folders = [base/'Family photos', base/'Voice recordings']
    for folder in folders: folder.mkdir()
    state = base/'State'
    def run(*args):
        result = subprocess.run([sys.executable,str(ROOT/'veronica.py'),*map(str,args),'--state-dir',str(state)],capture_output=True,text=True,timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)
    run('configure-folders','--add',folders[0],'--add',folders[1])
    snapshot = run('ui-snapshot')
    assert len(snapshot['folder_settings']) == 2
    assert len(snapshot['settings_presets']) >= 2
    original = snapshot['folder_settings'][0]
    recipe = original['recipe']
    recipe['optimization_settings']['image_output_format'] = 'png'
    recipe['optimization_settings']['jpeg_quality'] = 84
    recipe['optimization_settings']['image_max_megapixels'] = 7
    recipe['optimization_settings'].update(video_max_edge=1000, recompress_images_below_target=False, minimum_saving_percent=3.5, minimum_saving_mb=2.5)
    recipe['filename_policy']['date_format']='YYYY.MM.DD_'
    changed = run('configure-folder','--folder',folders[0],'--recipe-json',json.dumps(recipe))
    run('save-preset','--name','Custom PNG recipe','--recipe-json',json.dumps(changed['recipe']))
    snapshot = run('ui-snapshot')
    payload = base/'snapshot.json'; payload.write_text(json.dumps(snapshot))
    source = base/'main.swift'; binary = base/'check'; roundtrip = base/'recipe.json'
    source.write_text(r'''
import Foundation
let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
let snapshot = try JSONDecoder().decode(UISnapshot.self, from: data)
let folders = snapshot.folderSettings!
assert(folders.count == 2)
assert(snapshot.settingsPresets!.contains { $0.name == "Custom PNG recipe" && !$0.builtIn })
assert(snapshot.defaultPresetID != nil)
let folder = folders.first { $0.folder.hasSuffix("Family photos") }!
assert(folder.recipe.optimizationSettings.jpegQuality == 84)
assert(folder.recipe.optimizationSettings.imageMaxMegapixels == 7)
assert(folder.recipe.optimizationSettings.videoMaxEdge == 1000)
assert(!folder.recipe.optimizationSettings.recompressImagesBelowTarget)
assert(folder.recipe.optimizationSettings.minimumSavingPercent == 3.5)
assert(folder.recipe.optimizationSettings.minimumSavingMB == 2.5)
assert(folder.recipe.filenamePolicy.dateFormat == "YYYY.MM.DD_")
assert(FilenameDateStyle.isValid("DD_MM_YY-"))
assert(!FilenameDateStyle.isValid("YYYY/MM/DD_"))
assert(FilenameDateStyle.example("DD-MM-YYYY_") == "01-01-2023_photo.jpg")
// Malformed saving fields must not silently become the valid value zero.
for invalid in ["", " ", "oops", "NaN", "Infinity", "-Infinity", "3,5,2"] {
    assert(SettingsNumberInput.decimal(invalid) == nil)
}
assert(SettingsNumberInput.decimal("0") == 0)
assert(SettingsNumberInput.decimal(" 3,5 ") == 3.5)
assert(SettingsNumberInput.decimal("2.5") == 2.5)
assert(MediaProcessingPolicy.defaultExcludedDirectoryNames.isEmpty)
assert(folder.recipe.summary.contains("PNG"))
assert(!folder.recipe.summary.contains("JPEG"))
assert(folder.recipe.dateScope.summary == "Older than 2 years")
let encoded = try JSONEncoder().encode(folder.recipe)
try encoded.write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
let decoded = try JSONDecoder().decode(ProcessingRecipe.self, from: encoded)
assert(decoded == folder.recipe)
print("Swift folder settings and preset contract: PASS")
''')
    subprocess.run(['/usr/bin/swiftc',str(ROOT/'macos/Veronica/Sources/Models.swift'),str(source),'-o',str(binary)],check=True,timeout=90)
    subprocess.run([str(binary),str(payload),str(roundtrip)],check=True,timeout=10)
    returned = run('configure-folder','--folder',folders[0],'--recipe-json',roundtrip.read_text())
    assert returned['recipe']['optimization_settings']['jpeg_quality'] == 84
    assert not list(folders[0].iterdir()) and not list(folders[1].iterdir())
print('Actual Swift recipe serialization accepted by backend without touching media: PASS')
