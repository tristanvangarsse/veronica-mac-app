"""Internal restricted image worker. The parent owns all library mutations."""
from __future__ import annotations
import json
from pathlib import Path
import resource
import sys

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(arguments=None):
    import media_security as security
    security.require_supported_runtime()
    security._WORKER = True
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = 100_000_000
    action, raw = (arguments or sys.argv[1:])
    data = json.loads(raw)
    path = Path(data['source'])
    if action == 'probe':
        import media_audit
        result = media_audit.probe_image(path)
    elif action == 'metadata':
        import media_maintenance
        result = media_maintenance.image_metadata(path)
    elif action == 'verify':
        with Image.open(path, formats=security.pillow_formats()) as image:
            image.verify()
        result = {'verified': True}
    elif action == 'convert':
        import media_maintenance
        result = media_maintenance.convert_image_pixels(path, Path(data['destination']), data['item'], data['config'])
    else:
        raise ValueError('Unknown internal media operation')
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
