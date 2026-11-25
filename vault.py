"""Keep a copy of the signer's files in this device's keychain, through the plugin and Pallas.

Deleting Pallas deletes its Linux home, and with it the pairing record, the Apple session and the
certificate key; the runner on the phone stays. With this copy a reinstall needs no new pairing or
sign-in. Only small files that cannot be made again go in: the developer image (ddi/) downloads again.
"""
import base64
import gzip
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import tarfile

HOME = Path(os.environ.get('PALLAS_SIGN_HOME', '/root/.pallasboot'))
# The digest of the last copy kept, so an unchanged home is not written again.
DIGEST = '.vault-digest'
SKIP_DIRS = {'ddi', 'bin', '__pycache__'}
SKIP_NAMES = {'.writable', DIGEST}
SKIP_SUFFIXES = ('.log', '.part', '.tmp', '.lock')
LIMIT = 768 * 1024
# A previously saved copy may predate the current workspace permission checks.
RAW_LIMIT = 16 * 1024 * 1024


def has_state(home=HOME):
    """A pairing record or an Apple session: what a reinstall would make the person do again."""
    try:
        return any(p.is_file() for p in home.glob('*pair*')) or \
            any(p.is_file() for p in home.glob('isideload/**/pallas_token.json')) or \
            any(p.is_file() for p in home.glob('isideload/**/developer_session.json'))
    except OSError:
        return False


def _files(home):
    for path in sorted(home.rglob('*')):
        rel = path.relative_to(home)
        if rel.parts[0] in SKIP_DIRS or path.name in SKIP_NAMES or path.name.endswith(SKIP_SUFFIXES):
            continue
        if path.is_file() and not path.is_symlink():
            yield path, rel


def pack(home=HOME):
    """The files as an uncompressed tar with fixed times and owners, so the same files give the same bytes."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w', format=tarfile.PAX_FORMAT) as tar:
        for path, rel in _files(home):
            info = tarfile.TarInfo(rel.as_posix())
            info.size, info.mode, info.mtime = path.stat().st_size, 0o600, 0
            if raw.tell() + info.size + tarfile.RECORDSIZE > RAW_LIMIT:
                raise ValueError('signing data exceeds backup limit')
            with path.open('rb') as data:
                tar.addfile(info, data)
    return raw.getvalue()


def backup(call, home=HOME):
    """Keep the current files when they changed. `call(**args)` posts to the plugin and returns its data."""
    if not has_state(home):
        return 'nothing'
    raw = pack(home)
    digest = hashlib.sha256(raw).hexdigest()
    mark = home / DIGEST
    try:
        if mark.read_text() == digest:
            return 'unchanged'
    except OSError:
        pass
    value = base64.b64encode(gzip.compress(raw, mtime=0)).decode('ascii')
    if len(value) > LIMIT:
        return 'too_large'
    if not call(action='vault-save', value=value).get('supported'):
        return 'unsupported'
    mark.write_text(digest)
    return 'saved'


def _members(tar):
    for member in tar.getmembers():
        name = PurePosixPath(member.name)
        if not member.isfile() or name.is_absolute() or '..' in name.parts or not name.parts:
            raise ValueError('unexpected entry in the keychain copy')
        yield member


def restore(call, home=HOME):
    """Put the kept files back when the home has neither a pairing record nor an Apple session."""
    if has_state(home):
        return 'present'
    reply = call(action='vault-read')
    value = reply.get('value') if reply.get('supported') else ''
    if not value:
        return 'none'
    if len(value) > LIMIT:
        raise ValueError('oversized keychain copy')
    with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(value, validate=True))) as archive:
        raw = archive.read(RAW_LIMIT + 1)
    if len(raw) > RAW_LIMIT:
        raise ValueError('oversized keychain archive')
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as tar:
        members = list(_members(tar))
        tar.extractall(home, members=members, filter='data')
    for member in members:
        target = home / member.name
        target.chmod(0o600)
        for parent in target.relative_to(home).parents:
            if str(parent) != '.':
                (home / parent).chmod(0o700)
    (home / DIGEST).write_text(hashlib.sha256(raw).hexdigest())
    return f'restored {len(members)}'


def quietly(step, call, home=HOME):
    """Never let the copy stop an install; say what happened in the job log."""
    try:
        result = step(call, home)
    except Exception as error:  # noqa: BLE001 - any failure here only costs the copy
        result = 'failed: ' + type(error).__name__
    if result not in ('nothing', 'unchanged', 'present', 'none'):
        print('钥匙串备份', step.__name__, result, flush=True)
    return result
