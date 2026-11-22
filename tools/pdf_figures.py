"""Cut the figures this page uses out of the paper PDF.

    python3 tools/pdf_figures.py [path/to/paper.pdf]

Each figure is a page number and a vertical band in PDF points (72 per inch, from the top of the page); the band is
rendered at 300 dpi, trimmed to its ink and saved to media/img/. A 360 px thumbnail goes to media/poster/fig_<name>.jpg
for the figures the method stage offers as a choice. Needs pdftoppm (poppler-utils) and opencv-python.
If the PDF changes (camera-ready), check the page numbers and bands below.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent.parent
PDF = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "20532_Synthesizing_Whole_Body_.pdf"
DPI = 300

# name -> (page, top, bottom, thumbnail?)
FIGURES = {
    "pipeline": (5, 60, 280, False),   # Fig. 3: Part I + Part II -> Combine
    "anchors": (15, 60, 228, True),    # Fig. 6: grasp anchor synthesis in detail
    "augment": (15, 268, 546, True),   # Fig. 7: one template, varied grasp, pre-grasp motion and transport path
}

with tempfile.TemporaryDirectory() as tmp:
    for name, (page, top, bottom, thumb) in FIGURES.items():
        stem = Path(tmp) / name
        subprocess.run(["pdftoppm", "-r", str(DPI), "-f", str(page), "-l", str(page), "-singlefile", "-png", str(PDF), str(stem)], check=True)
        s = DPI / 72
        band = cv2.imread(f"{stem}.png")[int(top * s):int(bottom * s)]
        ink = band.min(axis=2) < 245
        ys, xs = np.where(ink.any(axis=1))[0], np.where(ink.any(axis=0))[0]
        pad = 10
        cut = band[max(ys[0] - pad, 0):ys[-1] + pad, max(xs[0] - pad, 0):xs[-1] + pad]
        cv2.imwrite(str(HERE / "media" / "img" / f"{name}.jpg"), cut, [cv2.IMWRITE_JPEG_QUALITY, 90])
        print(name, cut.shape[1], "x", cut.shape[0])
        if thumb:
            h, w = cut.shape[:2]
            small = cv2.resize(cut, (360, round(h * 360 / w)), interpolation=cv2.INTER_AREA)
            cv2.imwrite(str(HERE / "media" / "poster" / f"fig_{name}.jpg"), small, [cv2.IMWRITE_JPEG_QUALITY, 85])
