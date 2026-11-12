"""ひまわりが撮った地球の一日を短い動画にする。

荒れた日（正直・うるさい）は、途中から太陽が画面に割り込んでくる。
"""
from __future__ import annotations

import datetime as dt
import io
import subprocess
import tempfile
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from .mood import SHOJIKI, URUSAI

HIMAWARI = "https://www.data.jma.go.jp/mscweb/data/himawari/img/fd_/fd__trm_{hhmm}.jpg"
SDO_SUN = "https://sdo.gsfc.nasa.gov/assets/img/latest/latest_1024_0193.jpg"
SIZE = 1080
FPS = 12
STEP_MIN = 20  # 何分おきのコマを使うか（10の倍数）

CREDIT_EARTH = "Earth: JMA / NOAA NESDIS / CSU CIRA (Himawari)"
CREDIT_SUN = "Sun: NASA/SDO and the AIA science team"


def slots(now: dt.datetime) -> list[str]:
    """直近24時間ぶんの HHMM を古い順に。ファイルは HHMM で上書きされていく。"""
    start = now - dt.timedelta(hours=24)
    start = start.replace(minute=(start.minute // 10) * 10, second=0, microsecond=0) + dt.timedelta(minutes=10)
    out = []
    t = start
    while t <= now - dt.timedelta(minutes=30):  # 直近30分はまだ上がっていないことがある
        out.append(t.strftime("%H%M"))
        t += dt.timedelta(minutes=STEP_MIN)
    return out


def _download(url: str) -> Image.Image | None:
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200 or len(r.content) < 5000:
            return None
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception:
        return None


def _circle(img: Image.Image, d: int) -> Image.Image:
    img = img.resize((d, d))
    mask = Image.new("L", (d, d), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, d - 1, d - 1), fill=255)
    out = Image.new("RGBA", (d, d))
    out.paste(img, (0, 0), mask)
    return out


def _font(size: int):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def render_frames(earth: list[Image.Image], sun: Image.Image | None, outdir: Path) -> int:
    font = _font(22)
    credit = CREDIT_EARTH + ("   " + CREDIT_SUN if sun else "")
    n = len(earth)
    hold = FPS * 2  # 最後に2秒止める
    idx = 0
    for i in range(n + hold):
        src = earth[min(i, n - 1)]
        frame = Image.new("RGB", (SIZE, SIZE), "black")
        frame.paste(src.resize((SIZE, SIZE)), (0, 0))
        if sun is not None:
            # 三分の一を過ぎたら右上から太陽が入ってきて、だんだん大きくなる
            p = (min(i, n - 1) / max(n - 1, 1) - 1 / 3) * 1.5
            if p > 0:
                d = int(120 + 260 * min(p, 1))
                disc = _circle(sun, d)
                frame.paste(disc, (SIZE - d - 30, 30), disc)
        ImageDraw.Draw(frame).text((24, SIZE - 40), credit, fill=(160, 160, 160), font=font)
        frame.save(outdir / f"f{idx:04d}.jpg", quality=92)
        idx += 1
    return idx


def encode(frames_dir: Path, out: Path) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
        "-i", str(frames_dir / "f%04d.jpg"),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out),
    ], check=True)


def make_video(mood: str, out: Path, now: dt.datetime | None = None,
               earth_frames: list[Image.Image] | None = None,
               sun_image: Image.Image | None = None) -> Path | None:
    """動画を作って path を返す。地球の絵が足りない日は None（文字だけ投稿する）。"""
    now = now or dt.datetime.now(dt.timezone.utc)
    if earth_frames is None:
        earth_frames = [img for hhmm in slots(now) if (img := _download(HIMAWARI.format(hhmm=hhmm)))]
    if len(earth_frames) < 12:
        return None
    sun = None
    if mood in (SHOJIKI, URUSAI):
        sun = sun_image if sun_image is not None else _download(SDO_SUN)
    with tempfile.TemporaryDirectory() as tmp:
        render_frames(earth_frames, sun, Path(tmp))
        encode(Path(tmp), out)
    return out
