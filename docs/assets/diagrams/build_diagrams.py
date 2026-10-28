"""Generate the DSX-Connect 2 architecture and file-workflow diagrams.

Run from the repository root:

    python docs/assets/diagrams/build_diagrams.py

Each diagram is written in a light and a dark variant. Pages show the right one
with Material's #only-light / #only-dark image suffixes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

OUT_DIR = Path(__file__).resolve().parent
WIDTH, HEIGHT = 1240, 680

THEMES = {
    "light": {
        "bg": "#ffffff",
        "text": "#1f2933",
        "sub": "#52606d",
        "line": "#52606d",
        "box": "#ffffff",
        "neutral_fill": "#f5f6f8",
        "neutral_stroke": "#7b8794",
        "neutral_box_stroke": "#9aa5b1",
        "core_fill": "#eef7fd",
        "core_stroke": "#0288d1",
        "core_title": "#0277bd",
        "worker_fill": "#e1f5fe",
        "worker_stroke": "#4fc3f7",
        "conn_fill": "#edf7ee",
        "conn_stroke": "#2e7d32",
        "conn_box_stroke": "#66bb6a",
        "ext_fill": "#fff8e1",
        "ext_stroke": "#f57f17",
        "accent": "#ef6c00",
        "accent_text": "#ffffff",
        "dim": "0.32",
    },
    "dark": {
        "bg": "#1e2129",
        "text": "#e4e7eb",
        "sub": "#9aa5b1",
        "line": "#9aa5b1",
        "box": "#262a33",
        "neutral_fill": "#23272f",
        "neutral_stroke": "#616e7c",
        "neutral_box_stroke": "#52606d",
        "core_fill": "#14283a",
        "core_stroke": "#29b6f6",
        "core_title": "#4fc3f7",
        "worker_fill": "#0f3a52",
        "worker_stroke": "#29b6f6",
        "conn_fill": "#17291b",
        "conn_stroke": "#66bb6a",
        "conn_box_stroke": "#43a047",
        "ext_fill": "#33270f",
        "ext_stroke": "#ffb74d",
        "accent": "#ffa726",
        "accent_text": "#1e2129",
        "dim": "0.35",
    },
}


@dataclass
class Edge:
    points: list[tuple[float, float]]
    start: bool = False
    end: bool = True
    labels: list[tuple[float, float, str]] = field(default_factory=list)
    rotate_label: bool = False


# Element groups that a workflow can highlight. Anything not highlighted is dimmed.
ELEMENTS = [
    "apps", "repos", "connectors", "api", "postgres", "relay", "rabbitmq",
    "cache", "workers", "dsxa", "dianna", "results",
]

EDGES: dict[str, Edge] = {
    "apps_api": Edge([(750, 78), (750, 138)]),
    "repos_conn_1": Edge([(212, 214), (238, 214)], start=True),
    "repos_conn_2": Edge([(212, 280), (238, 280)], start=True),
    "repos_conn_3": Edge([(212, 346), (238, 346)], start=True),
    "conn_api": Edge([(422, 172), (518, 172)], start=True, labels=[(470, 152, "register"), (470, 164, "events")]),
    "workers_conn": Edge([(518, 527), (422, 527)], start=True, labels=[(470, 507, "read"), (470, 519, "remediate")]),
    "api_pg": Edge([(605, 206), (605, 248)], start=True),
    "pg_relay": Edge([(692, 296), (728, 296)]),
    "relay_mq": Edge([(790, 334), (790, 374)]),
    "api_cache": Edge([(955, 206), (955, 374)], labels=[(947, 290, "upload")], rotate_label=True),
    "mq_workers": Edge([(680, 436), (680, 468)]),
    "cache_workers": Edge([(900, 436), (900, 468)]),
    "workers_pg": Edge([(540, 468), (540, 342)], labels=[(532, 410, "state")], rotate_label=True),
    "workers_dsxa": Edge([(982, 496), (1058, 496)], labels=[(1020, 489, "scan")]),
    "workers_dianna": Edge([(982, 558), (1058, 558)], labels=[(1020, 551, "analyze")]),
    "workers_results": Edge([(982, 622), (1058, 622)], labels=[(1020, 615, "results")]),
}


@dataclass
class Flow:
    slug: str
    title: str
    highlight: set[str]
    edges: set[str]
    badges: list[tuple[float, float]]
    steps: list[list[str]]
    edge_labels: dict[str, list[tuple[float, float, str]]] = field(default_factory=dict)
    apps_subtitle: str | None = None
    connector_chips: dict[int, str] = field(default_factory=dict)


ARCHITECTURE = Flow(
    slug="architecture",
    title="Scan flow",
    highlight=set(ELEMENTS),
    edges=set(EDGES),
    badges=[(520, 140), (520, 262), (808, 354), (528, 510), (1060, 470), (618, 510)],
    steps=[
        ["Request or change event", "reaches the API"],
        ["Job, items and outbox", "committed to PostgreSQL"],
        ["Relay publishes work", "to RabbitMQ"],
        ["Scan worker reads content", "through the connector"],
        ["DSXA returns a verdict"],
        ["Policy decides; remediation", "and results follow"],
    ],
)

_PIPELINE = {"postgres", "relay", "rabbitmq", "workers", "dsxa", "results"}
_PIPELINE_EDGES = {"api_pg", "pg_relay", "relay_mq", "mq_workers", "workers_pg", "workers_dsxa", "workers_results"}

FULL_SCAN = Flow(
    slug="flow-full-scan",
    title="Full scan",
    highlight={"apps", "api", "connectors", "repos"} | _PIPELINE,
    edges={"apps_api", "conn_api", "workers_conn", "repos_conn_1", "repos_conn_2", "repos_conn_3"} | _PIPELINE_EDGES,
    badges=[(762, 108), (470, 186), (520, 262), (808, 354), (470, 541), (1060, 470), (618, 510)],
    edge_labels={
        "conn_api": [(470, 152, "list"), (470, 164, "objects")],
        "workers_conn": [(470, 507, "read"), (470, 519, "remediate")],
    },
    apps_subtitle="Operator starts a scan in the Operator Console",
    steps=[
        ["Operator scans a", "protected scope"],
        ["API lists the scope's", "objects through the connector"],
        ["Job, items and outbox", "committed to PostgreSQL"],
        ["Relay queues one scan", "per object in RabbitMQ"],
        ["Scan worker reads each", "file through the connector"],
        ["DSXA returns a verdict"],
        ["Policy applies the profile;", "remediation and results follow"],
    ],
)

MONITORING = Flow(
    slug="flow-monitoring",
    title="Monitoring",
    highlight={"repos", "connectors", "api"} | _PIPELINE,
    edges={"repos_conn_1", "repos_conn_2", "repos_conn_3", "conn_api", "workers_conn"} | _PIPELINE_EDGES,
    badges=[(225, 200), (470, 186), (520, 262), (808, 354), (470, 541), (1060, 470), (618, 510)],
    edge_labels={
        "conn_api": [(470, 152, "change"), (470, 164, "event")],
        "workers_conn": [(470, 507, "read"), (470, 519, "remediate")],
    },
    steps=[
        ["A file is created or", "changed in a repository"],
        ["Connector receives the", "change and submits a job"],
        ["Job matched to its scope", "and committed"],
        ["Relay queues the scan", "in RabbitMQ"],
        ["Scan worker reads the", "file through the connector"],
        ["DSXA returns a verdict"],
        ["Policy applies the profile;", "remediation and results follow"],
    ],
)

GATEWAY_UPLOAD = Flow(
    slug="flow-gateway-upload",
    title="Gateway: direct upload",
    highlight={"apps", "api", "cache", "connectors", "repos"} | _PIPELINE,
    edges={"apps_api", "api_cache", "cache_workers", "workers_conn", "repos_conn_1", "repos_conn_2", "repos_conn_3"}
    | _PIPELINE_EDGES,
    badges=[(762, 108), (967, 230), (520, 262), (808, 354), (912, 452), (1060, 470), (470, 541)],
    edge_labels={"workers_conn": [(470, 507, "write to"), (470, 519, "destination")]},
    apps_subtitle="Application uploads files with its credentials",
    steps=[
        ["Application uploads files", "to the gateway API"],
        ["API checks the app's grants", "and caches the upload"],
        ["Job, items and outbox", "committed to PostgreSQL"],
        ["Relay queues the scan", "in RabbitMQ"],
        ["Scan worker reads the", "cached file"],
        ["DSXA returns a verdict"],
        ["Policy decides; allowed files", "go to the destination"],
    ],
)

GATEWAY_TRANSFER = Flow(
    slug="flow-gateway-transfer",
    title="Gateway: source to sink",
    highlight={"apps", "api", "connectors", "repos"} | _PIPELINE,
    edges={"apps_api", "workers_conn", "repos_conn_1", "repos_conn_2", "repos_conn_3"} | _PIPELINE_EDGES,
    badges=[(762, 108), (520, 140), (520, 262), (808, 354), (470, 541), (1060, 470), (618, 510)],
    edge_labels={"workers_conn": [(470, 507, "read source"), (470, 519, "write sink")]},
    apps_subtitle="Transfer from a source connector to a sink (planned)",
    connector_chips={0: "GCS · source", 1: "AWS S3 · sink"},
    steps=[
        ["App or operator requests a", "source-to-sink transfer"],
        ["API checks grants for", "both connectors"],
        ["Job, items and outbox", "committed to PostgreSQL"],
        ["Relay queues the scan", "in RabbitMQ"],
        ["Scan worker reads each file", "through the source connector"],
        ["DSXA returns a verdict"],
        ["Policy decides; allowed files", "are written through the sink"],
    ],
)

FLOWS = [ARCHITECTURE, FULL_SCAN, MONITORING, GATEWAY_UPLOAD, GATEWAY_TRANSFER]


def _attr(**kwargs) -> str:
    return " ".join(f'{k.rstrip("_").replace("_", "-")}="{v}"' for k, v in kwargs.items())


class Svg:
    def __init__(self, theme: dict[str, str]):
        self.t = theme
        self.parts: list[str] = []

    def add(self, s: str) -> None:
        self.parts.append(s)

    def rect(self, x, y, w, h, fill, stroke, rx=10, dashed=False, stroke_width=1):
        dash = ' stroke-dasharray="4 3"' if dashed else ""
        self.add(f'<rect {_attr(x=x, y=y, width=w, height=h, rx=rx, fill=fill, stroke=stroke, stroke_width=stroke_width)}{dash}/>')

    def text(self, x, y, s, cls, anchor="middle", extra=""):
        a = f' text-anchor="{anchor}"' if anchor != "start" else ""
        self.add(f'<text class="{cls}" x="{x}" y="{y}"{a}{extra}>{escape(s)}</text>')


def _group(svg: Svg, name: str, flow: Flow, body) -> None:
    opacity = "1" if name in flow.highlight else svg.t["dim"]
    svg.add(f'<g opacity="{opacity}">')
    body()
    svg.add("</g>")


def render(flow: Flow, theme_name: str) -> str:
    t = THEMES[theme_name]
    svg = Svg(t)
    title = "DSX-Connect 2 architecture" if flow is ARCHITECTURE else f"DSX-Connect 2 {flow.title.lower()} workflow"
    desc = " ".join(" ".join(lines) + "." for lines in flow.steps)
    svg.add(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" '
        f'role="img" aria-labelledby="t d"><title id="t">{escape(title)}</title><desc id="d">{escape(desc)}</desc>'
    )
    svg.add(
        "<defs>"
        f'<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{t["line"]}"/></marker>'
        f'<marker id="arrow-hl" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5.5" markerHeight="5.5" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{t["accent"]}"/></marker>'
        "<style>"
        f'text {{ font-family: Roboto, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; fill: {t["text"]}; }}'
        ".h { font-size: 15px; font-weight: 600; } .h-sm { font-size: 14px; font-weight: 600; }"
        f'.sub {{ font-size: 11.5px; fill: {t["sub"]}; }} .chip {{ font-size: 12.5px; font-weight: 500; }}'
        f'.lbl {{ font-size: 10.5px; fill: {t["sub"]}; }} .lbl-hl {{ font-size: 10.5px; font-weight: 600; fill: {t["accent"]}; }}'
        f'.step {{ font-size: 12px; }} .badge-t {{ font-size: 11px; font-weight: 700; fill: {t["accent_text"]}; }}'
        f'.core-t {{ font-size: 16px; font-weight: 700; fill: {t["core_title"]}; }}'
        "</style></defs>"
    )
    svg.rect(0, 0, WIDTH, HEIGHT, t["bg"], "none", rx=14)

    def apps():
        svg.rect(600, 20, 300, 58, t["neutral_fill"], t["neutral_box_stroke"])
        svg.text(750, 45, "Applications and operators", "h")
        svg.text(750, 64, flow.apps_subtitle or "Operator Console · REST API · file gateway clients", "sub")

    def repos():
        svg.rect(20, 140, 190, 500, t["neutral_fill"], t["neutral_stroke"], rx=12)
        svg.text(115, 168, "Repositories", "h")
        for y, title, sub in [
            (186, "Cloud object storage", "GCS · Amazon S3"),
            (252, "File shares", "NFS · SMB · local volumes"),
            (318, "SaaS and collaboration", "SharePoint · OneDrive · M365"),
        ]:
            svg.rect(34, y, 162, 56, t["box"], t["neutral_box_stroke"], rx=8)
            svg.text(115, y + 23, title, "chip")
            svg.text(115, y + 42, sub, "sub")
        svg.text(115, 410, "Repository credentials", "sub")
        svg.text(115, 426, "stay with the connectors.", "sub")

    def connectors():
        svg.rect(240, 140, 180, 500, t["conn_fill"], t["conn_stroke"], rx=12)
        svg.text(330, 168, "Connectors", "h")
        for i, name in enumerate(["Google Cloud Storage", "AWS S3", "Filesystem", "More connectors"]):
            y = 186 + i * 40
            tagged = i in flow.connector_chips
            stroke = t["accent"] if tagged else t["conn_box_stroke"]
            svg.rect(254, y, 152, 32, t["box"], stroke, rx=8, dashed=(i == 3), stroke_width=2 if tagged else 1)
            svg.text(330, y + 21, flow.connector_chips.get(i, name), "chip")
        for i, cap in enumerate([
            "Register and heartbeat", "Discover assets", "Monitor change events",
            "Read file content", "Remediate", "Deliver files (write)",
        ]):
            svg.text(258, 382 + i * 22, f"• {cap}", "step", anchor="start")

    def api():
        svg.rect(520, 140, 460, 64, t["box"], t["core_stroke"])
        svg.text(750, 166, "DSX-Connect API", "h")
        svg.text(750, 186, "control plane · execution · file gateway · Operator Console", "sub")

    def postgres():
        svg.add(f'<path d="M520,262 v66 a85,10 0 0 0 170,0 v-66" fill="{t["box"]}" stroke="{t["core_stroke"]}"/>')
        svg.add(f'<ellipse cx="605" cy="262" rx="85" ry="10" fill="{t["box"]}" stroke="{t["core_stroke"]}"/>')
        svg.text(605, 296, "PostgreSQL", "h-sm")
        svg.text(605, 316, "jobs · items · outbox", "sub")

    def relay():
        svg.rect(730, 256, 150, 78, t["box"], t["core_stroke"])
        svg.text(805, 290, "Relay", "h-sm")
        svg.text(805, 310, "outbox → RabbitMQ", "sub")

    def rabbitmq():
        svg.rect(560, 376, 240, 58, t["box"], t["core_stroke"])
        svg.text(680, 400, "RabbitMQ", "h-sm")
        svg.text(680, 420, "work queues · retries · DLQs", "sub")

    def cache():
        svg.rect(820, 376, 160, 58, t["box"], t["core_stroke"])
        svg.text(900, 400, "Upload cache", "h-sm")
        svg.text(900, 420, "gateway files", "sub")

    def workers():
        svg.rect(520, 470, 460, 170, t["box"], t["core_stroke"])
        svg.text(538, 494, "Workers", "h-sm", anchor="start")
        for i, name in enumerate(["Scan", "Policy", "Remediation", "Result sink", "DIANNA"]):
            x = 528 + i * 90
            svg.rect(x, 510, 84, 34, t["worker_fill"], t["worker_stroke"], rx=8, dashed=(name == "DIANNA"))
            svg.text(x + 42, 532, name, "chip")
        svg.text(538, 576, "Each stage runs in its own pods and scales independently.", "sub", anchor="start")
        svg.text(538, 596, "Stage results are written back to PostgreSQL.", "sub", anchor="start")

    def external(name, y, h, title, sub, dashed=False):
        def body():
            svg.rect(1060, y, 170, h, t["ext_fill"], t["ext_stroke"], dashed=dashed)
            svg.text(1145, y + 22, title, "h-sm")
            svg.text(1145, y + 40, sub, "sub")
        _group(svg, name, flow, body)

    # Core panel sits behind the core components.
    svg.rect(500, 100, 500, 560, t["core_fill"], t["core_stroke"], rx=14, stroke_width=1.5)
    svg.text(520, 126, "DSX-Connect", "core-t", anchor="start")

    for name, body in [
        ("apps", apps), ("repos", repos), ("connectors", connectors), ("api", api),
        ("postgres", postgres), ("relay", relay), ("rabbitmq", rabbitmq), ("cache", cache), ("workers", workers),
    ]:
        _group(svg, name, flow, body)
    external("dsxa", 470, 52, "DSXA", "malware verdicts")
    external("dianna", 532, 52, "DIANNA", "AI analysis (optional)", dashed=True)
    external("results", 594, 56, "Result destinations", "stdout · JSON lines · SIEM")

    for key, edge in EDGES.items():
        on = key in flow.edges
        highlighted = on and flow is not ARCHITECTURE
        color = t["accent"] if highlighted else t["line"]
        marker = "url(#arrow-hl)" if highlighted else "url(#arrow)"
        width = 2.6 if highlighted else 1.6
        opacity = "1" if on else t["dim"]
        pts = " ".join(f"{x},{y}" for x, y in edge.points)
        markers = (f' marker-start="{marker}"' if edge.start else "") + (f' marker-end="{marker}"' if edge.end else "")
        svg.add(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}" opacity="{opacity}"{markers}/>')
        labels = flow.edge_labels.get(key, edge.labels)
        for x, y, label in labels:
            extra = f' transform="rotate(-90 {x} {y})"' if edge.rotate_label else ""
            cls = "lbl-hl" if highlighted else "lbl"
            svg.add(f'<g opacity="{opacity}">')
            svg.text(x, y, label, cls, extra=extra)
            svg.add("</g>")

    # Step legend.
    svg.text(1040, 146, flow.title, "h-sm", anchor="start")
    y = 170
    for number, lines in enumerate(flow.steps, start=1):
        svg.add(f'<circle cx="1050" cy="{y}" r="9" fill="{t["accent"]}"/>')
        svg.text(1050, y + 4, str(number), "badge-t")
        for j, line in enumerate(lines):
            svg.text(1066, y + 4 + j * 15, line, "step", anchor="start")
        y += 15 * len(lines) + 12

    for number, (x, y) in enumerate(flow.badges, start=1):
        svg.add(f'<circle cx="{x}" cy="{y}" r="9" fill="{t["accent"]}"/>')
        svg.text(x, y + 4, str(number), "badge-t")

    svg.add("</svg>")
    return "\n".join(svg.parts) + "\n"


def main() -> None:
    for flow in FLOWS:
        for theme_name in THEMES:
            suffix = "" if theme_name == "light" else "-dark"
            path = OUT_DIR / f"dsx-connect-2-{flow.slug}{suffix}.svg"
            path.write_text(render(flow, theme_name), encoding="utf-8")
            print(path.relative_to(OUT_DIR.parent.parent.parent))


if __name__ == "__main__":
    main()
