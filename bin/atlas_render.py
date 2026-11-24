"""atlas renderer: models (stack-agnostic, see atlas_solidity.py) -> view sections.

Pure functions, standard library only, no I/O: atlas calls render_view() and
writes the result as view.json, which the page (templates/atlas/index.html) draws.

Each module carries a 'role' that atlas adds from the project config:
src (yours), test, script, external (lib/, node_modules/: collapsed per package).
API, graph and impact views look at 'src' modules; sequences come from tests.
"""

from __future__ import annotations

import re

# Mermaid colors: green added, amber changed, red removed, grey context.
CLASSDEFS = [
    "classDef added fill:#dcfce7,stroke:#16a34a,color:#14532d",
    "classDef changed fill:#fef3c7,stroke:#d97706,color:#78350f",
    "classDef removed fill:#fee2e2,stroke:#dc2626,color:#7f1d1d,stroke-dasharray:4 3",
    "classDef ctx fill:#f1f5f9,stroke:#94a3b8,color:#334155",
    "classDef ext fill:#e0e7ff,stroke:#6366f1,color:#312e81",
]
EDGE_STYLE = {
    "added": "stroke:#16a34a,stroke-width:2.5px",
    "removed": "stroke:#dc2626,stroke-width:2px,stroke-dasharray:5 4",
    "same": "stroke:#94a3b8,stroke-width:1px",
}
EDGE_LABEL = {"inherits": "is", "uses": "uses", "calls": "calls", "creates": "new"}
MAX_NODES = 60


# ---- small helpers ----------------------------------------------------------


def mid(name: str) -> str:
    """A Mermaid-safe identifier for a module or package name."""
    return "n_" + re.sub(r"[^A-Za-z0-9_]", "_", name)


def esc(text: str) -> str:
    """Escape text for Mermaid labels and messages."""
    return (
        text.replace("#", "#35;").replace(";", "#59;").replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")
    )


def package_of(path: str) -> str:
    """lib/openzeppelin-contracts/... -> lib/openzeppelin-contracts; node_modules/@oz/x/... -> @oz/x."""
    parts = [p for p in path.split("/") if p not in ("", ".", "..")]
    if "node_modules" in parts:
        rest = parts[parts.index("node_modules") + 1 :]
        return "/".join(rest[:2]) if rest and rest[0].startswith("@") else (rest[0] if rest else "node_modules")
    if "lib" in parts:
        rest = parts[parts.index("lib") :]
        return "/".join(rest[:2])
    return "/".join(parts[:2]) or "external"


def group_of(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else "."


def src_modules(model: dict) -> dict:
    return {n: m for n, m in model.get("modules", {}).items() if m.get("role") == "src"}


def node_of(model: dict, name: str) -> str | None:
    """The graph node a module is drawn as: itself (src), its package (external), or None (tests, scripts)."""
    m = model.get("modules", {}).get(name)
    if m is None:
        return None
    role = m.get("role")
    if role == "src":
        return name
    if role == "external":
        return "ext:" + package_of(m["path"])
    return None


def edge_set(model: dict) -> set[tuple[str, str, str]]:
    out = set()
    for e in model.get("edges", []):
        a, b = node_of(model, e["from"]), node_of(model, e["to"])
        if a and b and a != b and not a.startswith("ext:"):
            out.add((a, b, e["kind"]))
    return out


# ---- diff -------------------------------------------------------------------


def diff_symbols(old: dict, new: dict) -> dict[str, str]:
    out = {}
    for sig in sorted(set(old) | set(new)):
        if sig not in old:
            out[sig] = "added"
        elif sig not in new:
            out[sig] = "removed"
        elif old[sig].get("hash") != new[sig].get("hash") or old[sig].get("mutability") != new[sig].get("mutability"):
            out[sig] = "changed"
    return out


def diff_modules(base: dict, head: dict) -> dict[str, dict]:
    """name -> {"status": added|removed|changed|same, "symbols": {sig: status}} for src modules."""
    b, h = src_modules(base), src_modules(head)
    out = {}
    for name in sorted(set(b) | set(h)):
        if name not in b:
            syms = {s: "added" for s in h[name]["symbols"]}
            out[name] = {"status": "added", "symbols": syms}
        elif name not in h:
            out[name] = {"status": "removed", "symbols": {s: "removed" for s in b[name]["symbols"]}}
        else:
            syms = diff_symbols(b[name]["symbols"], h[name]["symbols"])
            other = (
                b[name].get("events") != h[name].get("events")
                or b[name].get("errors") != h[name].get("errors")
                or b[name].get("storage") != h[name].get("storage")
                or b[name].get("kind") != h[name].get("kind")
            )
            out[name] = {"status": "changed" if syms or other else "same", "symbols": syms}
    return out


MUTABILITY_RANK = {"pure": 0, "view": 1, "nonpayable": 2, "payable": 3}


def api_rows(base: dict, head: dict) -> list[dict]:
    """External API changes of src modules: functions, events, errors, storage layout."""
    rows: list[dict] = []
    b, h = src_modules(base), src_modules(head)

    def row(module, kind, change, sig, detail="", breaking=False):
        rows.append(
            {"module": module, "kind": kind, "change": change, "signature": sig, "detail": detail, "breaking": breaking}
        )

    for name in sorted(set(b) | set(h)):
        if name not in b:
            row(name, h[name]["kind"], "added", name, h[name]["path"])
        elif name not in h:
            row(name, b[name]["kind"], "removed", name, b[name]["path"], True)
        old, new = b.get(name, {}), h.get(name, {})
        o_api = {s: v for s, v in old.get("symbols", {}).items() if v.get("api")}
        n_api = {s: v for s, v in new.get("symbols", {}).items() if v.get("api")}
        for sig in sorted(set(o_api) | set(n_api)):
            if sig not in o_api:
                v = n_api[sig]
                row(name, "function", "added", sig, f"{v['mutability']} {v['selector']}")
            elif sig not in n_api:
                row(name, "function", "removed", sig, o_api[sig]["selector"], True)
            elif o_api[sig]["mutability"] != n_api[sig]["mutability"]:
                om, nm = o_api[sig]["mutability"], n_api[sig]["mutability"]
                row(name, "function", "changed", sig, f"{om} → {nm}", not (om == "nonpayable" and nm == "payable"))
        oc, nc = old.get("symbols", {}).get("constructor"), new.get("symbols", {}).get("constructor")
        if name in b and name in h and oc and nc and oc.get("display") != nc.get("display"):
            row(name, "constructor", "changed", nc.get("display", ""), f"was {oc.get('display', '')}: deploy scripts")
        for kind in ("events", "errors"):
            o, n = old.get(kind, {}), new.get(kind, {})
            for sig in sorted(set(o) | set(n)):
                if sig not in o:
                    row(name, kind[:-1], "added", sig)
                elif sig not in n:
                    row(name, kind[:-1], "removed", sig, "", True)
        if name in b and name in h:
            rows.extend(storage_rows(name, old.get("storage", []), new.get("storage", [])))
    return rows


def storage_rows(module: str, old: list[dict], new: list[dict]) -> list[dict]:
    """Layout changes: a moved, retyped or removed variable breaks an upgradeable
    contract's storage; a variable appended after the old ones doesn't."""
    rows = []
    o = {v["name"]: v for v in old}
    n = {v["name"]: v for v in new}
    last = max(((v["slot"], v["offset"]) for v in old), default=(-1, -1))

    def row(change, sig, detail, breaking):
        rows.append(
            {
                "module": module,
                "kind": "storage",
                "change": change,
                "signature": sig,
                "detail": detail,
                "breaking": breaking,
            }
        )

    for name, v in o.items():
        if name not in n:
            row("removed", f"{v['type']} {name}", f"slot {v['slot']}", True)
        elif (v["slot"], v["offset"], v["type"]) != (n[name]["slot"], n[name]["offset"], n[name]["type"]):
            w = n[name]
            row(
                "changed",
                f"{w['type']} {name}",
                f"slot {v['slot']}+{v['offset']} {v['type']} → slot {w['slot']}+{w['offset']} {w['type']}",
                True,
            )
    # An added variable breaks the layout only by moving an existing one, and that
    # move is already its own 'changed' row: here it's informational.
    for name, v in n.items():
        if name not in o:
            appended = (v["slot"], v["offset"]) > last
            where = f"slot {v['slot']}+{v['offset']}" + ("" if appended else " (before existing variables)")
            row("added", f"{v['type']} {name}", where, False)
    return rows


# ---- flowcharts ---------------------------------------------------------------


def node_label(model_mods: dict, node: str) -> str:
    if node.startswith("ext:"):
        return f'{mid(node)}[["{esc(node[4:])}"]]'
    m = model_mods.get(node, {})
    kind = m.get("kind", "")
    tag = {"interface": "«interface» ", "library": "«library» "}.get(kind, "«abstract» " if m.get("abstract") else "")
    name = node.split("@")[0]
    if kind == "interface":
        return f'{mid(node)}(["{esc(tag + name)}"])'
    return f'{mid(node)}["{esc(tag + name)}"]'


def dependency_diff(base: dict, head: dict, mods: dict[str, dict]) -> str:
    """Touched src modules plus their direct neighbors; edges colored by change."""
    touched = {n for n, d in mods.items() if d["status"] != "same"}
    eb, eh = edge_set(base), edge_set(head)
    edges = eb | eh
    if not touched and eb == eh:
        return ""
    for a, b, _ in eb ^ eh:
        touched.update(x for x in (a, b) if not x.startswith("ext:"))
    nodes = set(touched)
    for a, b, _ in edges:
        if a in touched or b in touched:
            nodes.update((a, b))
    all_mods = {**base.get("modules", {}), **head.get("modules", {})}
    lines = ["flowchart LR"]
    for n in sorted(nodes):
        status = mods.get(n, {}).get("status", "same") if not n.startswith("ext:") else "ext"
        cls = {"same": "ctx", "ext": "ext"}.get(status, status)
        lines.append(f"  {node_label(all_mods, n)}:::{cls}")
    styles = []
    for i, (a, b, k) in enumerate(sorted(e for e in edges if e[0] in nodes and e[1] in nodes)):
        change = "added" if (a, b, k) not in eb else "removed" if (a, b, k) not in eh else "same"
        arrow = "-.->" if k == "inherits" else "-->"
        lines.append(f"  {mid(a)} {arrow}|{EDGE_LABEL.get(k, k)}| {mid(b)}")
        styles.append(f"  linkStyle {i} {EDGE_STYLE[change]}")
    return "\n".join(lines + styles + ["  " + c for c in CLASSDEFS])


def borders(head: dict, status: dict[str, str]) -> str:
    """Every src module, grouped by directory; packages collapsed; crossing edges drawn thick."""
    mods = src_modules(head)
    edges = edge_set(head)
    pairs: dict[tuple[str, str], set[str]] = {}
    for a, b, k in edges:
        pairs.setdefault((a, b), set()).add(EDGE_LABEL.get(k, k))
    if len(mods) > MAX_NODES:
        return borders_by_dir(head, set(status))
    groups: dict[str, list[str]] = {}
    for n, m in mods.items():
        groups.setdefault(group_of(m["path"]), []).append(n)
    exts = sorted({x for pair in pairs for x in pair if x.startswith("ext:")})
    lines = ["flowchart LR"]
    for i, (g, names) in enumerate(sorted(groups.items())):
        lines.append(f'  subgraph g{i}["{esc(g)}"]')
        for n in sorted(names):
            lines.append(f"    {node_label(mods, n)}:::{status.get(n, 'ctx')}")
        lines.append("  end")
    if exts:
        lines.append('  subgraph gext["external"]')
        lines.extend(f"    {node_label(mods, x)}:::ext" for x in exts)
        lines.append("  end")
    for (a, b), kinds in sorted(pairs.items()):
        crossing = b.startswith("ext:") or group_of(mods[a]["path"]) != group_of(mods.get(b, {}).get("path", ""))
        lines.append(f"  {mid(a)} {'==>' if crossing else '-->'}|{esc(', '.join(sorted(kinds)))}| {mid(b)}")
    return "\n".join(lines + ["  " + c for c in CLASSDEFS])


def borders_by_dir(head: dict, touched: set[str]) -> str:
    """Large projects: one node per directory, edges counted."""
    mods = src_modules(head)
    count: dict[tuple[str, str], int] = {}
    for a, b, _ in edge_set(head):
        ga = group_of(mods[a]["path"])
        gb = b[4:] if b.startswith("ext:") else group_of(mods.get(b, {}).get("path", ""))
        if ga != gb:
            count[(ga, gb)] = count.get((ga, gb), 0) + 1
    hot = {group_of(mods[n]["path"]) for n in touched if n in mods}
    groups = sorted({group_of(m["path"]) for m in mods.values()} | {g for pair in count for g in pair})
    lines = ["flowchart LR"]
    for g in groups:
        cls = "changed" if g in hot else ("ctx" if g in {group_of(m["path"]) for m in mods.values()} else "ext")
        lines.append(f'  {mid(g)}["{esc(g)}"]:::{cls}')
    for (a, b), c in sorted(count.items()):
        lines.append(f"  {mid(a)} ==>|{c}| {mid(b)}")
    return "\n".join(lines + ["  " + c for c in CLASSDEFS])


# ---- class diagram of impacted modules ------------------------------------------

VIS = {"external": "+", "public": "+", "internal": "#", "private": "-"}


def impacted(base: dict, head: dict, mods: dict[str, dict]) -> str:
    touched = sorted(n for n, d in mods.items() if d["status"] != "same")
    if not touched:
        return ""
    eb, eh = edge_set(base), edge_set(head)
    lines = ["classDiagram", "  direction LR"]
    styles = []
    neighbors: set[str] = set()
    rels = []
    for a, b, k in sorted(eb | eh):
        if a in touched or b in touched:
            gone = (a, b, k) not in eh
            neighbors.update(x for x in (a, b) if x not in touched)
            label = EDGE_LABEL.get(k, k) + (" (removed)" if gone else "" if (a, b, k) in eb else " (new)")
            if k == "inherits":
                rels.append(f"  {mid(b)} <|-- {mid(a)} : {esc(label)}")
            else:
                rels.append(f"  {mid(a)} {'..>' if k != 'calls' else '-->'} {mid(b)} : {esc(label)}")
    for n in touched:
        d = mods[n]
        m = head["modules"].get(n) or base["modules"][n]
        old_syms = base.get("modules", {}).get(n, {}).get("symbols", {})
        syms = {**old_syms, **m["symbols"]}
        lines.append(f'  class {mid(n)}["{esc(n.split("@")[0])}"] {{')
        kind = m.get("kind", "contract")
        lines.append(f"    <<{'abstract' if m.get('abstract') else kind}>>")
        for sig in sorted(syms, key=lambda s: (syms[s]["kind"] != "constructor", syms[s]["kind"] == "getter", s)):
            s = syms[sig]
            if s["kind"] == "getter" and sig not in d["symbols"]:
                continue  # unchanged public variables: noise
            mark = {"added": " NEW", "changed": " CHANGED", "removed": " REMOVED"}.get(d["symbols"].get(sig, ""), "")
            mut = s.get("mutability") if s.get("mutability") in ("view", "pure", "payable") else ""
            ret = " ".join(x for x in (mut, mark.strip()) if x)
            shown = s.get("display", sig) if s["kind"] != "function" else sig
            lines.append(f"    {VIS.get(s.get('visibility', ''), '+')}{esc(shown)}{(' ' + ret) if ret else ''}")
        lines.append("  }")
        styles.append(f"  style {mid(n)} {STYLE[d['status']]}")
    for n in sorted(neighbors):
        label = n[4:] if n.startswith("ext:") else n.split("@")[0]
        lines.append(f'  class {mid(n)}["{esc(label)}"]')
        styles.append(f"  style {mid(n)} {STYLE['ext' if n.startswith('ext:') else 'same']}")
    return "\n".join(lines + rels + styles)


STYLE = {
    "added": "fill:#dcfce7,stroke:#16a34a,color:#14532d",
    "changed": "fill:#fef3c7,stroke:#d97706,color:#78350f",
    "removed": "fill:#fee2e2,stroke:#dc2626,color:#7f1d1d",
    "same": "fill:#f1f5f9,stroke:#94a3b8,color:#334155",
    "ext": "fill:#e0e7ff,stroke:#6366f1,color:#312e81",
}


# ---- sequence diagrams ------------------------------------------------------------


def sequence(trace: dict) -> str:
    calls = trace.get("calls") or []
    if not calls:
        return ""
    ids: dict[str, str] = {}

    def pid(name: str) -> str:
        if name not in ids:
            ids[name] = f"p{len(ids)}"
        return ids[name]

    body: list[str] = []
    stack: list[dict] = []

    def close(c: dict) -> None:
        for ev in c.get("events") or []:
            body.append(f"  Note over {pid(c['to'])}: emit {esc(ev)}")
        if c.get("ok", True):
            body.append(f"  {pid(c['to'])}-->>{pid(c['from'])}: ok")
        else:
            body.append(f"  {pid(c['to'])}--x{pid(c['from'])}: revert {esc(c.get('error') or '')}")
        body.append(f"  deactivate {pid(c['to'])}")

    for c in calls:
        while stack and stack[-1]["depth"] >= c["depth"]:
            close(stack.pop())
        suffix = {"STATICCALL": " (view)", "DELEGATECALL": " (delegate)"}.get(c.get("kind", ""), "")
        if c.get("kind", "").startswith("CREATE"):
            suffix = ""
        body.append(f"  {pid(c['from'])}->>{pid(c['to'])}: {esc(c['fn'])}{suffix}")
        body.append(f"  activate {pid(c['to'])}")
        stack.append(c)
    while stack:
        close(stack.pop())
    head = ["sequenceDiagram"] + [f"  participant {i} as {esc(n)}" for n, i in ids.items()]
    return "\n".join(head + body)


# ---- the whole view -----------------------------------------------------------------


def diff_section(base: dict, head: dict, base_sha: str) -> dict:
    mods = diff_modules(base, head)
    rows = api_rows(base, head)
    touched = [n for n, d in mods.items() if d["status"] != "same"]
    return {
        "base": base_sha,
        "api": rows,
        "graph": dependency_diff(base, head, mods),
        "impacted": impacted(base, head, mods),
        "modules": {n: d for n, d in mods.items() if d["status"] != "same"},
        "summary": {
            "api_changes": len(rows),
            "breaking": sum(1 for r in rows if r["breaking"]),
            "modules_touched": len(touched),
            "symbols_touched": sum(len(mods[n]["symbols"]) for n in touched),
        },
    }


def render_view(head: dict, cycle_base: dict, task_base: dict, traces: list[dict], meta: dict) -> dict:
    task = diff_section(task_base, head, meta.get("task_base", ""))
    cycle = diff_section(cycle_base, head, meta.get("cycle_base", ""))
    reasons = meta.get("trace_reasons", {})
    return {
        **meta,
        "diffs": {"cycle": cycle, "task": task},
        "borders": borders(head, {n: d["status"] for n, d in task["modules"].items()}),
        "sequences": [
            {
                "test": t["test"],
                "status": t.get("status"),
                "reason": t.get("reason"),
                "why": reasons.get(t["test"], ""),
                "mermaid": sequence(t),
                "error": t.get("error", ""),
            }
            for t in traces
        ],
    }
