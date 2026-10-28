"""Generate light/dark Application identity diagrams using the architecture palette."""

from pathlib import Path
from xml.sax.saxutils import escape

from build_diagrams import THEMES


def render(t):
    parts = [f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1120 660" role="img" aria-labelledby="title desc">
<title id="title">DSX-Connect Application identity and attribution</title>
<desc id="desc">An operator defines an Application record. A real caller presents a credential that resolves to this record. Its grants authorize file requests and its attribution follows jobs, scanning, and results. Connectors provide destination access.</desc>
<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 Z" fill="{t['accent']}"/></marker></defs>
<rect width="1120" height="660" rx="12" fill="{t['bg']}"/>
<style>text{{font-family:Arial,sans-serif;fill:{t['text']}}}.title{{font-size:25px;font-weight:700}}.heading{{font-size:18px;font-weight:700}}.body{{font-size:15px}}.small{{font-size:13px;fill:{t['sub']}}}</style>''']

    def text(x, y, label, cls="body", anchor="middle"):
        parts.append(f'<text x="{x}" y="{y}" class="{cls}" text-anchor="{anchor}">{escape(label)}</text>')

    def box(x, y, w, h, fill, stroke, heading, lines=()):
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        text(x+w/2, y+29, heading, "heading")
        for i, line in enumerate(lines):
            text(x+w/2, y+54+i*21, line)

    def arrow(points):
        parts.append(f'<polyline points="{points}" fill="none" stroke="{t["accent"]}" stroke-width="2.5" marker-end="url(#arrow)"/>')

    text(30, 40, "Application identity and attribution", "title", "start")
    text(30, 65, "Register an Application to use DSX-Connect’s File Gateway capability.", "body", "start")
    # The record occupies the center, distinct from the caller and runtime stages.
    box(340, 125, 440, 340, t['core_fill'], t['core_stroke'], "DSX-Connect Application", ["A registered identity and access configuration"])
    for y, title, lines in [
        (198, "Identity bindings", ["Map a credential to this Application"]),
        (282, "Access grants", ["Allowed actions, destinations, path prefixes"]),
        (366, "Attribution defaults", ["Tenant · business unit · cost center", "Application ID · DSXA protected entity"]),
    ]:
        box(358, y, 404, 78 if y == 366 else 68, t['box'], t['core_stroke'], title, lines)
    box(30, 140, 245, 108, t['neutral_fill'], t['neutral_stroke'], "Real caller", ["Application · service · user", "Presents a credential"])
    box(30, 318, 245, 108, t['conn_fill'], t['conn_stroke'], "Operator", ["Registers the Application", "Assigns bindings and grants"])
    box(845, 140, 245, 108, t['ext_fill'], t['ext_stroke'], "Authenticate & Authorize", ["Resolves Application identity", "Checks requested access"])
    box(845, 318, 245, 108, t['conn_fill'], t['conn_stroke'], "Destination access", ["Protected scope + connector", "Repository permissions"])
    box(340, 524, 750, 105, t['core_fill'], t['core_stroke'], "File Gateway workflow", ["Accept files → scan / DSXA → policy → delivery + results", "Application context follows the work and remains available to operators"])
    arrow("275,185 307,185 307,230 358,230")
    text(305, 164, "identify", "small")
    arrow("275,370 340,370")
    arrow("780,230 810,230 810,194 845,194")
    text(814, 166, "authorize", "small")
    arrow("967,248 967,318")
    arrow("967,426 967,524")
    text(975, 477, "requested target", "small", "start")
    arrow("560,465 560,524")
    text(548, 496, "attach attribution", "small", "end")
    text(30, 492, "Credential binding today:", "small", "start")
    text(30, 515, "Static bearer token", "body", "start")
    text(30, 552, "Planned identity integration:", "small", "start")
    text(30, 575, "Entra / Okta / OIDC tokens", "body", "start")
    parts.append('</svg>')
    return '\n'.join(parts) + '\n'


if __name__ == '__main__':
    for name, theme in THEMES.items():
        suffix = '' if name == 'light' else '-dark'
        Path(__file__).with_name(f'dsx-connect-2-application-identity{suffix}.svg').write_text(render(theme), encoding='utf-8')
