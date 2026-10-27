"""Filesystem and process boundaries shared by Veronica's source and frozen engines."""
from __future__ import annotations

import contextlib
import fcntl
import functools
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata

IMAGE_FORMATS = ("JPEG", "MPO", "PNG", "GIF", "WEBP", "BMP", "HEIF", "HEIC")
def pillow_formats() -> tuple[str, ...]:
    from PIL import Image
    Image.init()
    return tuple(fmt for fmt in IMAGE_FORMATS if fmt in Image.OPEN)


_WORKER = False
_LOCKS = threading.local()


@contextlib.contextmanager
def database(path: Path):
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    flags = os.O_RDONLY | os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("Expected a regular file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                h.update(chunk)
    finally:
        os.close(fd)
    return h.hexdigest()


def identifier(value: str, length: int = 16) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{%d}" % length, value):
        raise ValueError("Invalid operation identifier")
    return value


def relative(value: str) -> Path:
    p = Path(value)
    if not value or p.is_absolute() or ".." in p.parts or not p.parts or "\x00" in value:
        raise ValueError("Unsafe relative pathname")
    return p


def inside(root: Path, value: str | Path) -> Path:
    root = Path(os.path.abspath(root))
    if root.resolve() != root:
        raise ValueError("Maintenance root changed or resolves through a symbolic link")
    rel = relative(str(value))
    path = root
    for part in rel.parts:
        path /= part
        if path.is_symlink():
            raise ValueError("Symbolic links are not permitted in a maintenance path")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Path escapes its maintenance folder")
    return path


def private_directory(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("State directory cannot be a symbolic link")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)


def atomic_json(path: Path, data: dict) -> None:
    private_directory(path.parent)
    fd, tmp = tempfile.mkstemp(prefix=".veronica-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextlib.contextmanager
def operation_lock(state: Path, *, create_state: bool = True, namespace: str = "state"):
    state = state.expanduser().resolve()
    canonical = unicodedata.normalize("NFC", str(state))
    if sys.platform == "darwin":
        canonical = canonical.casefold()
    if namespace == "library" and state.is_dir():
        identity = state.stat()
        canonical = f"{identity.st_dev}:{identity.st_ino}"
    key = (namespace, canonical)
    locks = getattr(_LOCKS, "held", {})
    _LOCKS.held = locks
    if key in locks:
        yield
        return
    # Registry paths do not move when state is migrated. All launch environments
    # use the same per-user directory, independent of HOME/PATH/TMPDIR overrides.
    registry = Path("/private/var/tmp" if sys.platform == "darwin" else "/tmp") / f"veronica-locks-{os.getuid()}"
    private_directory(registry)
    name = hashlib.sha256((namespace + ":" + canonical).encode()).hexdigest()
    fd = os.open(registry / (name + ".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another Veronica task is working on this library. Try again when it finishes.")
        if create_state:
            private_directory(state)
        locks[key] = fd
        yield
    finally:
        locks.pop(key, None)
        os.close(fd)


def library_root(state: Path) -> Path | None:
    db = inside(state, "media-maintenance.sqlite")
    if not db.exists():
        return None
    with database(db) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='meta'").fetchone():
            return None
        row = con.execute("SELECT value FROM meta WHERE key='root'").fetchone()
    return Path(row[0]).resolve() if row else None


@contextlib.contextmanager
def state_access(state: Path, explicit_root=None):
    with operation_lock(state):
        root = Path(explicit_root).expanduser().resolve() if explicit_root else library_root(state)
        guard = operation_lock(root, create_state=False, namespace="library") if root else contextlib.nullcontext()
        with guard:
            yield


def state_operation(fn):
    @functools.wraps(fn)
    def guarded(args, *extra, **kwargs):
        state = Path(getattr(args, "state_dir", None) or "~/Library/Application Support/Veronica").expanduser().resolve()
        with state_access(state, getattr(args, "root", None)):
            recover_transactions(state)
            return fn(args, *extra, **kwargs)
    return guarded


def migration_operation(fn):
    @functools.wraps(fn)
    def guarded(args):
        source = Path(args.from_dir).expanduser().resolve()
        target = Path(args.to_dir).expanduser().resolve()
        if not args.apply or not source.exists():
            return fn(args)
        with operation_lock(source, create_state=False), operation_lock(target, create_state=False):
            root = library_root(source)
            guard = operation_lock(root, create_state=False, namespace="library") if root else contextlib.nullcontext()
            with guard:
                recover_transactions(source)
                return fn(args)
    return guarded


@contextlib.contextmanager
def parent_fd(root: Path, path: Path):
    root = Path(os.path.abspath(root))
    rel = relative(str(path.relative_to(root)))
    fd = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        # Walk from the filesystem anchor, so a renamed ancestor cannot turn the
        # root open into an implicit symlink traversal either.
        for part in (*root.parts[1:], *rel.parts[:-1]):
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        yield fd, rel.name
    finally:
        os.close(fd)


def move_no_replace(source: Path, target: Path, source_root: Path, target_root: Path) -> None:
    """Publish without overwriting, using directory handles that cannot follow symlinks.

    A crash between link and unlink leaves two copies of the same inode; recovery
    recognizes their hashes. All supported transactions stay on one filesystem.
    """
    source = inside(source_root, source.relative_to(Path(os.path.abspath(source_root))))
    target = inside(target_root, target.relative_to(Path(os.path.abspath(target_root))))
    with parent_fd(source_root, source) as (sfd, sn), parent_fd(target_root, target) as (tfd, tn):
        before = os.stat(sn, dir_fd=sfd, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Refusing to move a non-regular file")
        os.link(sn, tn, src_dir_fd=sfd, dst_dir_fd=tfd, follow_symlinks=False)
        linked = os.stat(tn, dir_fd=tfd, follow_symlinks=False)
        if (linked.st_dev, linked.st_ino) != (before.st_dev, before.st_ino):
            raise RuntimeError("File changed during installation; recovery is required")
        os.fsync(tfd)
        current = os.stat(sn, dir_fd=sfd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
            raise RuntimeError("File changed during move; both versions were preserved")
        os.unlink(sn, dir_fd=sfd)
        os.fsync(sfd)


def journal_begin(state: Path, root: Path, cid: str, source: Path, final: Path,
                  quarantine: Path, original_sha: str, final_sha: str, operation: str,
                  *, rollback_id: str | None = None) -> None:
    identifier(cid)
    data = dict(commit_id=cid, root=str(root.resolve()),
                source=str(source.relative_to(root.resolve())),
                final=str(final.relative_to(root.resolve())),
                quarantine=str(quarantine.relative_to(state.resolve())),
                original_sha=original_sha, final_sha=final_sha, operation=operation,
                rollback_id=rollback_id)
    atomic_json(inside(state, f"transactions/{cid}.json"), data)


def flush_change_log(state: Path, *, strict: bool = True) -> bool:
    import media_change_log
    try:
        media_change_log.flush_state(state)
        return True
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        if strict:
            raise RuntimeError(media_change_log.ERROR) from exc
        return False


def journal_done(state: Path, cid: str) -> None:
    # A logging failure must not undo an already committed file. Keep the
    # transaction marker so recovery can retry before session data is discarded.
    if not flush_change_log(state, strict=False):
        return
    path = inside(state, f"transactions/{identifier(cid)}.json")
    if path.exists():
        path.unlink()
        sync_directory(path.parent)


def entry_exists(path: Path) -> bool:
    try:
        return path.name in os.listdir(path.parent)
    except FileNotFoundError:
        return False


def recover_transactions(state: Path) -> None:
    directory = inside(state, "transactions")
    db = inside(state, "media-maintenance.sqlite")
    flush_change_log(state)
    if not db.exists():
        return
    with database(db) as con:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "commits" not in tables:
            return
        for cid, qtext in con.execute("SELECT commit_id,quarantine_dir FROM commits WHERE status='RUNNING'"):
            identifier(cid)
            if inside(state, f"transactions/{cid}.json").exists():
                continue
            q = inside(state, f"quarantine/{cid}")
            if Path(qtext).resolve() != q:
                raise RuntimeError("Interrupted transaction has an unsafe quarantine record")
            if q.exists() and any(p.is_file() or p.is_symlink() for p in q.rglob('*')):
                raise RuntimeError("An older interrupted transaction needs review before maintenance can continue. Its original files are retained in quarantine.")
            con.execute("UPDATE commits SET status='RECOVERED_ROLLED_BACK' WHERE commit_id=?", (cid,))
        if 'staging_runs' in tables:
            con.execute("UPDATE staging_runs SET status='INTERRUPTED' WHERE status='RUNNING'")
    if not directory.exists():
        return
    for path in sorted(directory.glob("*.json")):
        if path.is_symlink():
            raise RuntimeError("Unsafe recovery record; maintenance stopped")
        j = json.loads(path.read_text())
        cid = identifier(j["commit_id"])
        if path.name != cid + ".json":
            raise RuntimeError("Recovery record ID mismatch")
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        try:
            root_row = con.execute("SELECT value FROM meta WHERE key='root'").fetchone()
            if not root_row or Path(root_row[0]).resolve() != Path(j["root"]).resolve():
                raise RuntimeError("Recovery library does not match the state database")
            root = Path(root_row[0])
            if not root.is_dir() or root.resolve() != root:
                raise RuntimeError("Reconnect the original library before recovery; all files have been retained")
            source = inside(root, j["source"])
            final = inside(root, j["final"])
            q = inside(state, j["quarantine"])
            if q != inside(state, f"quarantine/{cid}/{j['source']}"):
                raise RuntimeError("Invalid recovery quarantine path")
            record = con.execute("SELECT status FROM commits WHERE commit_id=?", (cid,)).fetchone()
            if record and record[0] in ("COMMITTED", "ROLLED_BACK") and not j.get("rollback_id"):
                journal_done(state, cid)
                continue
            original_sha = j["original_sha"]
            same_source = entry_exists(source) and digest(source) == original_sha
            q_ok = q.exists() and digest(q) == original_sha
            # During a rename, the original may already be at its new path while
            # the rollback copy has not yet been created.
            if not q_ok and not same_source and j["operation"] == "RENAME" and entry_exists(final) and digest(final) == original_sha:
                ensure_parent(source, root)
                move_no_replace(final, source, root, root)
                same_source = True
            if not same_source:
                if not q_ok:
                    raise RuntimeError("Original identity is uncertain; all files were retained for recovery")
                if entry_exists(source) and source != final:
                    raise RuntimeError("Original pathname is occupied; recovery will not overwrite it")
                if entry_exists(final):
                    if digest(final) != j["final_sha"]:
                        raise RuntimeError("Output changed; recovery will not overwrite it")
                    held = inside(state, f"recovered-outputs/{cid}/{j['final']}")
                    ensure_parent(held, state)
                    move_no_replace(final, held, root, state)
                ensure_parent(source, root)
                move_no_replace(q, source, state, root)
            elif final != source and entry_exists(final):
                if digest(final) != j["final_sha"]:
                    raise RuntimeError("Output changed; recovery will not overwrite it")
                held = inside(state, f"recovered-outputs/{cid}/{j['final']}")
                ensure_parent(held, state)
                move_no_replace(final, held, root, state)
            temp_output = inside(root, str(final.parent.relative_to(root) / f".{final.name}.media-maintenance-{cid}.tmp"))
            if entry_exists(temp_output):
                held_temp = inside(state, f"recovered-outputs/{cid}/temporary/{temp_output.name}")
                ensure_parent(held_temp, state)
                move_no_replace(temp_output, held_temp, root, state)
            if digest(source) != original_sha:
                raise RuntimeError("Recovery hash verification failed")
            if j.get("rollback_id"):
                # Rollback may have finished filesystem restoration before SQLite.
                status = "ROLLED_BACK"
                item = con.execute("SELECT details_json,operation FROM commit_items WHERE commit_id=?", (cid,)).fetchone()
                if item:
                    details = json.loads(item[0])
                    if details.get("asset_id"):
                        con.execute("UPDATE assets SET relpath=?,active=1 WHERE asset_id=?", (j["source"], details["asset_id"]))
                        con.execute("UPDATE processing_history SET status='ROLLED_BACK' WHERE asset_id=? AND operation=? AND status='COMMITTED'", (details["asset_id"], item[1]))
                con.execute("UPDATE rollbacks SET status='ROLLED_BACK' WHERE rollback_id=?", (identifier(j['rollback_id']),))
            else:
                status = "RECOVERED_ROLLED_BACK"
            con.execute("UPDATE commits SET status=? WHERE commit_id=?", (status, cid))
            con.execute("UPDATE commit_items SET status=? WHERE commit_id=?", (status, cid))
            con.commit()
            journal_done(state, cid)
        finally:
            con.close()


def clean_environment() -> dict[str, str]:
    allowed = ("LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "SYSTEMROOT")
    env = {k: v for k, v in os.environ.items() if k in allowed}
    path = "/usr/bin:/bin" if getattr(sys, 'frozen', False) else "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    env.update(PATH=path, PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
    return env


def sandbox_command(command: list[str], reads=(), writes=(), scratch: Path | None = None) -> list[str]:
    if sys.platform != "darwin":
        raise RuntimeError("Restricted media workers require macOS")
    if not Path("/usr/bin/sandbox-exec").is_file():
        raise RuntimeError("The restricted media worker is unavailable")
    # System/runtime code can be read; personal content is granted per file.
    roots = ["/System", "/usr/lib", "/usr/share", "/Library/Apple/System/Library",
             str(Path(sys.prefix).resolve()), str(Path(sys.base_prefix).resolve())]
    if getattr(sys, "frozen", False):
        roots.append(str(Path(sys._MEIPASS).resolve()))
    else:
        roots += ["/opt/homebrew/Cellar", "/opt/homebrew/lib", "/usr/local/Cellar", "/usr/local/lib"]
    literal = lambda p: json.dumps(str(Path(p).resolve()))
    rules = ['(version 1)', '(deny default)', '(import "system.sb")', f'(allow process-exec (literal {literal(command[0])}))', '(allow process-fork)',
             '(deny network-outbound (remote ip))', '(deny network-inbound)',
             f'(allow process-exec (literal {literal(Path(sys.base_prefix) / "Resources/Python.app/Contents/MacOS/Python")}))',
             '(allow sysctl-read)', '(allow file-read-metadata)',
             '(allow file-read* (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random"))',
             '(allow file-write* (literal "/dev/null"))',
             '(allow mach-lookup (global-name "com.apple.audio.AudioComponentRegistrar"))']
    if scratch is not None:
        rules.append(f'(allow file-read* file-write* (subpath {literal(scratch)}))')
    rules += [f'(allow file-read* file-map-executable (subpath {literal(p)}))' for p in roots]
    # Only trusted module files, not the checkout or the user's home directory.
    rules += [f'(allow file-read* (literal {literal(Path(__file__).parent)}))']
    rules += [f'(allow file-read* (literal {literal(p)}))' for p in Path(__file__).parent.glob('*.py')]
    rules += [f'(allow file-read* (literal {literal(p)}))' for p in reads]
    rules += [f'(allow file-read* file-write* (literal {literal(p)}))' for p in writes]
    rules += [f'(allow file-read* (literal {literal(command[0])}))']
    return ['/usr/bin/sandbox-exec', '-p', '\n'.join(rules), *command]


def bounded_run(command: list[str], *, timeout: float = 30, max_output: int = 8 * 1024 * 1024,
                reads=(), writes=(), sandbox: bool = True) -> subprocess.CompletedProcess:
    """Drain with bounded storage and kill the entire process group on failure."""
    import selectors
    if not Path(command[0]).is_absolute():
        executable = resolve_tool(command[0])
        if not executable:
            raise OSError("Approved media executable is unavailable")
        command = [executable, *command[1:]]
    with tempfile.TemporaryDirectory(prefix="veronica-worker-") as scratch:
        env = clean_environment()
        env.update(TMPDIR=scratch, HOME=scratch, XDG_CONFIG_HOME=scratch)
        if sandbox:
            command = sandbox_command(command, reads, writes, Path(scratch))
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, env=env, start_new_session=True)
        output = [bytearray(), bytearray()]
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ, 0)
        selector.register(proc.stderr, selectors.EVENT_READ, 1)
        deadline = time.monotonic() + timeout
        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                for key, _ in selector.select(min(remaining, 0.2)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output[key.data].extend(chunk)
                    if len(output[key.data]) > max_output:
                        raise RuntimeError("Media tool output exceeded its safety limit")
            code = proc.wait(timeout=max(0.01, deadline-time.monotonic()))
            return subprocess.CompletedProcess(command, code, *(b.decode('utf-8', errors='replace') for b in output))
        finally:
            selector.close()
            # Descendants can outlive the leader and retain its pipes. Terminate
            # the isolated group even if the original process has already exited.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            proc.stdout.close()
            proc.stderr.close()


def image_request(action: str, payload: dict, reads=(), writes=()) -> dict:
    if getattr(sys, 'frozen', False):
        command = [sys.executable, '__media_worker__', action, json.dumps(payload)]
    else:
        command = [sys.executable, '-I', '-B', str(Path(__file__).with_name('media_worker.py')), action, json.dumps(payload)]
    result = bounded_run(command, timeout=120, max_output=1024*1024, reads=reads, writes=writes)
    if result.returncode:
        raise RuntimeError('Restricted image processing failed (' + str(result.returncode) + '): ' + result.stderr[-2000:])
    return json.loads(result.stdout)


def remove_staging(state: Path, sid: str) -> None:
    import shutil
    identifier(sid)
    path = inside(state, f"staging/{sid}")
    if not shutil.rmtree.avoids_symlink_attacks:
        raise RuntimeError("This Python cannot perform safe staging cleanup")
    with parent_fd(state, path) as (fd, name):
        st = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISDIR(st.st_mode):
            raise ValueError("Cleanup target is not a staging directory")
        shutil.rmtree(name, dir_fd=fd)
        os.fsync(fd)


def resolve_tool(name: str) -> str | None:
    import shutil
    if name in ('file', 'xattr'):
        candidate = Path('/usr/bin') / name
    elif getattr(sys, 'frozen', False):
        base=Path(sys._MEIPASS).resolve()
        manifest=json.loads((base/'security-manifest.json').read_text())
        expected=manifest['tools'].get(name)
        if not expected or not expected.get('path','').startswith('MediaTools/'):
            raise RuntimeError('A bundled media component is missing. Reinstall Veronica.')
        candidate=inside(base,expected['path'])
        if not candidate.is_file():return None
        if digest(candidate)!=expected['sha256']:
            raise RuntimeError('A bundled media component changed. Reinstall Veronica.')
        for path,expected_hash in expected.get('libraries',{}).items():
            library=inside(base,path)
            if not path.startswith('MediaTools/') or digest(library)!=expected_hash:
                raise RuntimeError('A bundled media library changed. Reinstall Veronica.')
    else:
        bundled = (Path(sys.executable).resolve().parent.parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent) / 'Tools' / 'bin' / name
        candidate = next((p for p in (bundled, Path('/opt/homebrew/bin') / name, Path('/usr/local/bin') / name) if p.is_file()), None)
    if candidate is None or not candidate.is_file() or not os.access(candidate, os.X_OK):
        return None
    candidate = candidate.resolve()
    if candidate.stat().st_mode & stat.S_IWOTH:
        raise RuntimeError('Media dependency is writable by other users')
    return str(candidate)


def copy_new(source: Path, target: Path, source_root: Path, target_root: Path) -> None:
    import shutil
    with parent_fd(source_root, source) as (sfd, sn), parent_fd(target_root, target) as (tfd, tn):
        source_fd = os.open(sn, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=sfd)
        try:
            if not stat.S_ISREG(os.fstat(source_fd).st_mode):
                raise ValueError('Expected regular staged data')
            target_fd = os.open(tn, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=tfd)
            with os.fdopen(target_fd, 'wb') as output, os.fdopen(source_fd, 'rb', closefd=False) as original:
                shutil.copyfileobj(original, output, length=1024*1024)
                output.flush()
                os.fsync(output.fileno())
            os.fsync(tfd)
        finally:
            os.close(source_fd)


def recover_if_idle(state: Path) -> None:
    try:
        with state_access(state):
            recover_transactions(state)
    except RuntimeError as exc:
        if str(exc).startswith('Another Veronica task'):
            return
        raise


def require_supported_runtime() -> None:
    import PIL
    version = tuple(int(n) for n in PIL.__version__.split('.')[:3])
    if sys.version_info < (3, 11) or version < (12, 3, 0):
        raise RuntimeError("Veronica requires its current bundled runtime, or Python 3.11+ with Pillow 12.3+. Use the project's supported environment.")


def ensure_parent(path: Path, root: Path, *, exclusive: bool = False) -> None:
    """Create transaction directories without following a replaced ancestor."""
    root = Path(os.path.abspath(root))
    parts = relative(str(path.relative_to(root))).parts[:-1]
    with parent_fd(root, root / '.veronica-directory-anchor') as (root_fd, _):
        fd = os.dup(root_fd)
        try:
            for index, part in enumerate(parts):
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    if exclusive and index == len(parts) - 1:
                        raise
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
        finally:
            os.close(fd)
