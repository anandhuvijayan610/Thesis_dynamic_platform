#!/usr/bin/env python3
# Generates the system block diagram (fig_block.png).
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import os

OUT = os.environ.get("FIG_OUT", "./")
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})

fig, ax = plt.subplots(figsize=(9.5, 3.8))
ax.axis("off")

def box(x, y, w, h, text, fc="#f0f0f0"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.008",
                                fc=fc, ec="black", lw=1))
    ax.text(x + w/2, y + h/2, text, ha="center", va="center", fontsize=9)

def arr(x1, y1, x2, y2, text="", tx=None, ty=None, color="k", ls="-"):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="->", lw=1.2, color=color, linestyle=ls))
    if text:
        ax.text(tx if tx is not None else (x1+x2)/2,
                ty if ty is not None else (y1+y2)/2 + 0.05,
                text, ha="center", fontsize=8, color=color)

box(0.02, 0.60, 0.12, 0.26, "USB camera\n(120 fps)")
box(0.19, 0.60, 0.15, 0.26, "PC / Unity\nOpenCV, IK,\ncontrol")
box(0.39, 0.60, 0.12, 0.26, "Teensy 4.0\nfirmware (ISR)")
box(0.56, 0.60, 0.12, 0.26, "TXS0108E\nlevel shifter")
box(0.73, 0.60, 0.10, 0.26, "4 x DM542T\ndrivers")
box(0.88, 0.60, 0.10, 0.26, "4 x NEMA 17\n(5.18:1)")

arr(0.14, 0.73, 0.19, 0.73, "USB", ty=0.79)
arr(0.34, 0.73, 0.39, 0.73, "serial", ty=0.79)
arr(0.51, 0.73, 0.56, 0.73, "3.3 V", ty=0.79)
arr(0.68, 0.73, 0.73, 0.73, "5 V", ty=0.79)
arr(0.83, 0.73, 0.88, 0.73)

box(0.56, 0.10, 0.12, 0.24, "XL4016\nbuck  5 V", fc="#e8f0fe")
box(0.73, 0.10, 0.10, 0.24, "PSU\n35 V / 8 A", fc="#e8f0fe")
arr(0.73, 0.22, 0.68, 0.22, "35 V", ty=0.25)
arr(0.62, 0.34, 0.62, 0.60, "5 V", tx=0.645, ty=0.46)
arr(0.78, 0.34, 0.78, 0.60, "35 V", tx=0.812, ty=0.46)

box(0.88, 0.10, 0.10, 0.24, "Plate + ball", fc="#fff4e5")
arr(0.93, 0.60, 0.93, 0.34)

ax.annotate("", xy=(0.08, 0.60), xytext=(0.88, 0.16),
            arrowprops=dict(arrowstyle="->", lw=1.0, color="gray",
                            linestyle="--",
                            connectionstyle="arc3,rad=0.25"))
ax.text(0.36, 0.13, "optical feedback (ball observed by camera)", fontsize=8, color="gray")

ax.set_xlim(0, 1.0)
ax.set_ylim(0, 1.0)
plt.tight_layout()
plt.savefig(OUT + "fig_block.png", dpi=200, bbox_inches="tight")
print("ok")
