"""Build a portable source package from an explicit, credential-free allowlist."""
import argparse
from pathlib import Path
import tarfile


def package(output):
    root = Path(__file__).resolve().parents[1]
    allowed = ['README.md', '.gitignore', '.dockerignore', '.env.oauth.example',
               'campus_story_index', 'docker', 'deploy', 'docs', 'tests', 'scripts',
               'requirements.txt', 'requirements-audio.txt', 'requirements-assets.txt', 'requirements-dev.txt',
               'src', 'server', 'public/theme-init.js', 'public/images/icon', 'public/images/filters',
               'public/images/official', 'public/images/img_pattern_artdeco.png',
               'public/images/bg_character_standing.png', 'public/fonts',
               'package.json', 'package-lock.json', 'Dockerfile', 'index.html', 'vite.config.ts',
               'tsconfig.json', 'tsconfig.app.json', 'tsconfig.node.json',
               'postcss.config.js', 'tailwind.config.js', 'eslint.config.js']
    def safe(info):
        parts = Path(info.name).parts
        if '__pycache__' in parts or '.DS_Store' in parts or info.issym() or info.islnk(): return None
        if any(p.startswith('.env') and not p.endswith('.example') for p in parts): return None
        if info.name.endswith(('.pyc', '.log')): return None
        info.uid = info.gid = 0; info.uname = info.gname = ''
        return info
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, 'w:gz') as archive:
        for relative in allowed:
            archive.add(root / relative, arcname='campus-story/' + relative, filter=safe)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('release/campus-story-deploy.tar.gz'))
    print(package(parser.parse_args().output))
