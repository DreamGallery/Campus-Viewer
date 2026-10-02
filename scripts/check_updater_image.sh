#!/bin/sh
set -eu
image=${1:?Usage: check_updater_image.sh IMAGE [PLATFORM]}
platform=${2:-linux/amd64}
docker run --rm -i --platform "$platform" --entrypoint python "$image" - <<'CHECK'
import importlib, pathlib, subprocess, tempfile, wave, struct
from campus_story_index.audio_extract import encode_flac
with tempfile.TemporaryDirectory() as directory:
    wav = pathlib.Path(directory) / 'test.wav'
    pcm = b''.join(struct.pack('<hh', i * 7 % 32768, -(i * 5 % 32768)) for i in range(4800))
    with wave.open(str(wav), 'wb') as output:
        output.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
        output.writeframes(pcm)
    flac = encode_flac(wav)
    assert flac.read_bytes()[:4] == b'fLaC'
    decoded = pathlib.Path(directory) / 'decoded.wav'
    subprocess.run(['flac','-d','--silent','-o',str(decoded),str(flac)],check=True)
    with wave.open(str(decoded),'rb') as result:
        assert result.readframes(4800) == pcm
        assert result.getnchannels() == 2
        assert result.getsampwidth() == 2
        assert result.getframerate() == 48000
for name in ['requests','UnityPy','PIL','Crypto.Cipher.AES','google.protobuf','boto3','campus_story_index.runtime_update','campus_story_index.music_preview','campus_story_index.music_publish','campus_story_index.r2_publish','campus_story_index.web_assets','campus_story_index.audio_extract','campus_story_index.vendor.octodb_pb2']:
    importlib.import_module(name)
result=subprocess.run(['/usr/local/bin/vgmstream-cli','-h'],capture_output=True,text=True,timeout=20)
assert 'vgmstream' in (result.stdout+result.stderr).lower(), 'Decoder cannot execute'
assert pathlib.Path('/app/scripts/verify_web_export.py').is_file()
assert not list(pathlib.Path('/app').glob('.env*')), 'Unexpected environment file in image'
assert not pathlib.Path('/app/data').exists(), 'Downloaded assets must not be bundled'
subprocess.run(['python','-m','campus_story_index.runtime_update','--help'],check=True,stdout=subprocess.DEVNULL)
print('Updater image checks passed: dependencies, decoder, entrypoint, resource/secret exclusion')
CHECK
