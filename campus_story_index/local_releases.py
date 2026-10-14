"""Retention for updater-owned local releases, called while holding update.lock."""
import os
from pathlib import Path
import re
import shutil
import stat


KEEP_ENV = 'CAMPUS_LOCAL_RELEASES_KEEP'
RELEASE_NAME = re.compile(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}')


def retention_count():
    try:
        count = int(os.getenv(KEEP_ENV, '2'))
        if count >= 0:
            return count
    except ValueError:
        pass
    raise ValueError(f'{KEEP_ENV} 必须为非负整数（0 关闭自动清理）')


def prune_local_releases(root: Path, keep: int):
    """Always pin current; cleanup failures must not invalidate a successful publish."""
    if keep <= 0:
        return
    releases, pointer = root / 'releases', root / 'current'
    try:
        if releases.is_symlink() or not pointer.is_symlink():
            return
        current = pointer.resolve(strict=True)
        if current.parent != releases.resolve(strict=True) or not RELEASE_NAME.fullmatch(current.name):
            return
        candidates = []
        for path in releases.iterdir():
            if not RELEASE_NAME.fullmatch(path.name):
                continue
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode) and not path.is_mount():
                candidates.append((info.st_mtime_ns, path.name, path))
        if not any(path.name == current.name for _, _, path in candidates):
            return
        previous = sorted((item for item in candidates if item[1] != current.name), reverse=True)
        removed = failed = 0
        for _, _, path in previous[keep - 1:]:
            # The update lock protects normal writers; also stop on an external pointer change.
            if pointer.resolve(strict=True) != current or releases.is_symlink():
                print('Updater: 本地 releases 指针变化，停止清理', flush=True)
                return
            try:
                if path.is_symlink() or path.is_mount():
                    continue
                shutil.rmtree(path)
                removed += 1
            except OSError as exc:
                failed += 1
                print(f'Updater: 本地旧版本清理失败（{type(exc).__name__}），下轮重试', flush=True)
        if removed or failed:
            print(f'Updater: 本地 releases 已删除 {removed} 个旧版本，保留 {len(candidates) - removed} 个版本', flush=True)
    except (OSError, RuntimeError) as exc:
        print(f'Updater: 跳过本地 releases 清理（{type(exc).__name__}），下轮重试', flush=True)
