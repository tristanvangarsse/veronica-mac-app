Release builds stage the standalone Veronica engine here.

The engine is packaged with PyInstaller in --onedir mode. The executable remains:

    VeronicaEngine/veronica-engine

Supporting runtime files live alongside it (normally under _internal/).

These generated files are build artifacts and are not source-controlled.
Run scripts/build_standalone_engine_macos.sh before producing a Release build.
