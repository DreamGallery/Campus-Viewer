#!/bin/sh
# Fixed upstream source; only the formats used by the audio pipeline are enabled.
set -eu
version=8.1.3
sha256=7138d28c96d9d3e3af4ee3d8cad72741f8ffb40da90c1112235dea3ecd3178a3
build_root=${1:-/build/ffmpeg-audio}
prefix=${2:-/opt/ffmpeg-audio}
mkdir -p "$build_root" "$prefix/share/licenses/ffmpeg"
cd "$build_root"
curl --fail --location --retry 3 --connect-timeout 30 --max-time 300 \
    "https://ffmpeg.org/releases/ffmpeg-$version.tar.xz" -o source.tar.xz
printf '%s  source.tar.xz\n' "$sha256" | sha256sum -c -
tar -xf source.tar.xz
cd "ffmpeg-$version"
./configure --prefix="$prefix" \
    --disable-everything --disable-autodetect --disable-doc --disable-debug \
    --disable-network --disable-avdevice --disable-swscale \
    --disable-programs --enable-ffmpeg --enable-ffprobe \
    --disable-shared --enable-static --enable-small --enable-libmp3lame \
    --enable-protocol=file,pipe \
    --enable-demuxer=wav,mp3,mov,flac \
    --enable-muxer=wav,mp3,mp4,flac,null \
    --enable-parser=mpegaudio,aac,flac \
    --enable-decoder=pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le,mp3float,aac,flac \
    --enable-encoder=pcm_s16le,libmp3lame,aac,flac \
    --enable-filter=aresample,aformat,anull,abuffer,abuffersink
make -j "${CAMPUS_BUILD_JOBS:-4}"
make install
cp COPYING.LGPLv2.1 "$prefix/share/licenses/ffmpeg/"
printf 'FFmpeg %s\nSource: https://ffmpeg.org/releases/ffmpeg-%s.tar.xz\nSHA256: %s\nBuild: scripts/build_ffmpeg_audio.sh in Campus-Viewer\n' \
    "$version" "$version" "$sha256" > "$prefix/share/licenses/ffmpeg/SOURCE.txt"
# Static FFmpeg libraries are linked into the executables; retain only runtime files.
rm -rf "$prefix/lib" "$prefix/include" "$prefix/share/ffmpeg" "$prefix/share/man"
