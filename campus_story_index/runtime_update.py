"""Container-only resource initialization and scheduled, atomic publication."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from .io import atomic_write
from .resource_archive import prepare_archive, prune_archives

SOURCES = {
    'master': ('https://github.com/vertesan/gakumasu-diff.git', 'main'),
    'story': ('https://github.com/DreamGallery/Campus-Story.git', 'main'),
    'adv': ('https://github.com/DreamGallery/Campus-adv-txts.git', 'main'),
    'toolkit': ('https://github.com/DreamGallery/HatsuboshiToolkit.git', 'resource'),
}


def command(args, cwd=None):
    subprocess.run([str(a) for a in args], cwd=cwd, check=True, timeout=6 * 3600,
                   env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})


def sync_repo(root, key, url, branch):
    target = root / key
    # These checkouts belong exclusively to the updater, never to an operator's worktree.
    if not (target / '.git').exists():
        temp = root / (key + '.clone')
        if temp.exists():
            shutil.rmtree(temp)
        command(['git', 'clone', '--branch', branch, '--single-branch', url, temp])
        os.replace(temp, target)
    else:
        dirty = subprocess.check_output(['git', '-C', str(target), 'status', '--porcelain'])
        if dirty.strip():
            raise RuntimeError(f'{key}: checkout has local changes; refusing update')
        command(['git', '-C', target, 'fetch', 'origin', f'{branch}:refs/remotes/origin/{branch}'])
        command(['git', '-C', target, 'checkout', '--detach', f'refs/remotes/origin/{branch}'])
    return target


def link_copy(src, dst):
    """Published cache files are immutable: producers replace files, never edit in place."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def publish(root, cache, repos, manifest=None):
    releases = root / 'releases'
    releases.mkdir(exist_ok=True)
    name = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + uuid.uuid4().hex[:8]
    stage = releases / ('.' + name)
    stage.mkdir()
    try:
        shutil.copytree(cache / 'web', stage / 'web', copy_function=link_copy)
        shutil.copytree(cache / 'audio/clips', stage / 'audio', copy_function=link_copy)
        shutil.copytree(repos / 'story/CSV', stage / 'story/CSV')
        shutil.copytree(repos / 'adv/Resource', stage / 'adv')
        versions = prepare_archive(root, stage, manifest) if manifest is not None else None
        os.replace(stage, releases / name)
        temp = root / '.current-next'
        temp.unlink(missing_ok=True)
        temp.symlink_to(Path('releases') / name, target_is_directory=True)
        os.replace(temp, root / 'current')
        if versions is not None:
            prune_archives(root, versions)
        return name
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def update(root):
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'update.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another update is running; skipped', flush=True)
            return False
        cache, repos = root / 'cache', root / 'repos'
        cache.mkdir(exist_ok=True); repos.mkdir(exist_ok=True)
        previous = json.loads((root / 'status.json').read_text()) if (root / 'status.json').exists() else {}
        status = {'state': 'updating' if (root / 'current').exists() else 'initializing',
                  'started_at': int(time.time()), 'last_success': previous.get('last_success'),
                  'release': previous.get('release')}
        def phase(label):
            status['phase'] = label
            atomic_write(root / 'status.json', status)
            (root / 'status.json').chmod(0o644)
        try:
            phase('同步文本与 masterdata')
            for key, (url, branch) in SOURCES.items():
                sync_repo(repos, key, os.getenv(f'CAMPUS_{key.upper()}_REPO', url), os.getenv(f'CAMPUS_{key.upper()}_BRANCH', branch))
            generated = cache / 'generated'
            def run(module, *args):
                command([sys.executable, '-m', 'campus_story_index' + ('.' + module if module else ''), *args])
            phase('构建剧情索引')
            run('', '--masterdata', repos / 'master', '--stories', repos / 'story', '--output', generated / 'story-index.json', '--strict')
            phase('下载语音资源')
            run('audio_download', '--adv', repos / 'adv/Resource', '--catalog', generated / 'story-index.json', '--config-repo', repos / 'toolkit', '--config-ref', 'HEAD', '--refresh-manifest', '--manifest', cache / 'audio/OctoManifest.json', '--output', cache / 'audio', '--workers', os.getenv('CAMPUS_DOWNLOAD_WORKERS', '4'))
            phase('解包语音')
            run('audio_extract', '--directory', cache / 'audio', '--decoder', os.getenv('CAMPUS_DECODER', '/usr/local/bin/vgmstream-cli'), '--workers', os.getenv('CAMPUS_EXTRACT_WORKERS', '2'))
            phase('生成语音对应索引')
            run('voice_index', '--catalog', generated / 'story-index.json', '--stories', repos / 'story', '--adv', repos / 'adv/Resource', '--audio-root', cache / 'audio', '--output', generated / 'voice-index')
            phase('下载和解包网页图片')
            run('web_assets', '--catalog', generated / 'story-index.json', '--manifest', cache / 'audio/OctoManifest.json', '--cache', cache / 'images/bundles', '--output', cache / 'web/assets')
            phase('生成并检查网页目录')
            run('web_export', '--catalog', generated / 'story-index.json', '--masterdata', repos / 'master', '--stories', repos / 'story', '--assets', cache / 'web/assets/manifest.json', '--voices', generated / 'voice-index/manifest.json', '--output', cache / 'web/catalog')
            command([sys.executable, '/app/scripts/verify_web_export.py', '--catalog', generated / 'story-index.json', '--web', cache / 'web'])
            phase('打包并发布资源版本')
            manifest = json.loads((cache / 'audio/OctoManifest.json').read_text())
            revision = manifest['revision']
            status.update(revision=revision, release=publish(root, cache, repos, manifest), last_success=int(time.time()), state='ready')
            phase('更新完成')
            # Previous releases remain for explicit rollback; no automatic destructive pruning.
            return True
        except Exception as exc:
            status.update(state='error', error=type(exc).__name__ + '；请查看更新器日志')
            phase(status.get('phase', '初始化'))
            print(f'Update failed during {status["phase"]}: {type(exc).__name__}', flush=True)
            return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    root = Path(os.getenv('CAMPUS_RUNTIME_ROOT', '/runtime'))
    interval = max(300, int(os.getenv('CAMPUS_UPDATE_INTERVAL', '21600')))
    while True:
        ok = update(root)
        if args.once:
            return 0 if ok else 1
        time.sleep(interval if ok else min(interval, 900))


if __name__ == '__main__':
    raise SystemExit(main())
