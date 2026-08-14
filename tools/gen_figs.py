#!/usr/bin/env python3
# Generates the thesis diagrams: IK geometry, sine motion profile, camera FOV.
# Output paths are set by OUT below; adjust if running elsewhere.
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc, Circle
import numpy as np
import os

OUT = os.environ.get("FIG_OUT", "./")
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})

# ---------------- IK arm geometry ----------------
L1, L2, Q = 0.089, 0.080, 0.070023
theta1 = np.deg2rad(35)
j0 = np.array([0, 0])
j1 = j0 + L1 * np.array([np.cos(theta1), np.sin(theta1)])
yend = L1*np.sin(theta1) + np.sqrt(L2**2 - (Q - L1*np.cos(theta1))**2)
j2 = np.array([Q, yend])

fig, ax = plt.subplots(figsize=(5.5, 5))
ax.plot([j0[0], j1[0]], [j0[1], j1[1]], "-", lw=3, color="#1a56b0", label="link 1 ($L_1$ = 89 mm)")
ax.plot([j1[0], j2[0]], [j1[1], j2[1]], "-", lw=3, color="#c05a1a", label="link 2 ($L_2$ = 80 mm)")
for pnt, name in [(j0, "joint 1 (motor)"), (j1, "joint 2"), (j2, "plate joint")]:
    ax.plot(*pnt, "ko", ms=7)
    ax.annotate(name, pnt, textcoords="offset points", xytext=(8, -12), fontsize=9)
ax.axvline(Q, ls="--", color="gray", lw=1)
ax.text(Q + 0.002, -0.01, "x = q = 70 mm", fontsize=9, color="gray")
ax.annotate("", xy=(Q + 0.03, yend), xytext=(Q + 0.03, 0),
            arrowprops=dict(arrowstyle="<->", lw=1))
ax.text(Q + 0.033, yend/2, "y (plate height)", fontsize=9, rotation=90, va="center")
arc = Arc(j0, 0.05, 0.05, angle=0, theta1=0, theta2=np.rad2deg(theta1), color="k")
ax.add_patch(arc)
ax.text(0.030, 0.008, r"$\theta_1$", fontsize=11)
ax.axhline(0, color="k", lw=0.8)
ax.set_xlim(-0.02, 0.13); ax.set_ylim(-0.03, 0.15)
ax.set_aspect("equal")
ax.legend(loc="upper left", fontsize=9)
ax.set_xlabel("x [m]"); ax.set_ylabel("y [m]")
plt.tight_layout()
plt.savefig(OUT + "fig_ik.png", dpi=200, bbox_inches="tight")
plt.close()

# ---------------- sine motion profile ----------------
T = 0.1
ds = 500
t = np.linspace(0, T, 500)
theta = np.pi * t / T
pos = ds * (1 - (1 + np.cos(theta)) / 2)
vel = ds * np.pi / (2 * T) * np.sin(theta)

fig, ax1 = plt.subplots(figsize=(7, 3.6))
ax1.plot(t * 1000, pos, lw=2, color="#1a56b0", label="position (pulses)")
ax1.set_xlabel("time [ms]")
ax1.set_ylabel("position [pulses]", color="#1a56b0")
ax1.tick_params(axis="y", labelcolor="#1a56b0")
ax2 = ax1.twinx()
ax2.plot(t * 1000, vel, lw=2, color="#c05a1a", ls="--", label="step rate (pulses/s)")
ax2.set_ylabel("step rate [pulses/s]", color="#c05a1a")
ax2.tick_params(axis="y", labelcolor="#c05a1a")
ax1.set_title("Sinusoidal motion profile: 500-pulse move, $T$ = 0.1 s")
ax1.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(OUT + "fig_sine.png", dpi=200, bbox_inches="tight")
plt.close()

# ---------------- camera FOV geometry ----------------
fig, ax = plt.subplots(figsize=(6, 4.6))
cam = np.array([0, 0])
fov = np.deg2rad(61.6)
depth = 0.16
half = np.tan(fov/2) * depth
ax.plot([cam[0]], [cam[1]], "ks", ms=10)
ax.annotate("camera", cam, textcoords="offset points", xytext=(10, 4), fontsize=10)
ax.plot([0, -half], [0, -depth], "k-", lw=1)
ax.plot([0, half], [0, -depth], "k-", lw=1)
arc = Arc(cam, 0.06, 0.06, angle=0, theta1=-90-np.rad2deg(fov/2), theta2=-90+np.rad2deg(fov/2), color="k")
ax.add_patch(arc)
ax.text(0.008, -0.045, r"FOV $\approx 61.6°$", fontsize=10)
ax.plot([-0.09, 0.09], [-depth, -depth], lw=4, color="#888")
ax.text(0.095, -depth, "plate", fontsize=10, va="center")
ball_h = 0.078
ball = Circle((0.035, -depth + ball_h*0.55), 0.02, fc="#f5a623", ec="k")
ax.add_patch(ball)
ax.annotate("ball (r = 20 mm)", (0.055, -depth + ball_h*0.55), fontsize=9, va="center")
ax.annotate("", xy=(-0.105, 0), xytext=(-0.105, -depth),
            arrowprops=dict(arrowstyle="<->", lw=1))
ax.text(-0.135, -depth/2, "camera to\nplate", fontsize=9, ha="center")
ax.annotate("", xy=(-0.075, -depth), xytext=(-0.075, -depth + ball_h),
            arrowprops=dict(arrowstyle="<->", lw=1, color="#c05a1a"))
ax.text(-0.0450, -depth + ball_h/2, "h = 78 mm\n(origin height)", fontsize=8, color="#c05a1a")
ax.axis("off")
ax.set_xlim(-0.17, 0.17); ax.set_ylim(-0.19, 0.03)
plt.tight_layout()
plt.savefig(OUT + "fig_fov.png", dpi=200, bbox_inches="tight")
plt.close()

print("figures written to", OUT)
