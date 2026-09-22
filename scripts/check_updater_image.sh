#!/bin/sh
set -eu
image=${1:?Usage: check_updater_image.sh IMAGE [PLATFORM]}
platform=${2:-linux/amd64}
docker run --rm -i --platform "$platform" --entrypoint python "$image" - <<'CHECK'
import importlib, pathlib, subprocess
for name in ['requests','UnityPy','PIL','Crypto.Cipher.AES','google.protobuf','boto3','campus_story_index.runtime_update','campus_story_index.r2_publish','campus_story_index.web_assets','campus_story_index.audio_extract','campus_story_index.vendor.octodb_pb2']:
    importlib.import_module(name)
result=subprocess.run(['/usr/local/bin/vgmstream-cli','-h'],capture_output=True,text=True,timeout=20)
assert 'vgmstream' in (result.stdout+result.stderr).lower(), 'Decoder cannot execute'
assert pathlib.Path('/app/scripts/verify_web_export.py').is_file()
assert not list(pathlib.Path('/app').glob('.env*')), 'Unexpected environment file in image'
assert not pathlib.Path('/app/data').exists(), 'Downloaded assets must not be bundled'
subprocess.run(['python','-m','campus_story_index.runtime_update','--help'],check=True,stdout=subprocess.DEVNULL)
print('Updater image checks passed: dependencies, decoder, entrypoint, resource/secret exclusion')
CHECK
