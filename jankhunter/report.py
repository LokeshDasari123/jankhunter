"""Self-contained HTML report for a detection and repair run."""

from __future__ import annotations

import base64
import html
import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from jankhunter.fix.loop import Iteration
from jankhunter.models import Defect, Frame, Track


def _image_data(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _trajectory_plot(before: list[Track], after: list[Track]) -> str:
    fig, ax = plt.subplots(figsize=(8, 3.4), dpi=120)
    for tracks, prefix, style in ((before, "Before", "-"), (after, "After", "--")):
        for track in tracks:
            points = [p for p in track.points if p.visible]
            if points:
                ax.plot([p.centroid[0] for p in points], [p.centroid[1] for p in points],
                        style, linewidth=1.3, label=f"{prefix}: {track.label}")
    ax.set_title("Tracked object paths")
    ax.set_xlabel("x (px)")
    ax.set_ylabel("y (px)")
    ax.invert_yaxis()
    ax.grid(alpha=0.2)
    ax.legend(fontsize=7, ncol=2)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


def _frame_strip(frames: list[Frame], defects: list[Defect], title: str) -> str:
    indices = sorted({index for defect in defects for index in defect.evidence if 0 <= index < len(frames)})
    if not indices:
        indices = list(range(min(4, len(frames))))
    imgs = []
    for index in indices[:6]:
        frame = frames[index]
        imgs.append(f'<figure><img src="{_image_data(frame.path)}" alt="{title} frame {index}">'
                    f'<figcaption>{title} · {frame.t:.2f}s · frame {index}</figcaption></figure>')
    return "".join(imgs)


def write_report(
    out_path: Path,
    defects_before: list[Defect],
    defects_after: list[Defect],
    frames_before: list[Frame],
    frames_after: list[Frame],
    tracks_before: list[Track],
    tracks_after: list[Track],
    history: list[Iteration] | None = None,
) -> Path:
    """Write a portable report with plots and sampled evidence embedded inline."""
    plot = _trajectory_plot(tracks_before, tracks_after)
    rows = "".join(
        f"<tr><td>{html.escape(d.type)}</td><td>{html.escape(d.label)}</td>"
        f"<td>{d.t_start:.2f}–{d.t_end:.2f}s</td><td>{d.severity:.2f}</td>"
        f"<td>{d.metric:.3g}</td><td>{', '.join(map(str, d.evidence))}</td></tr>"
        for d in defects_before
    ) or '<tr><td colspan="6">No defects detected</td></tr>'
    history_rows = "".join(
        f"<tr><td>{item.number}</td><td>{html.escape(item.summary)}</td>"
        f"<td>{item.before_score:.3f}</td><td>{item.after_score if item.after_score is not None else '—'}</td>"
        f"<td>{'Accepted' if item.accepted else 'Rejected'}</td><td><pre>{html.escape(item.patch or item.error or '')}</pre></td></tr>"
        for item in (history or [])
    ) or '<tr><td colspan="6">Analysis only; no repair iteration</td></tr>'
    doc = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>JankHunter run report</title><style>
body{{max-width:1120px;margin:40px auto;padding:0 24px;background:#0e1117;color:#e7ebf2;font:15px/1.55 system-ui,sans-serif}}
h1,h2{{color:#fff}}.muted,figcaption{{color:#9aa6b8}}section{{margin:32px 0;padding:22px;background:#171c25;border:1px solid #2c3442;border-radius:12px}}
img{{max-width:100%;border-radius:6px}}.strip{{display:flex;gap:12px;overflow:auto}}figure{{min-width:160px;margin:0}}figure img{{width:220px;height:124px;object-fit:cover}}figcaption{{font-size:12px}}
table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;vertical-align:top;padding:9px;border-bottom:1px solid #303846}}pre{{white-space:pre-wrap;max-height:250px;overflow:auto;color:#bdc8d8}}
</style><body><h1>JankHunter <span class="muted">run report</span></h1>
<p class="muted">Temporal visual regression analysis · deterministic detectors · Muse Spark assisted patching when configured</p>
<section><h2>Findings before repair</h2><p>{len(defects_before)} defects · {len(defects_after)} after · {len(defects_before)-len(defects_after):+d} net change</p>
<table><thead><tr><th>Type</th><th>Element</th><th>Window</th><th>Severity</th><th>Metric</th><th>Evidence frames</th></tr></thead><tbody>{rows}</tbody></table></section>
<section><h2>Trajectory comparison</h2><img src="{plot}" alt="Before and after trajectory plot"></section>
<section><h2>Evidence frames</h2><h3>Before</h3><div class="strip">{_frame_strip(frames_before, defects_before, 'Before')}</div>
<h3>After</h3><div class="strip">{_frame_strip(frames_after, defects_after, 'After')}</div></section>
<section><h2>Repair history</h2><table><thead><tr><th>Try</th><th>Diagnosis</th><th>Before score</th><th>After score</th><th>Result</th><th>Patch diff / error</th></tr></thead><tbody>{history_rows}</tbody></table></section>
<p class="muted">Scores are heuristic indicators for this scenario, not universal quality scores. Captured frames and tracking quality bound detector accuracy.</p></body></html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    return out_path
