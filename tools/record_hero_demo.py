"""Record the hero demo video (PRD §10, M10): the Drone Delivery template in the app, about 78 s.

    python tools/record_hero_demo.py docs/media/hero_demo.mp4 [--sweep runs/.../results.parquet]

It opens the template, runs it, and records the window from inside the app (widget grabs plus
the VTK render, so windows on top of it don't matter), with a caption per segment:

  1. the fleet: three drones with GPS + IMU EKFs in gusty wind, trails, routes, wind arrow
  2. the camera follows d0: its trail and 3-sigma covariance ellipsoid; the plot shows d0's EKF
     error against its +-3 sigma bound
  3. the Diagram tab: d0's loop as a block diagram (IMU + GPS -> EKF -> route follower -> quad)
  4. back to the fleet
  5. the sweep view: a 50-trial Monte Carlo of the delivery time (run first unless --sweep)

Needs a display and ffmpeg (on PATH or --ffmpeg). Frames are encoded on a worker thread; each
is held for the wall time it covers, so the video plays in real time.
"""

from __future__ import annotations

import argparse
import queue
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FPS = 12
OUT_WIDTH = 1280
CAPTIONS = [
    "Three delivery drones, each with its own GPS + IMU EKF, fly through gusty wind",
    "Following drone d0: its trail and the 3σ covariance ellipsoid of its estimate",
    "The plot: d0's EKF position error (x) stays inside its ±3σ bound",
    "d0 is flown by a block diagram: IMU + GPS → EKF → route follower → quadrotor",
    "The diagram flies d0 exactly as the script does (tested to 1e-9)",
    "50-trial Monte Carlo, GPS noise and gusts varied: delivery time per trial",
]


def run_sweep(folder: Path) -> Path:
    import simview as sv
    from simview.templates import scene_path

    print("running the 50-trial sweep...", flush=True)
    res = sv.sweep(
        scene_path("drone_delivery"),
        50.0,
        trials=50,
        seed=0,
        params={"gps_noise": sv.Uniform(0.4, 1.6), "gust": sv.Uniform(0.5, 3.0)},
        out=folder,
    )
    return res.path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--sweep", type=Path, help="a drone_delivery sweep's results.parquet")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    args = ap.parse_args()
    sweep = args.sweep or run_sweep(Path(tempfile.mkdtemp(prefix="hero_sweep_")))

    from qtpy.QtCore import QSettings

    import simview
    from simview.ui.app import Controller, create_app

    ini = Path(tempfile.mkdtemp(prefix="hero_ui_")) / "hero.ini"
    app = create_app([sys.argv[0]], "dark")
    ctl = Controller(QSettings(str(ini), QSettings.Format.IniFormat))
    ctl.open_template("drone_delivery")
    w = ctl.window
    avail = w.screen().availableGeometry()
    w.resize(int(avail.width() * 0.92), int(avail.height() * 0.9))
    w.move(avail.x() + 10, avail.y() + 10)

    def pump(seconds: float, each: Callable[[], None] | None = None) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            if each:
                each()
            time.sleep(0.005)

    pump(2.0)
    cam = w.sim_view.plotter.camera
    cam.zoom(2.4)
    w.sim_view.plotter.render()
    w.run()
    pump(1.0)
    w.plots.plot_signals(["d0_err_x", "d0_bound_x"])
    pump(0.5)

    fonts = Path(simview.__file__).parent / "ui" / "assets" / "fonts"
    font_file = next(iter(sorted(fonts.rglob("Inter*.ttf"))), None)
    font = ImageFont.truetype(str(font_file), 26) if font_file else ImageFont.load_default()
    out_h = round(OUT_WIDTH * w.height() / w.width()) // 2 * 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    ff = subprocess.Popen(
        [args.ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{OUT_WIDTH}x{out_h}", "-r", str(FPS), "-i", "-", "-c:v", "libx264",
         "-preset", "medium", "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         str(args.out)],
        stdin=subprocess.PIPE,
    )  # fmt: skip
    assert ff.stdin is not None
    jobs: queue.Queue = queue.Queue(maxsize=8)
    written = [0]

    def encoder() -> None:
        while (job := jobs.get()) is not None:
            t_rel, raw, size, bpl, shot, at, text = job
            img = Image.frombuffer("RGB", size, raw, "raw", "RGB", bpl)
            if shot is not None:
                img.paste(Image.fromarray(shot[..., :3]).resize(at[2:]), at[:2])
            img = img.resize((OUT_WIDTH, out_h), Image.BILINEAR)
            d = ImageDraw.Draw(img, "RGBA")
            b = d.textbbox((0, 0), text, font=font)
            tw, th = b[2] - b[0], b[3] - b[1]
            x0, y0 = (OUT_WIDTH - tw) // 2, out_h - th - 40
            box = (x0 - 18, y0 - 12, x0 + tw + 18, y0 + th + 16)
            d.rounded_rectangle(box, 10, fill=(0, 0, 0, 200))
            d.text((x0, y0 - b[1]), text, font=font, fill=(255, 255, 255, 255))
            data = img.tobytes()
            for _ in range(max(1, round(t_rel * FPS) + 1 - written[0])):
                ff.stdin.write(data)
                written[0] += 1

    worker = threading.Thread(target=encoder, daemon=True)
    worker.start()
    state = {"target": w, "caption": "", "next": 0.0, "t0": time.monotonic()}

    def capture() -> None:
        now = time.monotonic()
        if now < state["next"]:
            return
        state["next"] = max(state["next"] + 1.0 / FPS, now - 0.5)
        top = state["target"]
        q = top.grab().toImage()
        q = q.convertToFormat(q.Format.Format_RGB888)
        shot = at = None
        if top is w and w.central_pages.currentIndex() == 0:  # the 3D page: paste VTK's render
            vp = w.sim_view
            shot = np.asarray(vp.plotter.screenshot(return_img=True))
            pos = vp.mapTo(w, vp.rect().topLeft())
            k = q.width() / w.width()
            at = (round(pos.x() * k), round(pos.y() * k), round(vp.width() * k),
                  round(vp.height() * k))  # fmt: skip
        raw = bytes(q.constBits())
        size = (q.width(), q.height())
        jobs.put((now - state["t0"], raw, size, q.bytesPerLine(), shot, at, state["caption"]))

    hist = w.plots.history

    def track() -> None:
        """Ease the camera toward drone d0 (focal point and position move together)."""
        p = [float(hist.signal(f"d0.{a}")[-1]) for a in "xyz"]
        f = cam.focal_point
        d = [0.25 * (p[i] - f[i]) for i in range(3)]
        cam.focal_point = [f[i] + d[i] for i in range(3)]
        cam.position = [cam.position[i] + d[i] for i in range(3)]

    def rec(seconds: float, each: Callable[[], None] | None = None, caption: str = "") -> None:
        if caption:
            state["caption"] = caption

        def tick() -> None:
            if each:
                each()
            capture()

        pump(seconds, tick)

    state["t0"] = time.monotonic()
    rec(18.0, caption=CAPTIONS[0])
    state["caption"] = CAPTIONS[1]
    for _ in range(40):  # zoom in on d0
        cam.zoom(1.035)
        rec(1.3 / 40, track)
    rec(7.0, track)
    rec(8.0, track, CAPTIONS[2])
    w.show_central(1)
    rec(12.0, caption=CAPTIONS[3])
    w.show_central(0)
    state["caption"] = CAPTIONS[4]
    for _ in range(40):  # back out to the fleet
        cam.zoom(1 / 1.035)
        rec(1.0 / 40)
    rec(9.0)
    w.pause()
    view = w.open_sweep(sweep)
    view.setGeometry(w.geometry())
    view.metric_box.setCurrentText("delivery_time")
    view.param_box.setCurrentText("gust")
    state["target"] = view
    rec(12.4, caption=CAPTIONS[5])

    jobs.put(None)
    worker.join()
    ff.stdin.close()
    ff.wait(timeout=120)
    print(f"{args.out}: {written[0] / FPS:.0f} s, {args.out.stat().st_size / 1e6:.1f} MB")
    view.close()
    w.close()
    pump(0.5)


if __name__ == "__main__":
    main()
