"""Refresh public profile quotes and media URLs from the official idol pages.
No game assets or audio are bundled; media is loaded on demand from the official site.
"""
import concurrent.futures
import html
import json
from pathlib import Path
import re
import subprocess

ORIGIN = "https://gakuen.idolmaster-official.jp"
SLUGS = dict(hski="saki", ttmr="temari", fktn="kotone", amao="mao", kllj="lilja", kcna="china", ssmk="sumika", shro="hiro", hrnm="rinami", hume="ume", hmsz="misuzu", jsna="sena", atbm="tsubame")
OUTPUT = Path(__file__).resolve().parents[1] / "campus_story_index/official_profiles.json"

def fetch(item):
    ident, slug = item
    url = ORIGIN + "/idol/" + ("" if slug == "saki" else slug + "/")
    page = subprocess.check_output(["curl", "--fail", "--silent", "--show-error", "--location", "--max-time", "30", url], text=True)
    quotes = [html.unescape(re.sub("<[^>]+>", "", line)).strip() for line in re.findall(r'<p class="idol__serif-text">(.*?)</p>', page, re.S)]
    voices = list(dict.fromkeys(re.findall(r'data-voice="(\d+)"', page)))
    photo = ORIGIN + f"/assets/img/idol/{slug}/thumb.png"
    if not quotes or photo not in page or not voices:
        raise ValueError(f"Official profile markup changed: {ident}")
    return ident, {"source_url": url, "quote": quotes, "photo": photo, "voices": [ORIGIN + f"/assets/data/voice/{slug}/voice_{voice}.mp3" for voice in voices]}

def main():
    existing = json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        profiles = dict(pool.map(fetch, SLUGS.items()))
    for ident, profile in profiles.items():
        if existing.get(ident, {}).get("introduction"):
            profile["introduction"] = existing[ident]["introduction"]
    OUTPUT.write_text(json.dumps(profiles, ensure_ascii=False, indent=2) + "\n")
    print(f"Updated {len(profiles)} official profiles")

if __name__ == "__main__":
    main()
