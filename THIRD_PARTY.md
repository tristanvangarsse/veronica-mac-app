# Third-party software in Veronica

Veronica's own source is provided under the [MIT licence](LICENSE). The downloadable application also contains separately licensed software. Those components retain their own copyright notices, licence terms and source availability rights.

The beta release supplies `Veronica-0.16.0-beta.1-ThirdPartySources.tar.gz` beside the application DMG. It contains matching media-tool source archives, Homebrew build recipes and receipts, HandBrake's vendored FFmpeg/x265 sources, the embedded ExifTool source, runtime notices and component provenance. `SOURCES.json` records upstream URLs and archive checksums. Veronica's own complete source and packaging scripts are available from the same GitHub release tag.

| Component | Licence information |
| --- | --- |
| Python | Python Software Foundation licence and included notices |
| Pillow | MIT-CMU and the licences of its native components; see the supplied Pillow licence files and component SBOM |
| PyInstaller bootloader | GPL with the upstream bootloader exception; see the supplied licence text |
| FFmpeg / ffprobe | This media-tool build enables GPL components and version 3; GPL-3.0-or-later applies to that FFmpeg build |
| HandBrakeCLI | GPL-2.0-only, with separately licensed dependencies |
| ExifTool | Distributed under the same terms as Perl; both supplied licence alternatives and the embedded source are included |
| Media libraries | Their individual licences and source/build recipes are included in the source archive and the app's `MediaTools/licenses` directory |

The media executables' native load paths and signatures are adjusted by `scripts/bundle_media_tools.py` so they can run inside the app. Their upstream source code is not edited by that relocation step. ExifTool's bundled library lookup is adjusted by `scripts/release_manifest.py`; the resulting Perl source is supplied in the app and source archive.

The app's complete third-party notices are available in `Veronica.app/Contents/Resources/VeronicaEngine/_internal/`, under `licenses`, `MediaTools/licenses` and `ExifTool`. Build receipts, source formulae and per-file provenance identify the particular versions used in a release.

If a source download is unavailable, report it through this repository's Issues so the matching source asset can be restored. The licences in the source archives are authoritative for the respective components.
