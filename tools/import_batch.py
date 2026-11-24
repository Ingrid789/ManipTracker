"""Cut the clips the page uses out of the batch in project_page_videos/ and make a poster for each.

    python3 tools/import_batch.py [name ...]        # all clips, or only the ones named

Each entry of CLIPS is  new name: (source under project_page_videos/, view, start s, end s or None, poster time as a
fraction of the cut). Views:
    wide   the whole 1440x720 frame of a G1 / H2 clip (main view, hand close-up, scene) at 1280x640
    main   the main view of a G1 / H2 clip (left 960x720) at 720x540
    left   the first view of a humanoid clip (left 640x480)
    two    a humanoid clip with two views, as it is (1280x480)
Clips are cut to the interaction (the walk in and the stand at the end are shortened), played at their own speed,
re-encoded with H.264 at 25 or 30 frames a second, without sound. Posters are 720 px wide.
Needs ffmpeg: FFMPEG=/path/to/ffmpeg, or the one of imageio-ffmpeg.
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SRC = HERE / "project_page_videos"

CLIPS = {
    # step 3, synthetic HOI: the SMPL-X humanoid, two views
    "syn_chair_overhead": ("03_chair_overhead_carry/stickman.mp4", "two", 0, None, 0.5),
    "syn_handover": ("02_handover/stickman.mp4", "two", 2, None, 0.45),
    "syn_mop": ("13_mop/stickman.mp4", "two", 2, None, 0.5),
    # step 5, other embodiments: the whole frame with the hand close-up
    "wide_g1_chair_overhead": ("03_chair_overhead_carry/g1.mp4", "wide", 4, 32, 0.46),
    "wide_h2_chair_overhead": ("03_chair_overhead_carry/h2.mp4", "wide", 2, 29, 0.45),
    # gallery, SMPL-X humanoid
    "hum_pickplace": ("01_pickplace/stickman.mp4", "left", 2, None, 0.45),
    "hum_box_push": ("06_box_push/stickman.mp4", "left", 0, None, 0.6),
    "hum_trashcan": ("04_large_object_carry/stickman.mp4", "left", 0, None, 0.5),
    "hum_floorlamp": ("05_pole_carry/stickman.mp4", "left", 0, None, 0.45),
    "hum_stairs_carry": ("08_stairs_carry/stickman.mp4", "left", 0, None, 0.5),
    "hum_yogamat": ("14_yogamat/stickman.mp4", "left", 2, None, 0.85),
    "hum_chair_spin": ("11_chair_spin/stickman.mp4", "left", 0, None, 0.5),
    # gallery, G1 + Revo2
    "g1syn_pickplace": ("01_pickplace/g1.mp4", "main", 2, 16, 0.5),
    "g1syn_handover": ("02_handover/g1.mp4", "main", 6, 43.5, 0.4),
    "g1syn_mop": ("13_mop/g1.mp4", "main", 5.5, 47, 0.5),
    "g1syn_yogamat": ("14_yogamat/g1.mp4", "main", 5, 36, 0.5),
    "g1syn_chair_sit": ("10_chair_sit/g1.mp4", "main", 2.5, 47, 0.5),
    "g1syn_soccer": ("12_soccer_kick/g1.mp4", "main", 0.5, None, 0.48),
    "g1syn_basketball": ("16_basketball/g1.mp4", "main", 5, 17, 0.68),
    "g1syn_undertable": ("17_undertable_pick/g1.mp4", "main", 2.5, 22, 0.5),
    "g1syn_stairs_carry": ("08_stairs_carry/g1.mp4", "main", 2, 35, 0.5),
    "g1syn_throw": ("15_throw/g1.mp4", "main", 5, None, 0.88),
    # gallery, H2 + Sharpa Wave
    "h2syn_pickplace": ("01_pickplace/h2.mp4", "main", 2.5, 16, 0.5),
    "h2syn_pole": ("05_pole_carry/h2.mp4", "main", 5.5, 21, 0.5),
    "h2syn_box_push": ("06_box_push/h2.mp4", "main", 4.5, 21, 0.5),
    "h2syn_chair_sit": ("10_chair_sit/h2.mp4", "main", 2.5, 49.5, 0.45),
    "h2syn_chair_spin": ("11_chair_spin/h2.mp4", "main", 11.5, 35, 0.58),
    "h2syn_yogamat": ("14_yogamat/h2.mp4", "main", 5.5, 40, 0.5),
    "h2syn_throw": ("15_throw/h2.mp4", "main", 5, None, 0.88),
    "h2syn_trashcan": ("04_large_object_carry/h2.mp4", "main", 2.5, 30.5, 0.5),
    "h2syn_stairs": ("07_stairs_walk/h2.mp4", "main", 0.5, None, 0.5),
}
VIEWS = {
    "wide": ("scale=1280:640:flags=lanczos", 25, 27),
    "main": ("crop=960:720:0:0,scale=720:540:flags=lanczos", 25, 27),
    "left": ("crop=640:480:0:0", 30, 27),
    "two": ("null", 30, 28),
}


def ffmpeg() -> str:
    if os.environ.get("FFMPEG"):
        return os.environ["FFMPEG"]
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def main() -> None:
    ff = ffmpeg()
    names = sys.argv[1:] or list(CLIPS)
    for d in ("video", "poster"):
        (HERE / "media" / d).mkdir(parents=True, exist_ok=True)
    for name in names:
        src, view, start, end, at = CLIPS[name]
        vf, fps, crf = VIEWS[view]
        dst = HERE / "media" / "video" / f"{name}.mp4"
        cut = ["-ss", str(start)] + (["-t", str(end - start)] if end else [])
        subprocess.run([ff, "-loglevel", "error", "-y", *cut, "-i", str(SRC / src), "-an", "-vf", vf, "-r", str(fps),
                        "-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(dst)], check=True)
        log = subprocess.run([ff, "-hide_banner", "-i", str(dst)], capture_output=True, text=True).stderr
        h, m, s = log.split("Duration: ")[1].split(",")[0].split(":")
        dur = int(h) * 3600 + int(m) * 60 + float(s)
        subprocess.run([ff, "-loglevel", "error", "-y", "-ss", f"{dur * at:.2f}", "-i", str(dst), "-frames:v", "1",
                        "-vf", "scale=720:-2:flags=lanczos", "-pix_fmt", "yuvj420p", "-q:v", "4",
                        str(HERE / "media" / "poster" / f"{name}.jpg")], check=True)
        print(f"{name:26s} {dur:5.1f} s  {dst.stat().st_size / 1e6:5.2f} MB")


if __name__ == "__main__":
    main()
