"""Copy the clips and figures this page uses from the old project page and cut a poster for each clip.

    python3 tools/import_media.py [path/to/ManipSynth-Tracker.github.io]

Clips land in media/video/, posters (the frame at 40%, 720 px wide) in media/poster/, figures in media/img/.
Needs opencv-python for the posters.
"""
import shutil
import sys
from pathlib import Path

import cv2

HERE = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "ManipSynth-Tracker.github.io"
V = SRC / "static" / "videos"

# new name -> old path under static/videos
CLIPS = {
    "teaser": "teaser_video.mp4",
    # Part I: grasp anchors (front view + top view of the grasp)
    "grasp_camera": "part2_camera_handover.mp4",
    "grasp_binoculars": "part2_binoculars_handover.mp4",
    "grasp_hammer": "part2_hammer_pickplace.mp4",
    # Part II: body motion from sparse controls
    "body_root_lwrist_rwrist": "part1_root_rwrist_lwrist.mp4",
    "body_root_rwrist": "part1_root_rwrist.mp4",
    "body_root_lwrist": "part1_root_lwrist.mp4",
    "body_lwrist_rwrist": "part1_lwrist_rwrist.mp4",
    "body_root": "part1_root.mp4",
    "body_lwrist": "part1_lwrist.mp4",
    "body_rwrist": "part1_rwrist.mp4",
    # combined: synthetic HOI trajectories
    "hoi_clothesstand": "part2_clothesstand_pickplace.mp4",
    "hoi_woodchair": "part2_woodchair_pickplace.mp4",
    "hoi_largetable": "part2_largetable_pickplace.mp4",
    # ManipTracker: the reference and the tracked rollout
    "ref_clothesstand": "part3_clothesstand_manipsynth.mp4",
    "trk_clothesstand": "part3_clothesstand_maniptracker.mp4",
    "ref_woodchair": "part3_woodchair_manipsynth.mp4",
    "trk_woodchair": "part3_woodchair_maniptracker.mp4",
    "ref_largetable": "part3_largetable_manipsynth.mp4",
    "trk_largetable": "part3_largetable_maniptracker.mp4",
    # G1
    "g1_sim_pickplace": "g1_interaction/web/simulation_pick_place.mp4",
    "g1_real_large": "g1_interaction/web/real_world_large_object.mp4",
    "g1_sim_tabletop": "g1_interaction/web/simulation_table.mp4",
    "g1_real_tabletop": "g1_interaction/web/real_world_tabletop.mp4",
    # gallery
    "long_woodchair": "woodchair_long.mp4",
    "long_largetable": "largetable_long.mp4",
    "long_plasticbox": "plasticbox_long.mp4",
    "push_grasp2_forward": "smplx_push_pull/hex0_grasp2_human_forward.mp4",
    "push_grasp2_backward": "smplx_push_pull/hex0_grasp2_human_backward.mp4",
    "push_grasp3_forward": "smplx_push_pull/hex0_grasp3_human_forward.mp4",
    "push_grasp3_backward": "smplx_push_pull/hex0_grasp3_human_backward.mp4",
    "g1body_root": "demo/root.mp4",
    "g1body_lwrist": "demo/left_wrist_bones_seed_g1_reaching_up_R_003__A054_M.mp4",
    "g1body_root_lwrist": "demo/root_left_wrist_bones_seed_g1_reaching_up_R_003__A054_M.mp4",
    "g1body_wrists": "demo/two_wrists_bones_seed_g1_thinking_R_007__A053.mp4",
    "g1body_root_wrists_look": "demo/root_two_wrists_bones_seed_g1_looking_around_horizontally_002__A053.mp4",
    "g1body_root_wrists_salute": "demo/root_two_wrists_bones_seed_g1_salute_005__A053_M.mp4",
    "g1body_rwrist_writing": "demo/rl-video-step-3-writing-down.mp4",
}
IMAGES = {"overview.jpg": "page_overview.jpg", "teaser.png": "page_teaser.png", "icon.png": "manipsynth_icon.png"}


def main() -> None:
    for d in ("video", "poster", "img"):
        (HERE / "media" / d).mkdir(parents=True, exist_ok=True)
    for name, old in CLIPS.items():
        dst = HERE / "media" / "video" / f"{name}.mp4"
        shutil.copyfile(V / old, dst)
        cap = cv2.VideoCapture(str(dst))
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) * 0.4))
        ok, frame = cap.read()
        if not ok:
            raise SystemExit(f"no frame in {old}")
        h, w = frame.shape[:2]
        frame = cv2.resize(frame, (720, round(h * 720 / w)), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(HERE / "media" / "poster" / f"{name}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
    for new, old in IMAGES.items():
        shutil.copyfile(SRC / "static" / "images" / old, HERE / "media" / "img" / new)
    print(f"{len(CLIPS)} clips, {len(IMAGES)} images -> {HERE / 'media'}")


if __name__ == "__main__":
    main()
