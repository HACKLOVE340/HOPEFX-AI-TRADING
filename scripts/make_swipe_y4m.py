#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Build the fake-camera feed that proves §18's camera path.

    python scripts/make_swipe_y4m.py

Writes `frontend/proof/swipe.y4m`: a real photograph of a hand, translated
across a plain frame, in the raw format Chromium's
`--use-file-for-fake-video-capture` reads.

## Why this exists

`npm run prove:hands` proves the DETECTOR — real model, real hand, real
browser. It does not prove the path an operator actually uses: getUserMedia to
a video element to `HandDetector` to `HandGestureSource` to `recogniseGesture`.
Shipping that path unexecuted would be the same faith-based commit that kept
these rows staged in the first place.

Chromium will serve a video file as a camera, so the camera is the only part
that stays synthetic. The HAND is not synthetic: it is MediaPipe's own
photograph, which is why the model has something real to find. A drawn hand
would test whether the model tolerates drawings.

## Why not ffmpeg

Playwright ships a minimal ffmpeg build with no `overlay` filter. Y4M is a
header, then `FRAME\\n` and three raw planes per frame, so writing it directly
is fewer moving parts than finding a second ffmpeg — and it makes the motion
exact rather than a filter expression nobody can predict.

## The motion is a swipe because the thresholds say so

`recogniseGesture` needs `SWIPE_DISTANCE` of travel inside `SWIPE_MAX_MS`, with
one axis dominant. The hand crosses most of the frame horizontally and does not
move vertically, so the track it produces clears both. A hand that merely
drifted would prove the pipeline runs and not that it recognises anything.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "frontend" / "proof" / "hand.jpg"
DEST = ROOT / "frontend" / "proof" / "swipe.y4m"

WIDTH, HEIGHT = 640, 480
#: 10fps, and the frame rate is a measurement rather than a preference.
#:
#: The detector runs at roughly 17 frames a second in this container, so a video
#: faster than that is undersampled: a 30fps version produced a two-point track
#: covering 59 pixels, and `recogniseGesture` correctly refused it. Holding each
#: position for 100ms means every position is seen.
#:
#: A real operator does not have this problem — their hand is continuously in
#: frame, so the sampling rate IS the detector's rate. It is an artifact of
#: driving a browser from a file, and the fix belongs in the file.
FPS = 15
#: 8 positions across the frame = 533ms of travel, inside `SWIPE_MAX_MS` (600).
#:
#: Eight rather than five because MediaPipe's VIDEO mode TRACKS between full
#: detections, and a hand that jumps 128 pixels between frames loses the
#: track: five positions produced four separate two-point tracks per loop,
#: each covering six pixels, as the detector kept re-acquiring. Sixty pixels a
#: frame is a motion it can follow, and is also closer to what a hand does.
#:
#: The first version was 24 frames at 15fps — a 1.6-second swipe — which
#: `recogniseGesture` also refused, and rightly: nobody swipes for a second and
#: a half. Loosening that threshold to make a proof pass would have changed what
#: a swipe means for POINTER input too, to accommodate a video file.
FRAMES = 8
#: Frames at the end with no hand — the operator lowering their hand.
#:
#: Not padding. `HandGestureSource` ends a gesture when the hand LEAVES, because
#: a hand has no pointer-up, and Chromium's fake capture device loops the file
#: forever. Without these the hand is in every frame the console ever sees, no
#: gesture ever ends, and the proof measured a detector working perfectly while
#: emitting nothing. A real swipe ends with the hand coming down; so does this.
EMPTY_TAIL_FRAMES = 5
HAND_WIDTH = 220


def _rgb_to_i420(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """BT.601, which is what a webcam frame is. Chroma is 2x2 subsampled."""
    r = rgb[:, :, 0].astype(np.float64)
    g = rgb[:, :, 1].astype(np.float64)
    b = rgb[:, :, 2].astype(np.float64)
    y = 0.299 * r + 0.587 * g + 0.114 * b
    u = -0.168736 * r - 0.331264 * g + 0.5 * b + 128.0
    v = 0.5 * r - 0.418688 * g - 0.081312 * b + 128.0

    def half(plane: np.ndarray) -> np.ndarray:
        return plane.reshape(HEIGHT // 2, 2, WIDTH // 2, 2).mean(axis=(1, 3))

    return (
        np.clip(y, 0, 255).astype(np.uint8),
        np.clip(half(u), 0, 255).astype(np.uint8),
        np.clip(half(v), 0, 255).astype(np.uint8),
    )


def build(dest: Path = DEST) -> Path:
    hand = Image.open(SOURCE).convert("RGB")
    scale = HAND_WIDTH / hand.width
    hand = hand.resize((HAND_WIDTH, max(1, int(hand.height * scale))), Image.LANCZOS)

    travel = WIDTH - hand.width
    top = max(0, (HEIGHT - hand.height) // 2)

    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as out:
        out.write(f"YUV4MPEG2 W{WIDTH} H{HEIGHT} F{FPS}:1 Ip A1:1 C420mpeg2\n".encode())
        for index in range(FRAMES + EMPTY_TAIL_FRAMES):
            canvas = Image.new("RGB", (WIDTH, HEIGHT), (110, 110, 110))
            if index < FRAMES:
                # Left to right. The console mirrors the camera, so on screen
                # this reads as a swipe LEFT — the mirroring is part of what the
                # proof checks, not an incidental detail.
                x = int(travel * index / max(FRAMES - 1, 1))
                canvas.paste(hand, (x, top))
            y_plane, u_plane, v_plane = _rgb_to_i420(np.asarray(canvas))
            out.write(b"FRAME\n")
            out.write(y_plane.tobytes())
            out.write(u_plane.tobytes())
            out.write(v_plane.tobytes())
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", default=str(DEST))
    args = ap.parse_args(argv)
    if not SOURCE.exists():
        print(f"error: {SOURCE} is missing")
        return 2
    path = build(Path(args.out))
    print(
        f"wrote {path.relative_to(ROOT)}  ({path.stat().st_size} bytes, "
        f"{FRAMES} hand frames + {EMPTY_TAIL_FRAMES} empty at {FPS}fps)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
