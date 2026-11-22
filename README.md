# ManipTracker project page

Project page for *Synthesizing Whole-Body Loco-Manipulation without Human Demonstration* (ManipSynth and ManipTracker, NeurIPS 2026).
Static files only: no build step, no CDN.

```bash
python3 -m http.server 8000     # then open http://localhost:8000/
```

(The page loads ES modules, so it needs a server; opening `index.html` from disk does not work.)

## What is on the page

1. **The first screen** (`hero.js`): a tall section whose content sticks, so the scroll position plays a 3D scene
   (a G1 humanoid opening a washing machine in a laundry room) and switches five captions: the title with the authors and the links, Part I grasp anchors, Part II body motion,
   the combined HOI demonstration, ManipTracker.
2. **Teaser, abstract, three numbers, the overview figure (Fig. 2) and the pipeline figure (Fig. 3).**
3. **The method** (`site.js`): five steps on one stage that sticks while the page scrolls through them, with a
   step rail on the left and the step's clips to choose from on the right. Steps 1 and 3 also offer a figure from
   the paper (Fig. 6 and Fig. 7).
4. **More results**: long-horizon, push and pull, G1 body motion.
5. **In numbers**: the paper's Tables 3, 4 and 5, cut down to what the three numbers stand on.
6. **Citation** (BibTeX with a Copy button) and the acknowledgments.

| path | what |
|---|---|
| `index.html`, `site.css`, `site.js` | the page; the clip lists are `STEPS` and `SETS` at the top of `site.js` |
| `hero.js` | the 3D first screen |
| `media/hero` | its assets: robot and washer (`scene.glb`), the room's Gaussian splat (`room.spz`), paths and anchors (`scene.json`) |
| `tools/export_hero.py` | exports `media/hero` from the ManipSynth washer-door demonstration |
| `media/video`, `media/poster`, `media/img` | clips, their posters, figures |
| `20532_Synthesizing_Whole_Body_.pdf` | the paper; the Paper button links to it |
| `tools/import_media.py` | copies the clips from the old page (`../ManipSynth-Tracker.github.io`) under new names and cuts the posters |
| `tools/pdf_figures.py` | cuts Fig. 3, 6 and 7 out of the paper PDF into `media/img` |
| `tools/shots.mjs` | screenshots at several scroll positions, desktop and phone, to check the layout |
| `vendor/three` | three.js r182 (MIT) |
| `vendor/spark` | Spark 2.4.0, the Gaussian splat renderer (`@sparkjsdev/spark`, MIT) |
| `fonts` | Manrope, JetBrains Mono (OFL) |

## Where the text comes from

The title, the authors and affiliations, the abstract, the numbers and the tables follow the paper PDF in this folder.
If the paper changes, the places to update are: `<title>` and the title caption in `index.html`, `.abstract`, `dl.stats`,
`section.numbers`, the BibTeX in the footer, and (for the figures) `tools/pdf_figures.py`.

The G1 clips (step 5 and the "G1 body motion" tab) come from the old page; the paper does not report G1 or real-robot
experiments, so step 5 is labelled "Beyond the paper".

## The 3D scene of the first screen

A G1 humanoid with Revo2 hands opens a washing machine in a laundry room. The scene is the ManipSynth demonstration
`output/laundry_washer_swap/g1_open_door`, exported by `tools/export_hero.py` into `media/hero`:

| file | what | size |
|---|---|---|
| `scene.glb` | robot and washer, one node per MuJoCo body, meshes decimated from 1.1 M to 0.24 M triangles, the motion baked at 25 fps in two clips (`robot`, `door`) | 6.7 MB |
| `room.spz` | the room as Gaussian splats, 523 k of 1.17 M: the row of machines with its counter and shelf, the wall it is set into, the floor in front. The ceiling, the other walls, the far side of the room and the splats of the replaced machine are left out; the floor and the wall fade out at the cut | 7.2 MB |
| `scene.json` | phases of the motion, root and wrist paths, the grasp anchors on the door | 20 kB |

```bash
/home/lenovo/miniconda3/envs/robosim/bin/python tools/export_hero.py    # needs mujoco, trimesh, fast_simplification
```

- **What the splat keeps**: the boxes `ROW` and `FLOOR` at the top of the script, in the row's coordinates (along the
  row, into the room, up). Widen them to show more of the room, at the cost of a larger file.
- **The story's timing**: `CHAPTERS` in `hero.js` holds the scroll fraction where each caption starts, and `draw()`
  maps the scroll to motion time; the camera path is `KEYS`. The caption texts are in `index.html` (`.hud .chapter`).
- **The last chapter** replays the same reference motion, with a blue see-through copy of the robot a moment ahead as
  the tracking target. There is no simulated rollout of this motion yet; once there is one, bake it as a third clip
  and play it on the solid robot.
- **The length of the scroll**: `.scrolly { height }` in `site.css`.
- **Frame rate**: the splats are bound by fill rate. The canvas has no multisampling, and `hero.js` lowers the
  drawing resolution while the scene moves if frames come slower than about 40 a second (`STEPS`, `adapt()`); a frame
  that stays on screen is drawn at full resolution. On an Intel UHD 770 this gives 60 frames a second at 1440×810.
- Without WebGL, or if an asset fails to load, the teaser image shows instead and the captions still follow the scroll.

## Still to fill in

- Code and arXiv links: the paper gives neither, so the title caption has no such buttons yet. Add them next to the
  Paper button in `index.html` (`.chapter.title .links`), and point Paper at arXiv if preferred.
- The BibTeX is written from the PDF's title page (`@inproceedings`, NeurIPS 2026); replace it with the official entry
  once the proceedings are out.
- The page carries `noindex` (as the old one did): remove that `<meta>` when it goes public.
