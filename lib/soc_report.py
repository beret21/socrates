#!/usr/bin/env python3
"""Socrates — Claude Code settings, harness, and session status analyzer.

Usage:
    soc_report.py --terminal   ANSI summary for the terminal (socrates map)
    soc_report.py --html       generate the tabbed HTML dashboard and open it
                               (socrates report)

Read-only inputs: ~/.claude/, ~/.claude.json, per-project .claude/ folders,
and the CLAUDE.md chain from the filesystem root down to each project
(official loading rule: https://code.claude.com/docs/en/memory#how-claude-md-files-load).
The only write target is ~/.claude/socrates/report.html.
Python standard library only.
"""

import html
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

CLAUDE_MEM_DB = Path.home() / ".claude-mem" / "claude-mem.db"

HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
REGISTRY = CLAUDE_DIR / "socrates" / "sessions.json"
REPORT_PATH = CLAUDE_DIR / "socrates" / "report.html"

# ── Data collection ──────────────────────────────────────────


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def settings_summary(path: Path) -> dict:
    """Summarize one settings(.local).json file."""
    data = load_json(path)
    if not isinstance(data, dict):
        return {}
    out = {}
    if "model" in data:
        out["model"] = data["model"]
    if "language" in data:
        out["language"] = data["language"]
    hooks = data.get("hooks")
    if isinstance(hooks, dict):
        out["hooks"] = {k: len(v) if isinstance(v, list) else 1 for k, v in hooks.items()}
    plugins = data.get("enabledPlugins")
    if isinstance(plugins, dict):
        out["plugins"] = [k for k, v in plugins.items() if v]
    mcp = data.get("mcpServers")
    if isinstance(mcp, dict):
        out["mcpServers"] = sorted(mcp.keys())
    perms = data.get("permissions")
    if isinstance(perms, dict):
        out["permissions"] = {k: len(v) for k, v in perms.items() if isinstance(v, list)}
    if "statusLine" in data:
        out["statusLine"] = True
    return out


def file_kb(p: Path) -> float:
    try:
        return round(p.stat().st_size / 1024, 1)
    except OSError:
        return 0.0


def claude_md_chain(cwd: Path) -> list:
    """The memory files a session started in `cwd` actually loads, in load order.

    Official rule (docs/en/memory): user memory first, then CLAUDE.md /
    CLAUDE.local.md walking the tree from the filesystem root DOWN to cwd
    (all concatenated), plus rules folders. Subdirectory files are on-demand
    and therefore not listed here.
    """
    chain = []

    def add(p: Path, scope: str):
        if p.is_file():
            chain.append({"path": str(p).replace(str(HOME), "~"),
                          "scope": scope, "kb": file_kb(p)})

    add(CLAUDE_DIR / "CLAUDE.md", "user")
    rules = CLAUDE_DIR / "rules"
    if rules.is_dir():
        for r in sorted(rules.glob("*.md")):
            add(r, "user rules")

    ancestors = [*reversed(cwd.parents), cwd]   # root → cwd (official order)
    for d in ancestors:
        if d == HOME:
            continue                            # ~/CLAUDE.md is not project scope
        scope = "project" if d == cwd else "ancestor"
        add(d / "CLAUDE.md", scope)
        add(d / "CLAUDE.local.md", f"{scope} (local)")
    add(cwd / ".claude" / "CLAUDE.md", "project (.claude)")
    prules = cwd / ".claude" / "rules"
    if prules.is_dir():
        for r in sorted(prules.glob("*.md")):
            add(r, "project rules")
    return chain


def project_xray(cwd: Path, storage_dir=None) -> dict:   # storage_dir: Path or None (3.9-compatible)
    """Everything Claude would pick up for a session started in `cwd`."""
    layers = []
    for name in ("settings.json", "settings.local.json"):
        p = CLAUDE_DIR / name
        if p.is_file():
            layers.append({"scope": "user", "path": str(p).replace(str(HOME), "~"),
                           "summary": settings_summary(p)})
    for name in ("settings.json", "settings.local.json"):
        p = cwd / ".claude" / name
        if p.is_file():
            layers.append({"scope": "project", "path": str(p).replace(str(HOME), "~"),
                           "summary": settings_summary(p)})

    local = {}
    for kind in ("skills", "agents", "commands"):
        items = list_md_items(cwd / ".claude" / kind)
        if items:
            local[kind] = items

    mem = {"exists": False, "files": 0}
    if storage_dir is not None:
        mdir = storage_dir / "memory"
        if mdir.is_dir():
            mem = {"exists": True, "files": len(list(mdir.glob("*.md")))}

    return {
        "layers": layers,
        "chain": claude_md_chain(cwd),
        "mcp_json": (cwd / ".mcp.json").is_file(),
        "local_harness": local,
        "memory": mem,
    }


def list_md_items(base: Path) -> list:
    """Collect item names from a skills/agents/commands folder."""
    if not base.is_dir():
        return []
    items = []
    for child in sorted(base.iterdir()):
        if child.name.startswith("."):
            continue
        if child.is_dir() and (child / "SKILL.md").is_file():
            items.append(child.name)
        elif child.suffix == ".md" and child.stem.upper() not in ("CLAUDE", "README"):
            items.append(child.stem)
    return items


def harness_inventory(cwd: Path) -> dict:
    inv = {}
    for scope, root in (("global", CLAUDE_DIR), ("project", cwd / ".claude")):
        for kind in ("skills", "agents", "commands"):
            items = list_md_items(root / kind)
            if items:
                inv.setdefault(scope, {})[kind] = items
    return inv


def first_fields(jsonl: Path, max_lines: int = 60) -> dict:
    out = {"cwd": "", "slug": "", "first_msg": ""}
    try:
        with jsonl.open(encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue
                if not out["cwd"] and isinstance(rec.get("cwd"), str):
                    out["cwd"] = rec["cwd"]
                if not out["slug"] and isinstance(rec.get("slug"), str):
                    out["slug"] = rec["slug"]
                if not out["first_msg"] and rec.get("type") == "user":
                    content = (rec.get("message") or {}).get("content")
                    if isinstance(content, list):
                        content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
                    if isinstance(content, str):
                        text = content.replace("\n", " ").strip()
                        if text and not text.startswith("<"):
                            out["first_msg"] = text[:120]
                if all(out.values()):
                    break
    except OSError:
        pass
    return out


def parse_memory_frontmatter(p: Path) -> dict:
    """Read name/description/type plus the FULL content of an auto-memory file
    (contents are embedded in the dashboard for the click-to-view panel)."""
    out = {"file": p.name, "name": p.stem, "description": "", "type": "", "kb": file_kb(p),
           "path": str(p).replace(str(HOME), "~"), "content": ""}
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return out
    out["content"] = text
    for ln in text.splitlines()[:15]:
        s = ln.strip()
        if s.startswith("name:"):
            out["name"] = s[5:].strip()
        elif s.startswith("description:"):
            out["description"] = s[12:].strip()
        elif s.startswith("type:"):
            out["type"] = s[5:].strip()
    return out


def collect_memories(storage_to_cwd: dict) -> list:
    """Per-project auto-memory inventory (auto memory is project-scoped only —
    there is no global auto-memory directory)."""
    mems = []
    if not PROJECTS_DIR.is_dir():
        return mems
    for proj_dir in sorted(PROJECTS_DIR.iterdir()):
        mdir = proj_dir / "memory"
        if not mdir.is_dir():
            continue
        files = [parse_memory_frontmatter(f) for f in sorted(mdir.glob("*.md"))
                 if f.name != "MEMORY.md"]
        if not files:
            continue
        cwd = storage_to_cwd.get(str(proj_dir), "")
        label = Path(cwd).name if cwd else proj_dir.name
        mems.append({"project": label, "cwd": cwd.replace(str(HOME), "~") if cwd else f"(storage: {proj_dir.name})",
                     "files": files})
    mems.sort(key=lambda m: len(m["files"]), reverse=True)
    return mems


def collect_injection(xrays: dict) -> dict:
    """Third-party memory layers that inject past-conversation context into
    sessions — the usual answer to 'why does Claude suddenly remember X?'."""
    inj = {"claude_mem": None, "md_blocks": [], "session_hooks": []}

    md = HOME / ".claude-mem"
    if md.is_dir():
        try:
            kb = int(subprocess.run(["du", "-sk", str(md)], capture_output=True,
                                    text=True).stdout.split()[0])
        except Exception:
            kb = 0
        comps = sorted(p.name for p in md.iterdir() if not p.name.startswith("."))
        inj["claude_mem"] = {"path": "~/.claude-mem", "mb": round(kb / 1024, 1),
                             "components": comps}

    seen = set()
    for x in xrays.values():
        for c in x["chain"]:
            seen.add(c["path"])
    seen.add(str(CLAUDE_DIR / "CLAUDE.md").replace(str(HOME), "~"))
    for pstr in sorted(seen):
        p = Path(pstr.replace("~", str(HOME), 1))
        try:
            if p.is_file() and "claude-mem-context" in p.read_text(encoding="utf-8"):
                inj["md_blocks"].append(pstr)
        except OSError:
            pass

    settings = load_json(CLAUDE_DIR / "settings.json") or {}
    for grp in (settings.get("hooks", {}).get("SessionStart") or []):
        for h in (grp.get("hooks") or []):
            cmd = h.get("command", "")
            if cmd:
                inj["session_hooks"].append(cmd[:110])

    # The exact text being injected (the <claude-mem-context> blocks)
    inj["blocks"] = []
    for pstr in inj["md_blocks"]:
        p = Path(pstr.replace("~", str(HOME), 1))
        try:
            m = re.search(r"<claude-mem-context>.*?</claude-mem-context>",
                          p.read_text(encoding="utf-8"), re.S)
            if m:
                inj["blocks"].append({"path": pstr, "kb": round(len(m.group(0)) / 1024, 1),
                                      "content": m.group(0)})
        except OSError:
            pass

    # claude-mem's store, browsed read-only (titles only — full text via 'socrates mem')
    inj["db"] = {"counts": {}, "obs": []}
    if CLAUDE_MEM_DB.is_file():
        try:
            con = sqlite3.connect(f"file:{CLAUDE_MEM_DB}?mode=ro", uri=True)
            cur = con.cursor()
            for t in ("observations", "session_summaries", "user_prompts"):
                try:
                    inj["db"]["counts"][t] = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                except sqlite3.Error:
                    pass
            try:
                for r in cur.execute(
                        "SELECT id, COALESCE(title,''), COALESCE(project,''), "
                        "COALESCE(type,''), COALESCE(substr(created_at,1,10),'') "
                        "FROM observations ORDER BY id DESC"):
                    inj["db"]["obs"].append({"i": r[0], "t": r[1][:90], "p": r[2],
                                             "y": r[3], "d": r[4]})
            except sqlite3.Error:
                pass
            con.close()
        except sqlite3.Error:
            pass
    return inj


def mem_search(args: list) -> int:
    """socrates mem <text|id> — read-only search of claude-mem's observations."""
    if not CLAUDE_MEM_DB.is_file():
        print("claude-mem store not found (~/.claude-mem/claude-mem.db)")
        return 1
    query = " ".join(args).strip()
    if not query:
        print("Usage: socrates mem <text>   full-text search of stored observations")
        print("       socrates mem <id>     show one observation in full")
        return 1
    con = sqlite3.connect(f"file:{CLAUDE_MEM_DB}?mode=ro", uri=True)
    cur = con.cursor()

    if query.isdigit():
        row = cur.execute("SELECT * FROM observations WHERE id=?", (int(query),)).fetchone()
        if not row:
            print(f"No observation with id {query}")
            return 1
        cols = [d[0] for d in cur.description]
        print(f"\n{BOLD}observation #{query}{RST}")
        for k, v in zip(cols, row):
            if v in (None, ""):
                continue
            v = str(v)
            if len(v) > 2000:
                v = v[:2000] + f"… ({len(v)} chars)"
            print(f"  {GREEN}{k:<16}{RST} {v}")
        con.close()
        return 0

    rows = []
    try:
        rows = cur.execute(
            "SELECT rowid FROM observations_fts WHERE observations_fts MATCH ? "
            "ORDER BY rowid DESC LIMIT 30", (query,)).fetchall()
        ids = [r[0] for r in rows]
        rows = []
        if ids:
            ph = ",".join("?" * len(ids))
            rows = cur.execute(
                f"SELECT id, substr(created_at,1,10), COALESCE(project,''), "
                f"COALESCE(title,''), COALESCE(subtitle,'') FROM observations "
                f"WHERE id IN ({ph}) ORDER BY id DESC", ids).fetchall()
    except sqlite3.Error:
        rows = []
    if not rows:   # FTS miss or error → LIKE fallback
        like = f"%{query}%"
        rows = cur.execute(
            "SELECT id, substr(created_at,1,10), COALESCE(project,''), "
            "COALESCE(title,''), COALESCE(subtitle,'') FROM observations "
            "WHERE title LIKE ? OR text LIKE ? ORDER BY id DESC LIMIT 30",
            (like, like)).fetchall()
    con.close()
    if not rows:
        print(f"No observations matched: {query}")
        return 1
    print(f"\n{BOLD}{len(rows)} observation(s) matching \"{query}\"{RST} {DIM}(newest first){RST}")
    for i, d, p, t, st in rows:
        print(f"  {GOLD}#{i:<5}{RST} {DIM}{d}{RST} {BLUE}{p:<14}{RST} {t}")
        if st:
            print(f"         {DIM}{st[:100]}{RST}")
    print(f"\n{DIM}full record: socrates mem <id>{RST}")
    return 0


def collect_identity() -> dict:
    """How Claude identifies this user (~/.claude.json, local file)."""
    data = load_json(HOME / ".claude.json") or {}
    acct = data.get("oauthAccount") or {}
    keep = ("displayName", "emailAddress", "organizationName", "organizationType",
            "organizationRole", "billingType", "seatTier", "userRateLimitTier",
            "accountCreatedAt", "subscriptionCreatedAt")
    ident = {k: acct.get(k) for k in keep if acct.get(k)}
    if data.get("userID"):
        ident["userID"] = str(data["userID"])[:12] + "…"
    if data.get("firstStartTime"):
        ident["firstStartTime"] = data["firstStartTime"]
    return ident


def scan_sessions() -> list:
    aliases = load_json(REGISTRY) or {}
    sessions = []
    if not PROJECTS_DIR.is_dir():
        return sessions
    for proj_dir in PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir():
            continue
        for jsonl in proj_dir.glob("*.jsonl"):
            uuid = jsonl.stem
            try:
                mtime = jsonl.stat().st_mtime
            except OSError:
                continue
            info = first_fields(jsonl)
            sessions.append({
                "uuid": uuid,
                "mtime": mtime,
                "cwd": info["cwd"],
                "slug": info["slug"],
                "first_msg": info["first_msg"],
                "alias": (aliases.get(uuid) or {}).get("alias", ""),
                "storage": str(proj_dir),
            })
    sessions.sort(key=lambda s: s["mtime"], reverse=True)
    return sessions


def collect(cwd: Path) -> dict:
    sessions = scan_sessions()
    by_project = {}
    storage_of = {}
    for s in sessions:
        key = s["cwd"] or "(unknown)"
        by_project.setdefault(key, []).append(s)
        storage_of.setdefault(key, Path(s["storage"]))

    xrays = {}
    for proj in by_project:
        if proj == "(unknown)":
            continue
        p = Path(proj)
        if p.is_dir():
            xrays[proj] = project_xray(p, storage_of.get(proj))

    storage_to_cwd = {s["storage"]: s["cwd"] for s in sessions if s["cwd"]}
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "inventory": harness_inventory(cwd),
        "sessions": sessions,
        "by_project": by_project,
        "xrays": xrays,
        "memories": collect_memories(storage_to_cwd),
        "identity": collect_identity(),
        "injection": collect_injection(xrays),
        "aliases": load_json(REGISTRY) or {},
        "global_settings": [
            {"name": n, "summary": settings_summary(CLAUDE_DIR / n)}
            for n in ("settings.json", "settings.local.json")
            if (CLAUDE_DIR / n).is_file()
        ],
    }


# ── Terminal output (socrates map) ───────────────────────────

GOLD, BLUE, GREEN, DIM, BOLD, RST = "\033[33m", "\033[34m", "\033[32m", "\033[2m", "\033[1m", "\033[0m"


def reltime(mtime: float) -> str:
    diff = int(datetime.now().timestamp() - mtime)
    if diff < 60:
        return f"{diff}s ago"
    if diff < 3600:
        return f"{diff // 60}m ago"
    if diff < 86400:
        return f"{diff // 3600}h ago"
    return f"{diff // 86400}d ago"


def render_terminal(data: dict) -> None:
    cwd = Path.cwd()
    print(f"\n{BOLD}{GOLD}Socrates{RST} — Know Your Self  {DIM}({data['generated_at']}){RST}\n")

    print(f"{BOLD}■ Global settings (~/.claude){RST}")
    for e in data["global_settings"]:
        s = e["summary"]
        parts = []
        if "model" in s:
            parts.append(f"model={s['model']}")
        if "hooks" in s:
            parts.append(f"hooks={len(s['hooks'])} events")
        if "plugins" in s:
            parts.append(f"plugins={len(s['plugins'])}")
        if "mcpServers" in s:
            parts.append(f"mcp={len(s['mcpServers'])}")
        if "permissions" in s:
            parts.append("permissions(" + ", ".join(f"{k}:{v}" for k, v in s["permissions"].items()) + ")")
        print(f"  {GREEN}{e['name']}{RST}  {DIM}{' · '.join(parts)}{RST}")

    print(f"\n{BOLD}■ CLAUDE.md chain for THIS directory{RST} {DIM}(loaded root→cwd, all concatenated){RST}")
    chain = claude_md_chain(cwd)
    if not chain:
        print(f"  {DIM}(none){RST}")
    total = 0.0
    for c in chain:
        total += c["kb"]
        print(f"  {GREEN}{c['scope']:<18}{RST} {c['path']}  {DIM}{c['kb']}KB{RST}")
    if chain:
        print(f"  {DIM}→ {len(chain)} file(s), {round(total, 1)}KB injected into every session here{RST}")

    print(f"\n{BOLD}■ Harness inventory (skills / agents / commands){RST}")
    if not data["inventory"]:
        print(f"  {DIM}(none){RST}")
    for scope, kinds in data["inventory"].items():
        print(f"  {GREEN}{scope}{RST}")
        for kind, items in kinds.items():
            print(f"    └ {kind} ({len(items)}): {DIM}{', '.join(items)}{RST}")

    print(f"\n{BOLD}■ Projects × sessions (top 12 by recent activity){RST}")
    ranked = sorted(data["by_project"].items(), key=lambda kv: kv[1][0]["mtime"], reverse=True)
    for pcwd, sess in ranked[:12]:
        short = pcwd.replace(str(HOME), "~")
        named = [s for s in sess if s["alias"]]
        tag = f" {GOLD}★{len(named)}{RST}" if named else ""
        print(f"  {BLUE}{Path(pcwd).name:<24}{RST} sessions {len(sess):>3}  {DIM}{reltime(sess[0]['mtime'])}{RST}{tag}  {DIM}{short}{RST}")

    n_mem_proj = len(data["memories"])
    n_mem_files = sum(len(m["files"]) for m in data["memories"])
    print(f"\n{BOLD}■ Auto-memory{RST} {DIM}(project-scoped; details in 'socrates report' → Memory & Identity){RST}")
    print(f"  {n_mem_proj} project(s), {n_mem_files} memory file(s)")

    total_s = len(data["sessions"])
    print(f"\n{DIM}{len(data['by_project'])} projects, {total_s} sessions · full dashboard: 'socrates report'{RST}\n")


# ── HTML output (socrates report) ────────────────────────────


def esc(s) -> str:
    return html.escape(str(s), quote=True)


CSS = """
:root { --bg:#ffffff; --panel:#f7f8fa; --panel2:#eef1f5; --text:#1f2430; --dim:#6b7280;
        --line:#dde2ea; --gold:#a16207; --blue:#2563eb; --green:#15803d; }
* { box-sizing:border-box; margin:0; padding:0; }
body { background:var(--bg); color:var(--text); font-family:-apple-system,"Segoe UI",sans-serif;
       line-height:1.6; padding:28px 24px 80px; }
.wrap { max-width:1150px; margin:0 auto; }
h1 { font-size:26px; } h1 .gold { color:var(--gold); }
.sub { color:var(--dim); font-size:13px; margin-bottom:18px; }
nav.tabs { display:flex; gap:6px; border-bottom:2px solid var(--line); margin-bottom:20px; flex-wrap:wrap; }
nav.tabs button { background:none; border:none; border-bottom:3px solid transparent; padding:8px 14px;
  font-size:14px; color:var(--dim); cursor:pointer; }
nav.tabs button.on { color:var(--gold); border-bottom-color:var(--gold); font-weight:600; }
section.tab { display:none; } section.tab.on { display:block; }
h2 { font-size:17px; margin:24px 0 10px; }
table { width:100%; border-collapse:collapse; font-size:13px; margin:8px 0 18px; }
th,td { border:1px solid var(--line); padding:7px 10px; text-align:left; }
th { background:var(--panel2); } td { background:var(--panel); }
tr.aliased td { background:#fdf6e3; } tr.aliased td:first-child { color:var(--gold); font-weight:600; }
td.msg { color:var(--dim); font-size:12px; }
button.cp { background:var(--panel2); color:var(--blue); border:1px solid var(--line); border-radius:5px;
  padding:3px 10px; font-size:12px; cursor:pointer; font-family:Menlo,monospace; }
button.cp:hover { border-color:var(--blue); }
code { font-family:Menlo,monospace; font-size:12px; background:var(--panel2); border:1px solid var(--line);
  border-radius:4px; padding:1px 5px; color:#92400e; }
.node { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px 16px; margin:8px 0; }
.scope { color:var(--gold); font-weight:600; font-size:14px; margin-bottom:4px; }
.detail { font-size:13px; }
.chip { display:inline-block; background:var(--panel2); border:1px solid var(--line); border-radius:10px;
  padding:1px 10px; margin:2px; font-size:12px; font-family:Menlo,monospace; color:var(--blue); }
.dim { color:var(--dim); }
.kpis { display:flex; gap:14px; flex-wrap:wrap; margin:14px 0; }
.kpi { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px 22px; min-width:130px; }
.kpi b { font-size:24px; display:block; } .kpi span { color:var(--dim); font-size:12px; }
select#xsel { font-size:14px; padding:6px 10px; border:1px solid var(--line); border-radius:6px;
  background:var(--panel); max-width:100%; }
.chainbar { display:flex; align-items:center; gap:6px; margin:4px 0; font-size:13px; flex-wrap:wrap; }
.chainbar .seg { background:#fde68a; border:1px solid var(--line); border-radius:4px; padding:0 6px;
  font-family:Menlo,monospace; font-size:11px; white-space:nowrap; }
.warn { color:#b45309; }
#toast { position:fixed; bottom:24px; right:24px; background:var(--gold); color:#fff;
  padding:8px 16px; border-radius:8px; font-size:13px; display:none; }
tr.mrow { cursor:pointer; } tr.mrow:hover td { background:var(--panel2); }
#mpanel { position:fixed; top:0; right:0; width:min(560px,92vw); height:100vh; background:var(--bg);
  border-left:1px solid var(--line); box-shadow:-8px 0 24px rgba(0,0,0,.12); padding:20px 22px;
  overflow:auto; z-index:50; transform:translateX(105%); transition:transform .18s ease; }
#mpanel.open { transform:translateX(0); }
#mpanel h3 { font-size:16px; color:var(--gold); margin-bottom:2px; }
#mpanel .meta { font-size:12px; color:var(--dim); margin-bottom:12px; }
#mpanel pre { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px;
  font-family:Menlo,monospace; font-size:12px; line-height:1.55; white-space:pre-wrap;
  word-break:break-word; }
#mpanel .x { position:absolute; top:14px; right:16px; background:none; border:none; font-size:20px;
  color:var(--dim); cursor:pointer; }
#mveil { position:fixed; inset:0; background:rgba(0,0,0,.18); z-index:40; display:none; }
#mveil.open { display:block; }
input.filter { width:100%; background:var(--panel); color:var(--text); border:1px solid var(--line);
  border-radius:6px; padding:8px 12px; font-size:14px; margin-bottom:10px; }
"""

JS = """
function tab(id){
  document.querySelectorAll('nav.tabs button').forEach(b=>b.classList.toggle('on', b.dataset.t===id));
  document.querySelectorAll('section.tab').forEach(s=>s.classList.toggle('on', s.id===id));
}
function cp(t){
  navigator.clipboard.writeText(t).then(()=>{
    const o=document.getElementById('toast');
    o.textContent='Copied: '+t; o.style.display='block';
    setTimeout(()=>o.style.display='none',1800);
  });
}
function flt(q, tid){
  q=q.toLowerCase();
  document.querySelectorAll('#'+tid+' tr').forEach((tr,i)=>{
    if(i===0) return;
    tr.style.display = tr.textContent.toLowerCase().includes(q)?'':'none';
  });
}
function sum(o){
  if(!o) return '';
  const bits=[];
  if(o.model) bits.push('<code>model='+o.model+'</code>');
  if(o.hooks) bits.push('hooks: '+Object.entries(o.hooks).map(([k,v])=>'<code>'+k+'('+v+')</code>').join(' '));
  if(o.plugins) bits.push('plugins: '+o.plugins.map(p=>'<code>'+p+'</code>').join(', '));
  if(o.mcpServers) bits.push('mcp: '+o.mcpServers.map(m=>'<code>'+m+'</code>').join(', '));
  if(o.permissions) bits.push('permissions: '+Object.entries(o.permissions).map(([k,v])=>'<code>'+k+':'+v+'</code>').join(' '));
  return bits.join('<br>') || '<span class=dim>(empty)</span>';
}
function xray(){
  const cwd=document.getElementById('xsel').value;
  const x=window.SOC.xrays[cwd];
  const el=document.getElementById('xbody');
  if(!x){ el.innerHTML='<p class=dim>No data for this project.</p>'; return; }
  let h='';
  h+='<h2>① Settings layers (user → project)</h2>';
  x.layers.forEach(l=>{
    h+='<div class=node><div class=scope>'+l.scope+' <span class=dim>'+l.path+'</span></div>'
      +'<div class=detail>'+sum(l.summary)+'</div></div>';
  });
  if(!x.layers.length) h+='<p class=dim>(no settings files)</p>';
  h+='<h2>② CLAUDE.md chain <span class=dim style="font-weight:400;font-size:12px">'
    +'loaded root→cwd, ALL concatenated into every session here '
    +'(<a href="https://code.claude.com/docs/en/memory#how-claude-md-files-load" target="_blank" rel="noopener">official rule</a>)</span></h2>';
  let total=0;
  x.chain.forEach(c=>{ total+=c.kb;
    h+='<div class=chainbar><span class=seg>'+c.scope+'</span> '+c.path
      +' <span class=dim>'+c.kb+'KB</span></div>';
  });
  if(x.chain.length){
    h+='<p><b>'+x.chain.length+' file(s), '+total.toFixed(1)+'KB</b> injected at session start';
    const anc=x.chain.filter(c=>c.scope.startsWith('ancestor'));
    if(anc.length) h+=' — <span class=warn>'+anc.length+' from ANCESTOR folders (easy to forget!)</span>';
    h+='</p>';
  } else h+='<p class=dim>(no CLAUDE.md found)</p>';
  h+='<h2>③ Project-local harness</h2>';
  const lk=Object.keys(x.local_harness||{});
  if(lk.length){ lk.forEach(k=>{
    h+='<div class=node><div class=scope>.claude/'+k+'</div><div class=detail>'
      +x.local_harness[k].map(i=>'<span class=chip>'+i+'</span>').join(' ')+'</div></div>'; });
  } else h+='<p class=dim>(no project-local skills/agents/commands)</p>';
  h+='<h2>④ Other</h2><div class=node><div class=detail>'
    +'.mcp.json: '+(x.mcp_json?'<b>present</b>':'<span class=dim>none</span>')
    +' &nbsp;·&nbsp; auto-memory: '+(x.memory.exists?('<b>'+x.memory.files+' file(s)</b>'):'<span class=dim>none</span>')
    +'</div></div>';
  el.innerHTML=h;
}
function mview(mi,fi){
  const m=window.SOC.memories[mi], f=m.files[fi];
  document.getElementById('mtitle').textContent=f.name;
  document.getElementById('mmeta').textContent=
    (f.type? f.type+' · ':'')+m.project+' · '+f.path+' · '+f.kb+'KB';
  document.getElementById('mbody').textContent=f.content||'(empty)';
  document.getElementById('mpanel').classList.add('open');
  document.getElementById('mveil').classList.add('open');
}
function mclose(){
  document.getElementById('mpanel').classList.remove('open');
  document.getElementById('mveil').classList.remove('open');
}
function escj(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function renderObs(){
  const el=document.getElementById('obslist'); if(!el) return;
  const q=(document.getElementById('obsq').value||'').toLowerCase();
  const all=(window.SOC.injection&&window.SOC.injection.obs)||[];
  const hit=q? all.filter(o=>(o.t+' '+o.p).toLowerCase().includes(q)) : all.slice(0,150);
  let h='<table><tr><th style="width:60px">id</th><th style="width:90px">date</th><th style="width:140px">project</th><th>title</th></tr>';
  hit.slice(0,500).forEach(o=>{
    h+='<tr class="mrow" onclick="oview('+o.i+')"><td>'+o.i+'</td><td class="dim">'+escj(o.d)
      +'</td><td>'+escj(o.p)+'</td><td>'+escj(o.t)+'</td></tr>';
  });
  h+='</table><p class="dim">'+(q? hit.length+' match(es)' : 'showing latest 150 of '+all.length+' — type to filter all')+'</p>';
  el.innerHTML=h;
}
function oview(id){
  const all=(window.SOC.injection&&window.SOC.injection.obs)||[];
  const o=all.find(x=>x.i===id); if(!o) return;
  document.getElementById('mtitle').textContent='observation #'+id;
  document.getElementById('mmeta').textContent=(o.y? o.y+' · ':'')+o.p+' · '+o.d;
  document.getElementById('mbody').textContent=o.t
    +'\\n\\nFull record (facts, narrative, files touched):\\n  socrates mem '+id
    +'\\n\\n(run in a terminal — full texts of all '+all.length+' records are too large to embed)';
  document.getElementById('mpanel').classList.add('open');
  document.getElementById('mveil').classList.add('open');
}
function bview(i){
  const b=window.SOC.injection.blocks[i]; if(!b) return;
  document.getElementById('mtitle').textContent='Injected block';
  document.getElementById('mmeta').textContent=b.path+' · '+b.kb+'KB — this exact text enters every session via the CLAUDE.md chain';
  document.getElementById('mbody').textContent=b.content;
  document.getElementById('mpanel').classList.add('open');
  document.getElementById('mveil').classList.add('open');
}
window.addEventListener('keydown',e=>{ if(e.key==='Escape') mclose(); });
window.addEventListener('DOMContentLoaded',()=>{ if(document.getElementById('xsel')) xray(); renderObs(); });
"""


def render_html(data: dict) -> str:
    # Sessions tab rows
    srows = []
    for s in data["sessions"][:200]:
        name = s["alias"] or s["slug"] or (s["first_msg"][:60] if s["first_msg"] else s["uuid"][:8])
        star = "★ " if s["alias"] else ""
        cls = ' class="aliased"' if s["alias"] else ""
        when = datetime.fromtimestamp(s["mtime"]).strftime("%m-%d %H:%M")
        srows.append(
            f"<tr{cls}><td>{esc(star + name)}</td>"
            f"<td>{esc(Path(s['cwd']).name if s['cwd'] else '?')}</td>"
            f"<td>{esc(when)}</td>"
            f"<td class='msg'>{esc(s['first_msg'][:90])}</td>"
            f"<td><button class='cp' onclick=\"cp('--resume {esc(s['uuid'])}')\">--resume</button></td></tr>")

    # Projects tab rows
    prows = []
    ranked = sorted(data["by_project"].items(), key=lambda kv: kv[1][0]["mtime"], reverse=True)
    for cwd, sess in ranked:
        named = sum(1 for s in sess if s["alias"])
        last = datetime.fromtimestamp(sess[0]["mtime"]).strftime("%Y-%m-%d %H:%M")
        prows.append(f"<tr><td>{esc(Path(cwd).name if cwd != '(unknown)' else cwd)}</td>"
                     f"<td class='dim'>{esc(cwd.replace(str(HOME), '~'))}</td>"
                     f"<td>{len(sess)}</td><td>{'★ ' + str(named) if named else '-'}</td><td>{esc(last)}</td></tr>")

    # Harness tab
    hnodes = []
    for scope, kinds in data["inventory"].items():
        for kind, items in kinds.items():
            chips = " ".join(f"<span class='chip'>{esc(i)}</span>" for i in items)
            hnodes.append(f"<div class='node'><div class='scope'>{esc(scope)} · {esc(kind)} ({len(items)})</div>"
                          f"<div class='detail'>{chips}</div></div>")
    for e in data["global_settings"]:
        s = e["summary"]
        if s.get("plugins"):
            chips = " ".join(f"<span class='chip'>{esc(p)}</span>" for p in s["plugins"])
            hnodes.append(f"<div class='node'><div class='scope'>enabled plugins ({len(s['plugins'])})</div>"
                          f"<div class='detail'>{chips}</div></div>")
        if s.get("mcpServers"):
            chips = " ".join(f"<span class='chip'>{esc(m)}</span>" for m in s["mcpServers"])
            hnodes.append(f"<div class='node'><div class='scope'>global MCP servers ({len(s['mcpServers'])})</div>"
                          f"<div class='detail'>{chips}</div></div>")

    # Memory & Identity tab
    ident = data["identity"]
    ident_rows = "".join(
        f"<tr><td style='width:220px'><b>{esc(k)}</b></td><td>{esc(v)}</td></tr>"
        for k, v in ident.items())
    mem_nodes = []
    glb = CLAUDE_DIR / "CLAUDE.md"
    mem_nodes.append(
        "<div class='node'><div class='scope'>Instruction memory (global)</div><div class='detail'>"
        + (f"<code>~/.claude/CLAUDE.md</code> {file_kb(glb)}KB — loaded into EVERY session"
           if glb.is_file() else "<span class='dim'>no global CLAUDE.md</span>")
        + " &nbsp;·&nbsp; per-project chains: see the <b>Config X-ray</b> tab</div></div>")
    for mi, m in enumerate(data["memories"]):
        rows = "".join(
            f"<tr class='mrow' onclick=\"mview({mi},{fi})\"><td>{esc(f['name'])}</td><td>{esc(f['type'] or '-')}</td>"
            f"<td class='msg'>{esc(f['description'])}</td><td class='dim'>{f['kb']}KB</td></tr>"
            for fi, f in enumerate(m["files"]))
        mem_nodes.append(
            f"<div class='node'><div class='scope'>{esc(m['project'])} "
            f"<span class='dim'>{esc(m['cwd'])} · {len(m['files'])} memories · click a row to read</span></div>"
            f"<table><tr><th>name</th><th>type</th><th>description</th><th>size</th></tr>{rows}</table></div>")

    # Injected memory layers (why past conversations "pop up")
    inj = data["injection"]
    inj_nodes = []
    cm = inj["claude_mem"]
    counts = inj["db"]["counts"]
    if cm:
        kpi_inj = "".join(
            f"<div class='kpi'><b>{v}</b><span>{esc(t)}</span></div>" for v, t in (
                (f"{cm['mb']}MB", "store on disk (NOT tokens)"),
                (counts.get("observations", "?"), "observations"),
                (counts.get("session_summaries", "?"), "session summaries"),
                (counts.get("user_prompts", "?"), "saved prompts"),
            ))
        inj_nodes.append(f"<div class='kpis'>{kpi_inj}</div>")
        inj_nodes.append(
            "<div class='node'><div class='detail'><b>Disk ≠ tokens.</b> The store above never enters context as a whole. "
            "What costs tokens: (1) the injected blocks below ride the CLAUDE.md chain into <b>every</b> session, "
            "(2) recording itself runs background observer sessions after conversations, "
            "(3) searches of the store load only what is retrieved.</div></div>")
        comps = " ".join(f"<span class='chip'>{esc(c)}</span>" for c in cm["components"])
        inj_nodes.append(
            f"<div class='node'><div class='scope'>claude-mem plugin <span class='dim'>{esc(cm['path'])}</span></div>"
            f"<div class='detail'>Records every conversation in the background and <b>rewrites CLAUDE.md files</b> "
            f"with 'Recent Activity' blocks — which is why past conversations resurface in new sessions.<br>{comps}</div></div>")
    if inj["blocks"]:
        items = "".join(
            f"<div class='chainbar mrow' onclick='bview({i})'><span class='seg'>injected</span> "
            f"{esc(b['path'])} <span class='dim'>{b['kb']}KB · click to read</span></div>"
            for i, b in enumerate(inj["blocks"]))
        inj_nodes.append(
            f"<div class='node'><div class='scope'>Injected blocks — the exact text entering every session</div>"
            f"<div class='detail'>{items}</div></div>")
    if inj["session_hooks"]:
        cmds = "".join(f"<div class='chainbar'><code>{esc(c)}</code></div>" for c in inj["session_hooks"])
        inj_nodes.append(
            f"<div class='node'><div class='scope'>SessionStart hooks ({len(inj['session_hooks'])})</div>"
            f"<div class='detail'>These run at every session start and can inject additional context:<br>{cmds}</div></div>")
    if not inj_nodes:
        inj_nodes.append("<div class='node'><div class='detail dim'>no third-party memory layers detected</div></div>")

    # X-ray selector (most recently active first)
    xopts = []
    for cwd, _ in ranked:
        if cwd in data["xrays"]:
            xopts.append(f"<option value=\"{esc(cwd)}\">{esc(Path(cwd).name)} — {esc(cwd.replace(str(HOME), '~'))}</option>")

    # Overview KPIs
    n_alias = len(data["aliases"])
    gs = data["global_settings"][0]["summary"] if data["global_settings"] else {}
    kpis = [
        (len(data["by_project"]), "projects"),
        (len(data["sessions"]), "sessions"),
        (n_alias, "★ aliases"),
        (len(gs.get("plugins", [])), "plugins"),
        (len(gs.get("hooks", {})), "hook events"),
        (len(data["xrays"]), "projects x-rayed"),
    ]
    kpi_html = "".join(f"<div class='kpi'><b>{v}</b><span>{esc(t)}</span></div>" for v, t in kpis)

    soc_json = json.dumps({"xrays": data["xrays"], "memories": data["memories"],
                           "injection": {"blocks": data["injection"]["blocks"],
                                         "obs": data["injection"]["db"]["obs"]}},
                          ensure_ascii=False).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Socrates — Know Your Self</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1><span class="gold">Socrates</span> — Know Your Self</h1>
<div class="sub">γνῶθι σεαυτόν · generated {esc(data['generated_at'])}</div>

<nav class="tabs">
  <button class="on" data-t="t-over" onclick="tab('t-over')">Overview</button>
  <button data-t="t-proj" onclick="tab('t-proj')">Projects</button>
  <button data-t="t-sess" onclick="tab('t-sess')">Sessions</button>
  <button data-t="t-xray" onclick="tab('t-xray')">Config X-ray</button>
  <button data-t="t-mem" onclick="tab('t-mem')">Memory &amp; Identity</button>
  <button data-t="t-inj" onclick="tab('t-inj')">Injection</button>
  <button data-t="t-harn" onclick="tab('t-harn')">Harness</button>
</nav>

<section class="tab on" id="t-over">
  <div class="kpis">{kpi_html}</div>
  <div class="node"><div class="detail">
    Pick sessions in the terminal with <code>socrates list</code> / <code>find</code> / <code>projects</code>.
    This dashboard is a snapshot — rerun <code>socrates report</code> to refresh.
    The <b>Config X-ray</b> tab shows, per project, exactly which settings and CLAUDE.md files
    a new session would load (including ancestor-folder files that are easy to forget).
  </div></div>
</section>

<section class="tab" id="t-proj">
  <table><tr><th>Project</th><th>Path</th><th>Sessions</th><th>Aliased</th><th>Last activity</th></tr>
  {''.join(prows)}</table>
</section>

<section class="tab" id="t-sess">
  <input class="filter" placeholder="Search sessions (alias, project, message)…" oninput="flt(this.value,'sess')">
  <table id="sess"><tr><th>Name</th><th>Project</th><th>Last</th><th>First message</th><th>Resume</th></tr>
  {''.join(srows)}</table>
</section>

<section class="tab" id="t-xray">
  <p style="margin-bottom:10px"><select id="xsel" onchange="xray()">{''.join(xopts)}</select></p>
  <div id="xbody"></div>
</section>

<section class="tab" id="t-mem">
  <h2>① How Claude identifies you <span class="dim" style="font-weight:400;font-size:12px">(from the local ~/.claude.json — never leaves this machine)</span></h2>
  <table>{ident_rows or '<tr><td class="dim">no account info found</td></tr>'}</table>
  <h2>② Auto-memory <span class="dim" style="font-weight:400;font-size:12px">(project-scoped only — there is no global auto-memory directory)</span></h2>
  {''.join(mem_nodes)}
  <p class="dim">Third-party injected layers (claude-mem, hooks) → see the <b>Injection</b> tab.</p>
</section>

<section class="tab" id="t-inj">
  <h2>Injected memory layers <span class="dim" style="font-weight:400;font-size:12px">— why past conversations "pop up" in new sessions, and how to find the polluting entry</span></h2>
  {''.join(inj_nodes)}
  <h2>Stored observations <span class="dim" style="font-weight:400;font-size:12px">browse what claude-mem remembers · full record &amp; search in the terminal: <code>socrates mem &lt;text|id&gt;</code></span></h2>
  <input class="filter" id="obsq" placeholder="Filter {len(data['injection']['db']['obs'])} observations by title/project (e.g. a process name that keeps resurfacing)…" oninput="renderObs()">
  <div id="obslist"></div>
</section>

<section class="tab" id="t-harn">
  {''.join(hnodes) or '<p class="dim">no skills / agents / commands found</p>'}
</section>

<div id="toast"></div>
<div id="mveil" onclick="mclose()"></div>
<aside id="mpanel">
  <button class="x" onclick="mclose()">×</button>
  <h3 id="mtitle"></h3>
  <div class="meta" id="mmeta"></div>
  <pre id="mbody"></pre>
</aside>
<script>window.SOC = {soc_json};</script>
<script>{JS}</script>
</div></body></html>"""


# ── Entry point ──────────────────────────────────────────────


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--terminal"
    if mode == "--mem":
        return mem_search(sys.argv[2:])
    data = collect(Path.cwd())
    if mode == "--html":
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(render_html(data), encoding="utf-8")
        print(f"Report generated: {REPORT_PATH}")
        if "--no-open" not in sys.argv:
            subprocess.run(["open", str(REPORT_PATH)], check=False)
    else:
        render_terminal(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
