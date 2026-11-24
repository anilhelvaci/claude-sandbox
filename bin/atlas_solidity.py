# pyright: reportMissingImports=false
"""atlas extractor for stack = solidity. Runs under Slither's Python (not the host's).

    python atlas_solidity.py model  <root> <out.json>
    python atlas_solidity.py traces <root> <model.json> <wanted.json> <out.json>

'model' compiles <root> through Slither (crytic-compile drives forge/hardhat) and
writes the stack-agnostic model atlas renders:

    {"stack": "solidity",
     "modules": {<name>: {"kind", "path", "lines", "abstract",
                          "symbols": {<signature>: {"name", "kind", "visibility", "mutability",
                                                     "api", "selector", "lines", "hash"}},
                          "events": {<signature>: {"topic"}}, "errors": {<signature>: {"selector"}},
                          "storage": [{"name", "type", "slot", "offset"}]}},
     "edges": [{"from", "to", "kind"}]}       kind: inherits | uses | calls | creates

'traces' runs 'forge test --json -vvvv' for the wanted tests ({file: [test names]})
and decodes each Execution call tree with the model's selectors:

    [{"test": "<file>:<Contract>.<name>", "status", "calls": [
        {"depth", "from", "to", "fn", "kind", "ok", "events": [...], "error"}]}]

Everything here is deterministic: no LLM, only the compiler's view and the EVM's trace.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys

CHEATCODES = "0x7109709ecfa91a80626ff3989d68f67f5b1dd12d"
CONSOLE = "0x000000000000000000636f6e736f6c652e6c6f67"
CREATE2_DEPLOYER = "0x4e59b44847b379578588920ca78fbf26c0b4956c"
MAX_DEPTH = 6
MAX_CALLS = 80


def keccak_hex(text: str) -> str:
    from Crypto.Hash import keccak  # pycryptodome, a Slither dependency

    return "0x" + keccak.new(digest_bits=256, data=text.encode()).hexdigest()


def source_of(sm) -> str:
    try:
        with open(sm.filename.absolute, "rb") as f:
            f.seek(sm.start)
            return f.read(sm.length).decode(errors="replace")
    except OSError:
        return ""


def body_hash(sm) -> str:
    """A whitespace- and comment-insensitive hash of a definition's source."""
    text = source_of(sm)
    text = re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"\s+", "", text)
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def lines_of(sm) -> list[int]:
    lines = list(sm.lines) if sm.lines else []
    return [lines[0], lines[-1]] if lines else [0, 0]


def rel_path(path: str, root: str) -> str:
    """Path relative to the snapshot root. Symlinked dirs (submodules) resolve
    outside it ('../...'), which atlas classifies as external."""
    real_root = os.path.realpath(root)
    full = path if os.path.isabs(path) else os.path.join(real_root, path)
    return os.path.relpath(os.path.realpath(full), real_root)


def mutability(f) -> str:
    if f.pure:
        return "pure"
    if f.view:
        return "view"
    return "payable" if f.payable else "nonpayable"


def module_key(c, names: dict[str, int]) -> str:
    """Contract names are unique in most projects; on a clash, qualify with the path."""
    if names.get(c.name, 0) > 1:
        return f"{c.name}@{c.source_mapping.filename.relative}"
    return c.name


def extract_model(root: str) -> dict:
    from slither import Slither
    from slither.core.declarations import Contract
    from slither.slithir.operations import HighLevelCall, LibraryCall, NewContract

    os.chdir(root)
    sl = Slither(".", foundry_compile_all=True, hardhat_ignore_compile=False)
    contracts = list(sl.contracts)
    names: dict[str, int] = {}
    for c in contracts:
        names[c.name] = names.get(c.name, 0) + 1
    key = {id(c): module_key(c, names) for c in contracts}
    by_name = {c.name: c for c in contracts}

    modules: dict[str, dict] = {}
    edges: set[tuple[str, str, str]] = set()
    for c in contracts:
        me = key[id(c)]
        sm = c.source_mapping
        symbols: dict[str, dict] = {}
        for f in list(c.functions_declared) + list(c.modifiers_declared):
            ftype = getattr(f.function_type, "name", "NORMAL") if hasattr(f, "function_type") else "MODIFIER"
            if ftype == "CONSTRUCTOR_VARIABLES" or ftype == "CONSTRUCTOR_CONSTANT_VARIABLES":
                continue
            is_modifier = f in c.modifiers_declared
            kind = (
                "modifier"
                if is_modifier
                else {"CONSTRUCTOR": "constructor", "FALLBACK": "fallback", "RECEIVE": "receive"}.get(ftype, "function")
            )
            api = not is_modifier and f.visibility in ("public", "external") and kind == "function"
            # Constructor/fallback/receive are keyed by kind, so a new parameter list
            # reads as 'changed', not as one removed and one added.
            sig = f.solidity_signature if kind == "function" else (f.full_name if is_modifier else kind)
            symbols[sig] = {
                "name": f.name,
                "display": f.full_name,
                "kind": kind,
                "visibility": f.visibility,
                "mutability": "" if is_modifier else mutability(f),
                "api": api,
                "selector": keccak_hex(sig)[:10] if api else "",
                "lines": lines_of(f.source_mapping),
                "hash": body_hash(f.source_mapping),
            }
            for ir in f.slithir_operations if not is_modifier else []:
                target, ekind = None, ""
                if isinstance(ir, LibraryCall):
                    target, ekind = ir.destination, "uses"
                elif isinstance(ir, HighLevelCall):
                    t = getattr(ir.destination, "type", None)
                    target, ekind = getattr(t, "type", None), "calls"
                elif isinstance(ir, NewContract):
                    target, ekind = by_name.get(str(ir.contract_name)), "creates"
                if isinstance(target, Contract) and id(target) in key and target is not c:
                    edges.add((me, key[id(target)], ekind))
        for v in c.state_variables_declared:
            if v.visibility == "public":
                sig = v.solidity_signature
                symbols[sig] = {
                    "name": v.name,
                    "kind": "getter",
                    "visibility": "public",
                    "mutability": "view",
                    "api": True,
                    "selector": keccak_hex(sig)[:10],
                    "lines": lines_of(v.source_mapping),
                    "hash": body_hash(v.source_mapping),
                }
            t = getattr(v.type, "type", None)
            if isinstance(t, Contract) and id(t) in key and t is not c:
                edges.add((me, key[id(t)], "holds"))
        for parent in c.immediate_inheritance:
            if id(parent) in key:
                edges.add((me, key[id(parent)], "inherits"))
        for libs in c.using_for_complete.values():
            for lib_type in libs:
                t = getattr(lib_type, "type", None)
                if isinstance(t, Contract) and id(t) in key:
                    edges.add((me, key[id(t)], "uses"))
        storage = []
        if c.contract_kind == "contract" and not c.is_abstract:
            for v in c.storage_variables_ordered:
                try:
                    slot, offset = c.compilation_unit.storage_layout_of(c, v)
                except (KeyError, AttributeError):
                    continue
                storage.append({"name": v.name, "type": str(v.type), "slot": int(slot), "offset": int(offset)})
        modules[me] = {
            "kind": c.contract_kind,
            "abstract": bool(getattr(c, "is_abstract", False)),
            "path": rel_path(sm.filename.absolute or sm.filename.relative, root),
            "lines": lines_of(sm),
            "symbols": symbols,
            "events": {e.full_name: {"topic": keccak_hex(e.full_name)} for e in c.events_declared},
            "errors": {e.full_name: {"selector": keccak_hex(e.full_name)[:10]} for e in c.custom_errors_declared},
            "storage": storage,
        }
    # 'holds' (a state variable typed as another contract) is a dependency even
    # when nothing calls it yet; fold it into 'calls' when both exist.
    final = set()
    for a, b, k in edges:
        if k == "holds" and (a, b, "calls") in edges:
            continue
        final.add((a, b, "calls" if k == "holds" else k))
    return {
        "stack": "solidity",
        "modules": modules,
        "edges": [{"from": a, "to": b, "kind": k} for a, b, k in sorted(final)],
    }


# ---- traces -----------------------------------------------------------------


def decode_tables(model: dict) -> tuple[dict, dict, dict]:
    """selector -> [(module, signature)], topic -> event name, error selector -> error signature."""
    sels: dict[str, list[tuple[str, str]]] = {}
    topics: dict[str, str] = {}
    errors: dict[str, str] = {}
    for mname, m in model["modules"].items():
        for sig, s in m["symbols"].items():
            if s.get("selector"):
                sels.setdefault(s["selector"], []).append((mname, sig))
        for sig, e in m["events"].items():
            topics[e["topic"]] = sig.split("(")[0]
        for sig, e in m["errors"].items():
            errors[e["selector"]] = sig
    errors["0x08c379a0"] = "Error(string)"
    errors["0x4e487b71"] = "Panic(uint256)"
    return sels, topics, errors


def run_traces(root: str, model: dict, wanted: dict[str, list[str]]) -> list[dict]:
    """wanted: {path: ["<Contract>.<test>"]}. Inherited copies of a test in other
    contracts of the file also run (forge matches by name) but are dropped here."""
    sels, topics, errors = decode_tables(model)
    out: list[dict] = []
    for path, tests in sorted(wanted.items()):
        if not tests:
            continue
        keep = set(tests)
        names = sorted({t.split(".", 1)[1] for t in tests})
        pattern = "^(" + "|".join(re.escape(t) for t in names) + r")\("
        proc = subprocess.run(
            ["forge", "test", "--json", "-vvvv", "--match-path", path, "--match-test", pattern],
            cwd=root,
            text=True,
            capture_output=True,
        )
        try:
            data = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            out.append({"test": path, "status": "error", "error": (proc.stderr or proc.stdout)[-2000:], "calls": []})
            continue
        for suite, result in sorted(data.items()):
            contract = suite.split(":")[-1]
            for tname, r in sorted(result.get("test_results", {}).items()):
                if f"{contract}.{tname.split('(')[0]}" not in keep:
                    continue
                labels = {a.lower(): n for a, n in (r.get("labeled_addresses") or {}).items()}
                calls = decode_execution(r.get("traces") or [], labels, sels, topics, errors, contract)
                out.append(
                    {
                        "test": f"{path}:{contract}.{tname.split('(')[0]}",
                        "status": r.get("status", "?"),
                        "reason": r.get("reason"),
                        "calls": calls,
                    }
                )
    return out


def decode_execution(traces, labels, sels, topics, errors, test_contract) -> list[dict]:
    arena = None
    for phase, body in traces:
        if phase == "Execution":
            arena = body.get("arena") or []
    if not arena:
        return []
    root_addr = arena[0]["trace"]["address"].lower()
    names: dict[str, str] = {root_addr: test_contract}
    names.update(labels)

    def who(addr: str, selector: str = "") -> str:
        addr = addr.lower()
        if addr in names:
            return names[addr]
        owners = {m for m, _ in sels.get(selector, [])}
        if len(owners) == 1:  # the only contract with this function: a deterministic guess
            return next(iter(owners))
        return addr[:8] + "…" + addr[-4:]

    calls: list[dict] = []

    def walk(idx: int, depth: int) -> None:
        node = arena[idx]
        t = node["trace"]
        addr = t["address"].lower()
        if addr in (CHEATCODES, CONSOLE) or depth > MAX_DEPTH or len(calls) >= MAX_CALLS:
            return
        kind = t.get("kind", "CALL")
        data = t.get("data") or "0x"
        selector = data[:10] if len(data) >= 10 else ""
        callee = who(addr, selector)
        if kind.startswith("CREATE"):
            fn = "new"
        else:
            sigs = sorted({s for _, s in sels.get(selector, [])})
            fn = sigs[0] if len(sigs) == 1 else (selector or "fallback/receive")
        error = ""
        if not t.get("success", True):
            output = t.get("output") or "0x"
            error = errors.get(output[:10], output[:10] or "revert")
        events = []
        for log in node.get("logs") or []:
            topics0 = (log.get("raw_log") or {}).get("topics") or []
            if topics0:
                events.append(topics.get(topics0[0], topics0[0][:10]))
        if depth > 0:
            calls.append(
                {
                    "depth": depth,
                    "from": who(t["caller"]),
                    "to": callee,
                    "fn": fn,
                    "kind": kind,
                    "ok": bool(t.get("success", True)),
                    "events": events,
                    "error": error,
                }
            )
        for child in node.get("children") or []:
            walk(child, depth + 1)

    walk(0, 0)
    return calls


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "model":
        model = extract_model(os.path.abspath(argv[1]))
    elif len(argv) == 5 and argv[0] == "traces":
        with open(argv[2]) as f:
            model = json.load(f)
        with open(argv[3]) as f:
            wanted = json.load(f)
        model = run_traces(os.path.abspath(argv[1]), model, wanted)  # type: ignore[assignment]
    else:
        print(__doc__, file=sys.stderr)
        return 2
    out = argv[-1]
    with open(out + ".tmp", "w") as f:
        json.dump(model, f, indent=1, sort_keys=True)
    os.replace(out + ".tmp", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
