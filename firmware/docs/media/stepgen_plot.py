"""Renders stepgen_plot.png: the pull-in / cruise / accel profile of one run.

Rate is drawn against time, so accel_pps_s is a literal slope and the pulse
count is the area under the curve.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PULLIN = 400.0    # pps
CRUISE = 2000.0   # pps
ACCEL = 8000.0    # pps/s
CRUISE_S = 0.45   # time held at cruise

ramp_s = (CRUISE - PULLIN) / ACCEL
t = [0.0, ramp_s, ramp_s + CRUISE_S, 2 * ramp_s + CRUISE_S]
v = [PULLIN, CRUISE, CRUISE, PULLIN]

fig, ax = plt.subplots(figsize=(8, 4.2))

ax.plot(t, v, color="#1f4e79", linewidth=2.4, zorder=3)
ax.fill_between(t, 0, v, color="#1f4e79", alpha=0.07, zorder=1)

ax.axhline(PULLIN, color="#8a8a8a", linewidth=0.9, linestyle="--", zorder=2)
ax.axhline(CRUISE, color="#8a8a8a", linewidth=0.9, linestyle="--", zorder=2)

ax.annotate("cruise_pps", xy=(t[1] + CRUISE_S / 2, CRUISE),
            xytext=(t[1] + CRUISE_S / 2, CRUISE + 180),
            ha="center", color="#1f4e79", fontsize=11)
ax.annotate("pullin_pps", xy=(0, PULLIN), xytext=(t[-1] * 0.02, PULLIN + 110),
            color="#1f4e79", fontsize=11)

mid = ramp_s * 0.5
ax.annotate("accel_pps_s\n(slope of both ramps)",
            xy=(mid, PULLIN + ACCEL * mid),
            xytext=(ramp_s * 1.35, CRUISE * 0.78),
            fontsize=10, color="#333333",
            arrowprops=dict(arrowstyle="->", color="#333333", linewidth=0.9))

ax.annotate("area under the curve = pulses emitted",
            xy=(t[1] + CRUISE_S * 0.42, CRUISE * 0.30),
            ha="center", fontsize=10, color="#4d6b85")

for x0, label, off in ((t[0], "starts from rest", 1), (t[-1], "stops dead", -1)):
    ax.plot([x0], [PULLIN], marker="o", markersize=6, color="#c0392b", zorder=4)
    ax.annotate(label, xy=(x0, PULLIN),
                xytext=(x0 + off * t[-1] * 0.11, PULLIN - 230),
                ha="center", fontsize=9.5, color="#c0392b")

ax.set_xlabel("time (s)")
ax.set_ylabel("rate (pulses per second)")
ax.set_title("A run is a profile, not a rate", fontsize=12, pad=12)

ax.set_xlim(-t[-1] * 0.03, t[-1] * 1.03)
ax.set_ylim(0, CRUISE * 1.28)
ax.spines[["top", "right"]].set_visible(False)
ax.grid(axis="y", color="#dddddd", linewidth=0.7, zorder=0)

fig.tight_layout()
fig.savefig("stepgen_plot.png", dpi=200)
