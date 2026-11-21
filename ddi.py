#!/usr/bin/env python3
"""Download the developer image the runner needs (fork/ddi.rs mounts it), once, with pinned hashes.

The same snapshot of Apple's signed image Pallas's Mac installer uses; iOS verifies its
personalized ticket, and the hashes pin the download.
"""
import hashlib
import os
from pathlib import Path
import urllib.request

BASE = ('https://raw.githubusercontent.com/doronz88/DeveloperDiskImage/e2aaeac89ca8fa56c2fa1f144d182994e07a525b/'
        'PersonalizedImages/Xcode_iOS_DDI_Personalized/')
FILES = {
    'Image.dmg': '05fd807da5e19f030fa4941f24800c965c6c77982ab572dd5d1ef778fb69f9ca',
    'Image.dmg.trustcache': '36af60889ff5a737874a26daeb8e1a0139ebfebec6ec2e4d8f6a3c1bf1dce35c',
    'BuildManifest.plist': '8edd4a2f4f4ef1fbd7bfe49785d8badc673d1395d1d94d85b132ca8ab5ecaf54',
}


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    home = Path(os.environ.get('PALLAS_SIGN_HOME', '/root/.pallasboot')) / 'ddi'
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name, want in FILES.items():
        path = home / name
        if path.is_file() and digest(path) == want:
            continue
        print('正在下载开发者运行环境', name, flush=True)
        part = path.with_suffix(path.suffix + '.part')
        with urllib.request.urlopen(BASE + name, timeout=120) as res, open(part, 'wb') as out:
            while chunk := res.read(1 << 20):
                out.write(chunk)
        if digest(part) != want:
            part.unlink(missing_ok=True)
            raise SystemExit('Stopped: 开发者运行环境校验失败')
        os.replace(part, path)


if __name__ == '__main__':
    main()
