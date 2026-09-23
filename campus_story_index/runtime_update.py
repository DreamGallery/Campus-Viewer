"""Container-only resource initialization and scheduled, atomic publication."""
import argparse
import hashlib
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
import traceback

from .io import atomic_write
from .resource_archive import prepare_archive, prune_archives
from .audio_download import fetch_manifest

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


def input_signature(repos, manifest):
    commits = {key: subprocess.check_output(['git', '-C', str(repos / key), 'rev-parse', 'HEAD']).decode().strip()
               for key in SOURCES}
    code = hashlib.sha256()
    for path in sorted(Path(__file__).parent.rglob('*.py')):
        code.update(path.relative_to(Path(__file__).parent).as_posix().encode())
        code.update(path.read_bytes())
    # Store only a digest: configuration can include private endpoints or credentials.
    config = {k: v for k, v in os.environ.items() if k.startswith('CAMPUS_')}
    return hashlib.sha256(json.dumps({'commits': commits, 'manifest': manifest,
        'code': code.hexdigest(), 'config': config}, sort_keys=True).encode()).hexdigest()


def link_copy(src, dst):
    """Published cache files are immutable: producers replace files, never edit in place."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def publish(root, cache, repos, manifest=None, inputs=None):
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
        if inputs is not None:
            atomic_write(stage / 'update-inputs.json', {'signature': inputs})
        versions = prepare_archive(root, stage, manifest) if manifest is not None else None
        os.replace(stage, releases / name)
        if os.getenv('CAMPUS_PUBLISH_TARGET', 'local') == 'r2':
            from .r2_publish import publish_release
            publish_release(root, name)
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
            print(f'Updater: {label}', flush=True)
            status['phase'] = label
            atomic_write(root / 'status.json', status)
            (root / 'status.json').chmod(0o644)
        try:
            phase('同步文本与 masterdata')
            for key, (url, branch) in SOURCES.items():
                sync_repo(repos, key, os.getenv(f'CAMPUS_{key.upper()}_REPO', url), os.getenv(f'CAMPUS_{key.upper()}_BRANCH', branch))
            phase('检查游戏资源清单与仓库提交')
            manifest = fetch_manifest(config_repo=repos / 'toolkit', config_ref='HEAD')
            inputs = input_signature(repos, manifest)
            saved = root / 'current/update-inputs.json'
            if os.getenv('CAMPUS_FORCE_UPDATE') != '1' and saved.exists() and json.loads(saved.read_text()).get('signature') == inputs:
                status.update(state='ready', revision=manifest['revision'], release=(root / 'current').resolve().name)
                phase('仓库与游戏资源未变化，跳过构建和上传')
                return True
            atomic_write(cache / 'audio/OctoManifest.json', manifest)
            generated = cache / 'generated'
            def run(module, *args):
                command([sys.executable, '-m', 'campus_story_index' + ('.' + module if module else ''), *args])
            phase('构建剧情索引')
            run('', '--masterdata', repos / 'master', '--stories', repos / 'story', '--output', generated / 'story-index.json', '--strict')
            phase('下载语音资源')
            run('audio_download', '--adv', repos / 'adv/Resource', '--catalog', generated / 'story-index.json', '--config-repo', repos / 'toolkit', '--config-ref', 'HEAD', '--manifest', cache / 'audio/OctoManifest.json', '--output', cache / 'audio', '--workers', os.getenv('CAMPUS_DOWNLOAD_WORKERS', '4'))
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
            status.update(revision=revision, release=publish(root, cache, repos, manifest, inputs), last_success=int(time.time()), state='ready')
            phase('更新完成')
            # Previous releases remain for explicit rollback; no automatic destructive pruning.
            return True
        except Exception as exc:
            status.update(state='error', error=type(exc).__name__ + '；请查看更新器日志')
            phase(status.get('phase', '初始化'))
            print(f'Update failed during {status["phase"]}: {type(exc).__name__}', flush=True)
            # Report code locations without exception messages, locals, URLs or credentials.
            for frame in traceback.extract_tb(exc.__traceback__):
                print(f'  at {Path(frame.filename).name}:{frame.lineno} in {frame.name}', flush=True)
            return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    root = Path(os.getenv('CAMPUS_RUNTIME_ROOT', '/runtime'))
    interval = max(300, int(os.getenv('CAMPUS_UPDATE_INTERVAL', '21600')))
    while True:
        print(f'Updater: 开始检查仓库与游戏资源更新 ({time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())})', flush=True)
        ok = update(root)
        if args.once:
            return 0 if ok else 1
        delay = interval if ok else min(interval, 900)
        next_check = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(time.time() + delay))
        result = '本轮更新完成' if ok else '本轮未完成，将重试'
        print(f'Updater: {result}；下次检查 {next_check}（等待 {delay} 秒）', flush=True)
        time.sleep(delay)


if __name__ == '__main__':
    raise SystemExit(main())
