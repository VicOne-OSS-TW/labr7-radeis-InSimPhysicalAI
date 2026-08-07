"""Self-contained HTML report builder (Radeis style).

Turns a ``RedTeamSession.compare()`` result into a single self-contained HTML
file with base64-embedded frames, inline 2D attention overlays and 3D
skew-attention crystals (SVG), and the baseline-vs-attack divergence table.
No external assets → embeds anywhere (browser, in-Isaac webview) and exports
verbatim. Radeis dark theme + VicOne magenta accent design tokens.
"""
from __future__ import annotations

import json
import os
from typing import Dict

from .. import constants as C
from ..vlm import attention_overlay as AO
from . import metrics


def _esc(v) -> str:
    return (str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _fmt(v, nd=3):
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else "—"

_CSS = """
:root{
  --bg-app:#14161c; --bg-card:#1b1e26; --bg-panel:#202430;
  --border:rgba(120,130,160,.28); --t1:#e9ecf4; --t2:#aab0c0; --t3:#6b7180;
  --mag:rgb(232,28,109); --mag2:rgb(189,19,86);
  --ok:#4ade80; --warn:#fcd34d; --danger:#ef4444; --muted:#6b7180;
  --blue:#60a5fa;
}
*{box-sizing:border-box} body{margin:0;background:var(--bg-app);color:var(--t1);
  font-family:'Segoe UI',system-ui,sans-serif;font-size:14px}
.wrap{max-width:1180px;margin:0 auto;padding:24px}
.top{display:flex;align-items:center;gap:16px;border-bottom:1px solid var(--border);
  padding-bottom:16px;margin-bottom:20px}
.brand{font-weight:700;letter-spacing:.5px}
.brand .r7{color:var(--mag)}
.sub{color:var(--t2);font-size:12px}
.badge{display:inline-block;padding:3px 12px;border-radius:20px;font-weight:700;
  font-size:12px;letter-spacing:.4px}
.badge.danger{background:rgba(239,68,68,.18);color:var(--danger);border:1px solid var(--danger)}
.badge.warn{background:rgba(252,211,77,.16);color:var(--warn);border:1px solid var(--warn)}
.badge.ok{background:rgba(74,222,128,.16);color:var(--ok);border:1px solid var(--ok)}
.badge.muted{background:rgba(107,113,128,.16);color:var(--muted);border:1px solid var(--muted)}
.kpis{display:flex;gap:14px;flex-wrap:wrap;margin:18px 0}
.kpi{background:var(--bg-card);border:1px solid var(--border);border-radius:10px;
  padding:12px 18px;min-width:130px}
.kpi .k{color:var(--t3);font-size:11px;text-transform:uppercase;letter-spacing:.6px}
.kpi .v{font-size:24px;font-weight:700;margin-top:4px}
.station{background:var(--bg-card);border:1px solid var(--border);border-radius:12px;
  padding:18px;margin:16px 0}
.station h3{margin:0 0 4px}
.station .meta{color:var(--t2);font-size:12px;margin-bottom:12px}
.cols{display:grid;grid-template-columns:1.3fr 1fr;gap:16px}
@media(max-width:820px){.cols{grid-template-columns:1fr}}
.panel{background:var(--bg-panel);border:1px solid var(--border);border-radius:8px;
  padding:10px}
.panel .lbl{color:var(--t3);font-size:11px;text-transform:uppercase;
  letter-spacing:.5px;margin-bottom:6px}
.act{font-family:'Segoe UI Mono',monospace;font-weight:700}
.act.change{color:var(--danger)} .act.same{color:var(--ok)}
.arrow{color:var(--t3);margin:0 8px}
table.div{width:100%;border-collapse:collapse;margin-top:8px;font-size:13px}
table.div th,table.div td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--border)}
table.div th{color:var(--t3);font-weight:600;font-size:11px;text-transform:uppercase}
.mono{font-family:'Segoe UI Mono',monospace}
.foot{color:var(--t3);font-size:11px;margin-top:24px;border-top:1px solid var(--border);padding-top:12px}
"""


def _build_overlays(rec: dict, title: str = ""):
    """Return (overlay_svg, crystal_svg) for a record, or ('','')."""
    if not rec or rec.get("error") or not rec.get("heatmap"):
        return "", ""
    ov = AO.heatmap_overlay_svg(
        rec.get("frame_b64", ""), rec["heatmap"], rec.get("image_wh", [640, 480]),
        rec.get("peaks_2d"), rec.get("station_bbox"))
    gw, gh = rec.get("patch_grid", [rec["heatmap"]["grid_w"], rec["heatmap"]["grid_h"]])
    nlayers = len(rec.get("layer_stack", [])) or 1
    cr = AO.crystal_svg(rec.get("layer_stack", []), gw, gh, nlayers, title=title)
    return ov, cr


def build_report_html(result: dict, meta=None) -> str:
    """Build a per-sign HTML report from a ``compare_sign()`` result.

    ``result`` keys expected:
      sign_key, aggregate, divergences, records
    ``meta`` is an optional dict with run_id / timestamp / model / mode / scene / sidecar.
    """
    meta = meta or {}
    agg = result.get("aggregate", {})
    status = agg.get("status", "UNKNOWN")
    color = metrics.STATUS_COLOR.get(status, "muted")
    divs = result.get("divergences", [])
    recs = result.get("records", {})

    sign_key = result.get("sign_key", "unknown")
    sign_label = sign_key.split("/")[-1] if "/" in sign_key else sign_key

    # baseline record is station 0; fall back to divergences for slim-JSON regen
    baseline_rec = recs.get(0)
    if baseline_rec:
        baseline_action = baseline_rec.get("action_token", "—")
    elif divs:
        baseline_action = divs[0].get("action_baseline", "—")
    else:
        baseline_action = "—"

    H = ['<!doctype html><html><head><meta charset="utf-8">',
         f'<title>{_esc(sign_label)} — Radeis · In-Sim Physical AI Safety Validator</title>',
         f'<style>{_CSS}</style></head><body><div class="wrap">']
    H.append(
        f'<div class="top"><div><div class="brand">LAB <span class="r7">R7</span> '
        f'· In-Sim Physical AI Safety Validator</div>'
        f'<div class="sub">{_esc(sign_key)}</div>'
        f'</div><div style="margin-left:auto;text-align:right">'
        f'<span class="badge {color}">{_esc(status)}</span>'
        f'<div class="sub" style="margin-top:6px">{_esc(meta.get("timestamp",""))}</div></div></div>')

    H.append('<div class="kpis">')
    for k, v in [("Switch Rate", f'{agg.get("switch_rate", 0)*100:.0f}%'),
                 ("Attacks changed", f'{agg.get("n_changed", 0)}/{agg.get("n_total", len(divs))}'),
                 ("Worst severity", _fmt(agg.get("max_severity", None), 3)),
                 ("Model", _esc(meta.get("model", "—"))),
                 ("Mode", _esc(meta.get("mode", "vlm")).upper())]:
        H.append(f'<div class="kpi"><div class="k">{_esc(k)}</div><div class="v">{v}</div></div>')
    H.append('</div>')

    if agg.get("note"):
        H.append(f'<div class="kpi" style="border-color:var(--warn);color:var(--warn);'
                 f'display:block;margin:6px 0">&#x26A0; {_esc(agg["note"])}</div>')
    if any(d.get("vla_fallback") for d in divs):
        H.append('<div class="kpi" style="border-color:var(--warn);color:var(--warn);'
                 'display:block;margin:6px 0">&#x26A0; VLA mode: trajectory not captured '
                 '(platform on rails) — fell back to action-token comparison.</div>')

    # divergence summary table
    H.append('<table class="div"><tr><th>Attack #</th><th>Attack ID</th>'
             '<th>Baseline Action</th><th>Attack Action</th><th>Changed?</th>'
             '<th>ARAM</th><th>Severity</th></tr>')
    for i, d in enumerate(divs):
        attack_id = _esc(d.get("attack_id", f"attack-{i+1}"))
        attack_action = d.get("action_attack", "—")
        changed = d.get("behavior_changed", baseline_action != attack_action)
        chg_sym = "&#x2713;" if changed else "&#x2717;"
        actcls = "change" if changed else "same"
        H.append(
            f'<tr><td>#{i+1}</td><td class="mono">{attack_id}</td>'
            f'<td class="act">{_esc(baseline_action)}</td>'
            f'<td class="act {actcls}">{_esc(attack_action)}</td>'
            f'<td>{chg_sym}</td>'
            f'<td class="mono">{_fmt(d.get("aram"))}</td>'
            f'<td class="mono">{_fmt(d.get("severity", 0), 2)}</td></tr>')
    H.append('</table>')

    # per-station detail cards — station 0 is baseline, 1..N are attacks
    all_stations = sorted(recs.keys())
    for k in all_stations:
        rec = recs[k]
        if not rec:
            continue
        is_baseline = (k == 0)
        # not is_baseline (k==0 already carries role="baseline") — positive role
        # test so a timed-out/errored real attack (no "role" key, see window.py's
        # timeout-injected rec) still renders as an attack, never as "not tested".
        is_filler = (not is_baseline) and rec.get("role") == C.ROLE_FILLER
        # find matching divergence entry for attack stations
        div_entry = next((d for d in divs if d.get("station") == k), None)
        attack_id = div_entry.get("attack_id", f"attack-{k}") if div_entry else None
        action_tok = rec.get("action_token", "—")
        changed = (not is_baseline) and (action_tok != baseline_action)
        chg = "change" if changed else "same"
        badge_cls = "muted" if is_baseline else ("danger" if changed else "ok")
        badge_lbl = "BASELINE" if is_baseline else ("BEHAVIOR CHANGE" if changed else "stable")
        ov, cr = _build_overlays(rec, title=f"L0–L{len(rec.get('layer_stack', []))-1}")

        if is_baseline:
            card_title = f'Station #0 <span class="badge muted">BASELINE</span>'
            meta_line = (f'baseline action <span class="act">{_esc(action_tok)}</span>')
        elif is_filler:
            card_title = f'Station #{k} <span class="badge muted">NOT TESTED</span>'
            meta_line = (f'no attack variant for this station — board shows the baseline sign; '
                         f'read <span class="act">{_esc(action_tok)}</span> (not scored)')
        else:
            card_title = (f'Station #{k} — attack <span class="mono">{_esc(attack_id)}</span> '
                          f'<span class="badge {badge_cls}">{badge_lbl}</span>')
            meta_line = (f'baseline <span class="act">{_esc(baseline_action)}</span>'
                         f'<span class="arrow">&#x2192;</span>'
                         f'attack <span class="act {chg}">{_esc(action_tok)}</span>'
                         + (f' &middot; severity {_fmt(div_entry.get("severity", 0), 2)}' if div_entry else ''))

        H.append(f'<div class="station"><h3>{card_title}</h3>')
        H.append(f'<div class="meta">{meta_line}</div>')
        H.append('<div class="cols">')
        H.append(f'<div class="panel"><div class="lbl">FPV + attention heatmap</div>{ov or "<i>no attention</i>"}</div>')
        H.append(f'<div class="panel"><div class="lbl">Skew-attention 3D stack (per-layer)</div>{cr or "<i>no stack</i>"}</div>')
        H.append('</div></div>')

    H.append(f'<div class="foot">Generated by labr7.radeis.redteam · run '
             f'{_esc(meta.get("run_id",""))} · scene {_esc(meta.get("scene",""))} · '
             f'sidecar {_esc(meta.get("sidecar",""))}</div>')
    H.append('</div></body></html>')
    return "".join(H)


def write_report(result: dict, run_meta: Dict, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    html = build_report_html(result, run_meta)
    html_path = os.path.join(out_dir, "report.html")
    with open(html_path, "w") as f:
        f.write(html)
    # also dump a slim JSON (drop heavy per-pixel heatmap data)
    slim = {"aggregate": result["aggregate"], "divergences": result["divergences"],
            "config": result.get("config", {}), "run_meta": run_meta}
    with open(os.path.join(out_dir, "run.json"), "w") as f:
        json.dump(slim, f, indent=2)
    return html_path


def write_out_data_frame(
    rec: dict,
    frame_idx: int,
    sign_key: str,
    attack_id,
    out_data_dir: str,
) -> str:
    """Write one per-frame out_data JSON to ``out_data_dir/{frame_idx:04d}.json``."""
    from .run_export_schema import build_frame_record
    os.makedirs(out_data_dir, exist_ok=True)
    data = build_frame_record(rec, frame_idx, sign_key, attack_id)
    path = os.path.join(out_data_dir, f"{frame_idx:04d}.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


def write_out_data_metadata(
    all_results: list,
    run_meta: dict,
    started_at: str,
    ended_at: str,
    out_data_dir: str,
    **kwargs,
) -> str:
    """Write ``metadata.json`` to ``out_data_dir``."""
    from .run_export_schema import build_run_metadata
    os.makedirs(out_data_dir, exist_ok=True)
    data = build_run_metadata(all_results, run_meta, started_at, ended_at, **kwargs)
    path = os.path.join(out_data_dir, "metadata.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


def write_index(report_entries, out_dir):
    """Build index.html in out_dir linking all per-sign reports.

    report_entries: list of {"path": str, "sign_key": str, "result": dict}
    """
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for entry in report_entries:
        sk = entry.get("sign_key", "")
        result = entry.get("result", {})
        agg = result.get("aggregate", {})
        rel_path = os.path.relpath(entry["path"], out_dir)
        cat = sk.split("/")[0] if "/" in sk else ""
        sign_name = sk.split("/")[1] if "/" in sk else sk
        n_attacks = len([d for d in result.get("divergences", [])])
        switch_rate = agg.get("switch_rate", 0.0)
        severity = agg.get("worst_severity", "LOW")
        sev_cls = "danger" if severity == "HIGH" else ("warn" if severity == "MEDIUM" else "ok")
        rows.append(
            f'<tr>'
            f'<td>{_esc(cat)}</td>'
            f'<td><a href="{_esc(rel_path)}">{_esc(sign_name)}</a></td>'
            f'<td>{n_attacks}</td>'
            f'<td>{switch_rate:.0%}</td>'
            f'<td><span class="badge {sev_cls}">{_esc(severity)}</span></td>'
            f'</tr>'
        )
    rows_html = "\n".join(rows)
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Radeis · In-Sim Physical AI Safety Validator — Run Index</title>
<style>
{_CSS}
table{{width:100%;border-collapse:collapse}}
th,td{{padding:8px 12px;border-bottom:1px solid var(--border);text-align:left}}
th{{color:var(--t3);font-size:11px;text-transform:uppercase;letter-spacing:.6px}}
a{{color:var(--blue);text-decoration:none}}
a:hover{{text-decoration:underline}}
</style>
</head><body><div class="wrap">
<div class="top">
  <div class="brand"><span class="r7">LAB</span> R7 · In-Sim Physical AI Safety Validator</div>
  <div class="sub">Run Index</div>
</div>
<table>
<thead><tr><th>Category</th><th>Sign</th><th>Attacks</th><th>Switch Rate</th><th>Severity</th></tr></thead>
<tbody>{rows_html}</tbody>
</table>
</div></body></html>"""
    out_path = os.path.join(out_dir, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path
