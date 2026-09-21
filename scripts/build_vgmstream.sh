#!/bin/sh
# Build a local ACB/HCA decoder; no global install or external codec downloads.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
source_dir="$root/tools/vgmstream-src"
build_dir="$root/tools/vgmstream-build"
revision=764c84c5048932054356f2ea67a71ea7673abc83
if [ ! -d "$source_dir/.git" ]; then
    git clone https://github.com/vgmstream/vgmstream.git "$source_dir"
fi
if [ "$(git -C "$source_dir" rev-parse HEAD)" != "$revision" ]; then
    if [ -n "$(git -C "$source_dir" status --porcelain)" ]; then
        echo 'vgmstream source has local changes; refusing to change its revision.' >&2
        exit 1
    fi
    git -C "$source_dir" fetch origin "$revision"
    git -C "$source_dir" checkout --detach "$revision"
fi
cmake -S "$source_dir" -B "$build_dir" \
    -DBUILD_CLI=ON -DBUILD_V123=OFF -DBUILD_AUDACIOUS=OFF \
    -DUSE_MPEG=OFF -DUSE_VORBIS=OFF -DUSE_FFMPEG=OFF \
    -DUSE_G7221=OFF -DUSE_G719=OFF -DUSE_ATRAC9=OFF \
    -DUSE_CELT=OFF -DUSE_SPEEX=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build "$build_dir" --parallel 8
