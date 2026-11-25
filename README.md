# ManipTracker project page

Project page for *Synthesizing Whole-Body Loco-Manipulation without Human Demonstration* (ManipSynth and ManipTracker, NeurIPS 2026).
Static files only: no build step, no CDN.

```bash
python3 -m http.server 8000     # then open http://localhost:8000/
```

(The page loads ES modules, so it needs a server; opening `index.html` from disk does not work.)

## What is on the page

1. **The first screen** (`hero.js`): a tall section whose content sticks, so the scroll position plays a 3D scene
   (a G1 humanoid doing a seven-step laundry task: open the washer, fetch the detergent, unscrew its cap, open the
   drawer, pour, close the drawer, close the door) and switches five captions: the title with the authors and the
   links, Part I grasp anchors, Part II body motion, the combined HOI demonstration, ManipTracker.
2. **Teaser, abstract, three numbers, the overview figure (Fig. 2) and the pipeline figure (Fig. 3).**
3. **The method** (`site.js`): five steps on one stage that sticks while the page scrolls through them, with a
   step rail on the left and the step's clips to choose from on the right. Steps 1 and 3 also offer a figure from
   the paper (Fig. 6 and Fig. 7).
4. **More results**: four tabs. Synthesized demonstrations for the SMPL-X humanoid, for the G1 with Revo2 hands and
   for the H2 with Sharpa Wave hands, one clip per kind of task; then long-horizon sequences and G1 body motion.
5. **In numbers**: the paper's Tables 3, 4 and 5, cut down to what the three numbers stand on.
6. **Citation** (BibTeX with a Copy button) and the acknowledgments.

| path | what |
|---|---|
| `index.html`, `site.css`, `site.js` | the page; the clip lists are `STEPS` and `SETS` at the top of `site.js` |
| `hero.js` | the 3D first screen |
| `media/hero` | its assets: robot, washer, jug and cap (`scene.glb`), the room's Gaussian splat (`room.spz`), steps, paths and anchors (`scene.json`) |
| `tools/export_hero.py` | exports `media/hero` from the ManipSynth laundry demonstration |
| `media/video`, `media/poster`, `media/img` | clips, their posters, figures |
| `20532_Synthesizing_Whole_Body_.pdf` | the paper; the Paper button links to it |
| `tools/import_media.py` | copies the clips taken from the old page (`../ManipSynth-Tracker.github.io`) under new names and cuts the posters |
| `tools/import_batch.py` | cuts the clips taken from the batch in `project_page_videos/` (view, start, end per clip), re-encodes them and cuts the posters |
| `project_page_videos/` | the batch itself: 46 clips, 339 MB, with its own `README.md` (source and check of every clip). Not in git (`.gitignore`) |
| `tools/pdf_figures.py` | cuts Fig. 3, 6 and 7 out of the paper PDF into `media/img` |
| `tools/shots.mjs` | screenshots at several scroll positions, desktop and phone, to check the layout |
| `vendor/three` | three.js r182 (MIT), with the meshopt decoder that `scene.glb` needs (`addons/libs/meshopt_decoder.module.js`) |
| `vendor/spark` | Spark 2.4.0, the Gaussian splat renderer (`@sparkjsdev/spark`, MIT) |
| `fonts` | Manrope, JetBrains Mono (OFL) |

## Where the text comes from

The title, the authors and affiliations, the abstract, the numbers and the tables follow the paper PDF in this folder.
If the paper changes, the places to update are: `<title>` and the title caption in `index.html`, `.abstract`, `dl.stats`,
`section.numbers`, the BibTeX in the footer, and (for the figures) `tools/pdf_figures.py`.

## Where the clips come from

The teaser, steps 1, 2 and 4, the last choice of step 5 and the last tab come from the old page (`tools/import_media.py`).
Step 3, the first two choices of step 5 and the first three tabs come from the batch (`tools/import_batch.py`).

| place | clips | source |
|---|---|---|
| teaser | `teaser` | old page |
| step 1, grasp anchors | `grasp_camera`, `grasp_binoculars`, `grasp_hammer` | old page; the batch has no grasp close-ups |
| step 2, body motion | `body_*` (7) | old page; the batch has no sparse-control clips |
| step 3, synthetic HOI | `syn_chair_overhead`, `syn_handover`, `syn_mop` | batch, SMPL-X humanoid, two views |
| step 4, ManipTracker | `ref_*`, `trk_*` (3 pairs) | old page; the batch has no tracked rollouts |
| step 5, other robots | `wide_g1_chair_overhead`, `wide_h2_chair_overhead` | batch, the whole frame with the hand close-up |
| | `g1_sim_pickplace`, `g1_real_large` | old page: the only real-robot footage |
| tab SMPL-X humanoid | `hum_*` (7) | batch, first view |
| tab G1 + Revo2 | `g1syn_*` (10) | batch, main view |
| tab H2 + Sharpa Wave | `h2syn_*` (9) | batch, main view |
| tab Long-horizon and body motion | `long_*` (3), `g1body_*` (4) | old page |

Things to keep in mind when changing the selection:

- The batch's clips are synthesized demonstrations that passed their checks. They are not rollouts of a tracking
  policy and not real-robot footage, and the page says so (lead text of step 5, the note under the tabs).
- The paper reports neither G1 nor H2 experiments, so step 5 and the two robot tabs are labelled "Beyond the paper".
- Left out of the batch on purpose: the humanoid's kick, balance beam and chair sit (their references start from
  AMASS mocap clips, see `PULSE/examples/plan_kick.py`, `plan_terrain.py`, `plan_chair_sit.py`) and the G1 parkour
  (edited BONES-SEED mocap). The page's title says "without human demonstration".
- Also left out: the humanoid's throw, basketball and under-table pick (no check script; the basketball clip is
  640x480 at 157 kb/s), and the H2 football kick (dark, low contrast).
- The batch's clips carry a caption baked into the picture (task, seed, time, phase).

## The 3D scene of the first screen

A G1 humanoid with Revo2 hands does a laundry task in seven steps: it opens the washing machine, fetches the
detergent jug from the counter, unscrews its cap, opens the detergent drawer, pours, closes the drawer and closes
the door. The scene is the ManipSynth demonstration `output/laundry_washer_swap/g1_laundry` (159.5 s, 7974 frames
at 50 fps), exported by `tools/export_hero.py` into `media/hero`:

| file | what | size |
|---|---|---|
| `scene.glb` | robot, washer, jug and cap, one node per MuJoCo body, meshes decimated from 1.23 M to 154 k triangles, the motion at 15 keys a second in two clips (`robot`, `scene`), packed by gltfpack with meshopt compression | 1.22 MB (0.92 MB as GitHub Pages sends it, gzipped) |
| `room.spz` | the room as Gaussian splats, 143 k of 1.17 M: the row of machines with its counter and shelf, the wall it is set into, the floor in front. The ceiling, the other walls, the far side of the room, the scanned jug and the splats of the replaced machine are left out; the floor and the wall fade out at the cut | 1.41 MB |
| `scene.json` | phases and steps of the motion, root and wrist paths of the first step, the grasp anchors | 19 kB (5 kB gzipped) |

Together 2.3 MB on the wire. The scene of the one-step door demonstration that this replaces took 11.5 MB.

```bash
npm install gltfpack                 # once; then put node_modules/.bin on PATH, or set GLTFPACK to the binary
/home/lenovo/miniconda3/envs/robosim/bin/python tools/export_hero.py    # needs mujoco, trimesh, fast_simplification
```

- **What the splat keeps**: the boxes `ROW` and `FLOOR` at the top of the script, in the row's coordinates (along the
  row, into the room, up). Widen them to show more of the room, at the cost of a larger file.
- **How small the splat is**: `KEEP` is the share of each region's splats that stays (those with the most opacity
  times area first), `BITS` the precision of positions (9: 2 mm), `COARSE` the rounding of opacity, colour, size and
  rotation. These were chosen by comparing screenshots: at `KEEP = 0.44, 0.26` the labels on the counter and the
  panels of the two scanned machines turn soft.
- **How small the mesh is**: `ratio_for()` gives the share of triangles kept per body, and the gltfpack call sets the
  bits per position (14). With 12 bits, or with half the triangles, the jug's label tears and the door seal of the
  washer breaks up.
- **Loading**: `index.html` preloads the three assets and the modules in `<head>`, so they download while the page
  is parsed instead of after `hero.js` and its imports have arrived. Add a line there if `hero.js` gains an asset.
  The largest download is now Spark itself (2.85 MB, 0.98 MB gzipped).
- **The story's timing**: `CHAPTERS` in `hero.js` holds the scroll fraction where each caption starts, and `draw()`
  maps the scroll to motion time: step 1 plays over 0.27–0.42, steps 2–6 over 0.42–0.80, step 7 over 0.80–0.985. The
  camera path is `KEYS`. The caption texts are in `index.html` (`.hud .chapter`); the pill that names the step
  ("3/7 · Unscrew the cap") is `#hero-step`, filled from `steps` in `scene.json`.
- **The anchors of Part I**: on the door they are the fitted hook grasp of `g1_open_door/grasps.json`. On the jug,
  its cap and the drawer they are the fingertip positions at the frame the hand takes hold, read from the motion.
- **The last chapter** replays the same reference motion, with a blue see-through copy of the robot a moment ahead as
  the tracking target. There is no simulated rollout of this motion yet; once there is one, bake it as a third clip
  and play it on the solid robot.
- **The length of the scroll**: `.scrolly { height }` in `site.css` (820vh for the seven steps).
- **Frame rate**: the splats are bound by fill rate. The canvas has no multisampling, and `hero.js` lowers the
  drawing resolution while the scene moves if frames come slower than about 40 a second (`STEPS`, `adapt()`); a frame
  that stays on screen is drawn at full resolution. The 60 frames a second measured on an Intel UHD 770 at 1440×810
  were with the earlier scene of 523 k splats; this one has 143 k and has not been timed on a GPU.
- Without WebGL, or if an asset fails to load, the teaser image shows instead and the captions still follow the scroll.

## Still to fill in

- Code and arXiv links: the paper gives neither, so the title caption has no such buttons yet. Add them next to the
  Paper button in `index.html` (`.chapter.title .links`), and point Paper at arXiv if preferred.
- The BibTeX is written from the PDF's title page (`@inproceedings`, NeurIPS 2026); replace it with the official entry
  once the proceedings are out.
- The page carries `noindex` (as the old one did): remove that `<meta>` when it goes public.
