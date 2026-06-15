#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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


def soc_version() -> str:
    p = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    d = load_json(p) or {}
    return d.get("version", "?")


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


def _md_lines(p: Path) -> int:
    try:
        return sum(1 for _ in p.open(encoding="utf-8", errors="replace"))
    except OSError:
        return 0


def _anat_ftype(p: Path) -> str:
    return {".md": "md", ".json": "json", ".sh": "sh"}.get(p.suffix.lower(), "text")


def _anat_read(p: Path, limit: int = 65536) -> str:
    """File content for the click-to-view panel (read-only, size-capped)."""
    try:
        t = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(t) > limit:
        return t[:limit] + f"\n… (truncated — {p.stat().st_size} bytes total)"
    return t


def _anat_file(p: Path) -> dict:
    """path/content/ftype for a file node (empty dict if absent)."""
    if not p.is_file():
        return {}
    return {"path": str(p).replace(str(HOME), "~"),
            "ftype": _anat_ftype(p), "content": _anat_read(p)}


def collect_anatomy(cwd: Path) -> list:
    """Annotated tree of the Claude Code setup, with measured metadata.

    A whitelist of known, user-configurable components (not Claude's internal
    runtime folders). Each known slot is reported present-or-empty; empty core
    slots become dotted 'you could add this' hints. role_key feeds i18n.
    File-backed nodes carry their content for the click-to-view panel.
    """
    scopes = []

    def scan(root: Path, scope_key: str, settings_name: str):
        items = []

        def node(name, kind, role_key, present, meta="", children=None, fp=None):
            # Only show what actually exists — no 'you could add this' slots.
            if not present:
                return
            extra = _anat_file(fp) if fp is not None else {}
            items.append({"name": name, "kind": kind, "role_key": role_key,
                          "meta": meta, **extra, "children": children or []})

        st = load_json(root / "settings.json") or load_json(root / settings_name) or {}

        # memory
        for fn, rk in (("CLAUDE.md", "a_claudemd"), ("CLAUDE.local.md", "a_claudelocal")):
            p = root / fn
            node(fn, "memory", rk, p.is_file(),
                 f"{file_kb(p)}KB · {_md_lines(p)} lines", fp=p)
        # settings
        for fn, rk in (("settings.json", "a_settings"), ("settings.local.json", "a_settingslocal")):
            p = root / fn
            meta = ""
            if p.is_file():
                s = settings_summary(p)
                bits = []
                if "model" in s: bits.append(f"model={s['model']}")
                if "permissions" in s: bits.append(f"{sum(s['permissions'].values())} perms")
                if "hooks" in s: bits.append(f"{len(s['hooks'])} hook events")
                if "plugins" in s: bits.append(f"{len(s['plugins'])} plugins")
                if "mcpServers" in s: bits.append(f"{len(s['mcpServers'])} MCP")
                meta = " · ".join(bits)
            node(fn, "settings", rk, p.is_file(), meta, fp=p)
        # .mcp.json (project-root level)
        mp = root.parent / ".mcp.json" if scope_key == "project" else None
        if mp is not None and mp.is_file():
            mj = load_json(mp) or {}
            n = len(mj.get("mcpServers", {})) if isinstance(mj.get("mcpServers"), dict) else 0
            node(".mcp.json", "mcp", "a_mcp", True, f"{n} server(s)", fp=mp)
        # component folders (shown only if the folder has items)
        for fn, kind, rk in (("agents", "agent", "a_agents"), ("skills", "skill", "a_skills"),
                             ("commands", "command", "a_commands"), ("rules", "rule", "a_rules"),
                             ("output-styles", "style", "a_styles")):
            d = root / fn
            children = []
            if d.is_dir():
                if fn == "skills":
                    for c in sorted(d.iterdir()):
                        sk = c / "SKILL.md"
                        if c.is_dir() and sk.is_file():
                            children.append({"name": c.name + "/", "meta": f"{_md_lines(sk)} lines",
                                             **_anat_file(sk)})
                else:
                    for c in sorted(d.glob("*.md")):
                        # CLAUDE.md/README in a component folder is documentation,
                        # not an agent/command/rule — don't count it as a child.
                        if c.stem.upper() in ("README", "CLAUDE"):
                            continue
                        children.append({"name": c.name, "meta": f"{_md_lines(c)} lines",
                                         **_anat_file(c)})
            node(fn + "/", kind, rk, bool(children), f"{len(children)} item(s)", children)
        # hooks — folder (hooks.json) OR inline in settings
        hooks_dir = root / "hooks"
        hk = st.get("hooks") if isinstance(st.get("hooks"), dict) else {}
        hj = hooks_dir / "hooks.json"
        if hj.is_file():
            node("hooks/", "hook", "a_hooks", True, "hooks.json", fp=hj)
        else:
            ev = list(hk.keys())
            node("hooks", "hook", "a_hooks", bool(ev),
                 ", ".join(ev[:4]) + (f" +{len(ev)-4}" if len(ev) > 4 else ""))
        # statusline (a script file, if present)
        sl_files = [f for f in (list(root.glob("statusline*.sh")) + list(root.glob("statusline*")))
                    if f.is_file()]
        if sl_files:
            node("statusline", "settings", "a_statusline", True, sl_files[0].name, fp=sl_files[0])
        elif "statusLine" in st:
            node("statusline", "settings", "a_statusline", True, "configured in settings.json")
        # plugins
        plugins = st.get("enabledPlugins") if isinstance(st.get("enabledPlugins"), dict) else {}
        active = [k for k, v in plugins.items() if v]
        node("plugins", "plugin", "a_plugins", bool(active),
             f"{len(active)} enabled: " + ", ".join(active[:3]) + (" …" if len(active) > 3 else ""))

        scopes.append({"scope": scope_key, "root": str(root).replace(str(HOME), "~"),
                       "exists": root.is_dir(), "items": items})

    scan(CLAUDE_DIR, "global", "settings.local.json")
    pc = cwd / ".claude"
    scan(pc, "project", "settings.local.json")
    return scopes


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
                # Structural ceiling, decided from measurement (93 days → 2.8k
                # records, ~2.3KB each → ~33MB/year): full bodies are embedded
                # newest-first within a byte budget; older records keep titles
                # only. Unlimited full-text stays in 'socrates mem' (SQLite FTS).
                budget = int(float(__import__("os").environ.get("SOC_EMBED_MB", "25")) * 1048576)
                spent = 0
                full_n = 0
                for r in cur.execute(
                        "SELECT id, COALESCE(title,''), COALESCE(project,''), "
                        "COALESCE(type,''), COALESCE(substr(created_at,1,10),''), "
                        "COALESCE(subtitle,''), COALESCE(narrative,''), COALESCE(facts,'') "
                        "FROM observations ORDER BY id DESC"):
                    rec = {"i": r[0], "t": r[1][:90], "p": r[2], "y": r[3], "d": r[4],
                           "st": r[5], "na": r[6], "fa": r[7]}
                    size = len(r[5]) + len(r[6]) + len(r[7])
                    if spent + size <= budget:
                        spent += size
                        full_n += 1
                    else:
                        rec["st"] = rec["na"] = rec["fa"] = ""
                        rec["L"] = 1   # light record: body not embedded
                    inj["db"]["obs"].append(rec)
                inj["db"]["full_n"] = full_n
                inj["db"]["budget_mb"] = round(budget / 1048576)
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
        print(mem_removal_guide().replace("<ID>", query))
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


def mem_removal_guide() -> str:
    """Lazy: the color constants are defined later in the module."""
    return f"""
{BOLD}How to remove this memory{RST} {DIM}(claude-mem has no delete tool — issue #659 closed as
not planned; its own troubleshooting docs prescribe direct SQL, which is safe here:
the FTS index is trigger-synced){RST}

  1. claude-mem stop        {DIM}# stop the worker first (the DB runs in WAL mode){RST}
  2. sqlite3 ~/.claude-mem/claude-mem.db \\
       "DELETE FROM observations WHERE id=<ID>;"
  3. sqlite3 ~/.claude-mem/claude-mem.db \\
       "INSERT INTO observations_fts(observations_fts) VALUES('rebuild');"
  4. claude-mem start

{DIM}Note: an orphan embedding stays in ~/.claude-mem/vector-db (harmless — retrieval
hydrates from SQLite). Prevent future capture: wrap text in <private>…</private>;
reduce injection volume via CLAUDE_MEM_CONTEXT_* in ~/.claude-mem/settings.json.
Sources: docs.claude-mem.ai/troubleshooting · github.com/thedotmack/claude-mem/issues/659{RST}"""



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


def _stage(msg: str, progress: bool) -> None:
    if progress:
        print(f"  {msg}", file=sys.stderr, flush=True)


def _bar(label: str, i: int, n: int, t0: float, state: dict) -> None:
    """\\r-updated progress bar, latency-triggered: appears only once the work
    has already taken >0.4s — adapts to slow disks/machines instead of
    guessing from counts (fast machines never see it)."""
    if not sys.stderr.isatty():
        return
    import time
    if not state.get("on"):
        if time.time() - t0 < 0.4:
            return
        state["on"] = True
    w = 24
    f = int(w * i / max(n, 1))
    end = "\n" if i >= n else ""
    print(f"\r  {label:<26} [{'█' * f}{'░' * (w - f)}] {i}/{n}", file=sys.stderr,
          end=end, flush=True)


def scan_sessions(progress: bool = False) -> list:
    aliases = load_json(REGISTRY) or {}
    sessions = []
    if not PROJECTS_DIR.is_dir():
        return sessions
    files = [j for d in PROJECTS_DIR.iterdir() if d.is_dir() for j in d.glob("*.jsonl")]
    scan_sessions.total_mb = round(sum(f.stat().st_size for f in files) / 1048576)
    _stage(f"scanning {len(files)} session transcripts…", progress)
    import time
    t0 = time.time()
    bar_state = {}
    done = 0
    for proj_dir in PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir():
            continue
        for jsonl in proj_dir.glob("*.jsonl"):
            done += 1
            if progress:
                _bar("scanning transcripts", done, len(files), t0, bar_state)
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


def collect(cwd: Path, progress: bool = False) -> dict:
    sessions = scan_sessions(progress)
    by_project = {}
    storage_of = {}
    for s in sessions:
        key = s["cwd"] or "(unknown)"
        by_project.setdefault(key, []).append(s)
        storage_of.setdefault(key, Path(s["storage"]))

    _stage(f"x-raying {len(by_project)} projects (settings + CLAUDE.md chains)…", progress)
    import time
    t0 = time.time()
    bar_state = {}
    xrays = {}
    for k, proj in enumerate(by_project):
        if progress:
            _bar("x-raying projects", k + 1, len(by_project), t0, bar_state)
        if proj == "(unknown)":
            continue
        p = Path(proj)
        if p.is_dir():
            xrays[proj] = project_xray(p, storage_of.get(proj))
    _stage("mapping the setup anatomy…", progress)
    anatomy = collect_anatomy(cwd)
    _stage("reading auto-memory and the claude-mem store…", progress)

    storage_to_cwd = {s["storage"]: s["cwd"] for s in sessions if s["cwd"]}
    return {
        "transcripts_mb": getattr(scan_sessions, "total_mb", 0),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "inventory": harness_inventory(cwd),
        "sessions": sessions,
        "by_project": by_project,
        "xrays": xrays,
        "anatomy": anatomy,
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
.lang { position:absolute; top:30px; right:28px; }
.lang button { background:var(--panel); border:1px solid var(--line); padding:4px 12px; font-size:12px;
  cursor:pointer; color:var(--dim); }
.lang button:first-child { border-radius:6px 0 0 6px; } .lang button:last-child { border-radius:0 6px 6px 0; }
.lang button.on { background:var(--gold); color:#fff; border-color:var(--gold); }
.wrap { position:relative; }
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
#mhtml { font-size:13px; line-height:1.65; word-break:break-word; }
#mhtml table { font-size:12px; } #mhtml h1,#mhtml h2,#mhtml h3 { font-size:14px; margin:12px 0 6px; border:none; }
#mhtml ul,#mhtml ol { margin:6px 0 6px 20px; }
#mhtml .fm { background:var(--panel2); border:1px solid var(--line); border-radius:6px; padding:8px 12px;
  font-family:Menlo,monospace; font-size:11px; color:var(--dim); white-space:pre-wrap; margin-bottom:10px; }
#mhtml pre.cb { background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:10px;
  font-family:Menlo,monospace; font-size:11.5px; white-space:pre-wrap; word-break:break-word; }
#mhtml .jk{color:#2563eb} #mhtml .js{color:#15803d} #mhtml .jb{color:#7c3aed}
#mhtml .jn{color:#b45309} #mhtml .cmt{color:var(--dim)}
.mtog { margin:0 0 10px; } .mtog button { background:var(--panel); border:1px solid var(--line);
  padding:3px 12px; font-size:12px; cursor:pointer; color:var(--dim); }
.mtog button:first-child { border-radius:6px 0 0 6px; } .mtog button:last-child { border-radius:0 6px 6px 0; }
.mtog button.on { background:var(--gold); color:#fff; border-color:var(--gold); }
#mpanel .x { position:absolute; top:14px; right:16px; background:none; border:none; font-size:20px;
  color:var(--dim); cursor:pointer; }
#mveil { position:fixed; inset:0; background:rgba(0,0,0,.18); z-index:40; display:none; }
#mveil.open { display:block; }
input.filter { width:100%; background:var(--panel); color:var(--text); border:1px solid var(--line);
  border-radius:6px; padding:8px 12px; font-size:14px; margin-bottom:10px; }
.anat-scope { margin:14px 0 8px; font-weight:600; font-size:14px; }
.anat-scope .dim { font-weight:400; }
.arow { display:flex; align-items:baseline; gap:8px; padding:3px 10px; border-radius:6px; font-size:13px; }
.arow:hover { background:var(--panel2); }
.arow .pfx { font-family:Menlo,monospace; color:#b6bdcb; white-space:pre; }
.arow .nm { font-family:Menlo,monospace; min-width:170px; }
.arow.root .nm { font-weight:600; color:var(--gold); }
.arow.child .nm { color:var(--dim); min-width:200px; }
.arow.mrow { cursor:pointer; }
.tag { font-size:11px; border-radius:10px; padding:1px 9px; white-space:nowrap; min-width:62px; text-align:center; }
.tag.memory{background:#fde2e1;color:#9b2c2c} .tag.settings{background:#dbeafe;color:#1d4ed8}
.tag.agent{background:#e5e7eb;color:#374151} .tag.skill{background:#ede9fe;color:#6d28d9}
.tag.command{background:#fee2e2;color:#b91c1c} .tag.hook{background:#fed7aa;color:#9a3412}
.tag.rule{background:#dcfce7;color:#15803d} .tag.style{background:#fef9c3;color:#854d0e}
.tag.plugin{background:#cffafe;color:#0e7490} .tag.mcp{background:#e0e7ff;color:#3730a3}
.arow .role { color:var(--dim); }
.arow .meta { margin-left:auto; font-family:Menlo,monospace; font-size:11px; color:var(--dim); white-space:nowrap; }
.arow.absent .meta { color:#b45309; }
/* terminal-style search strip — the one deliberately dark accent on the light page */
.term { display:flex; align-items:center; gap:10px; background:#1b2130; border:1px solid #2c3547;
  border-radius:8px; padding:10px 14px; margin:4px 0 12px; }
.term .pr { color:var(--gold); font-family:Menlo,monospace; font-size:13px; white-space:nowrap; }
.term input { flex:1; background:transparent; border:none; outline:none; color:#e6edf7;
  font-family:Menlo,monospace; font-size:14px; caret-color:var(--gold); }
.term input::placeholder { color:#7b87a0; }
.term:focus-within { border-color:var(--gold); box-shadow:0 0 0 3px rgba(161,98,7,.18); }
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


    # Memory & Identity tab
    ident = data["identity"]
    ident_rows = "".join(
        f"<tr><td style='width:220px'><b>{esc(k)}</b></td><td>{esc(v)}</td></tr>"
        for k, v in ident.items())
    mem_nodes = []
    glb = CLAUDE_DIR / "CLAUDE.md"
    mem_nodes.append(
        "<div class='node'><div class='scope' data-i18n='m_instr'>Instruction memory (global)</div><div class='detail'>"
        + (f"<code>~/.claude/CLAUDE.md</code> {file_kb(glb)}KB — <span data-i18n='m_instr_note'>loaded into EVERY session</span>"
           if glb.is_file() else "<span class='dim'>no global CLAUDE.md</span>")
        + " &nbsp;·&nbsp; <span data-i18n='m_instr_xref'>per-project chains: see the <b>Config X-ray</b> tab</span></div></div>")
    for mi, m in enumerate(data["memories"]):
        rows = "".join(
            f"<tr class='mrow' onclick=\"mview({mi},{fi})\"><td>{esc(f['name'])}</td><td>{esc(f['type'] or '-')}</td>"
            f"<td class='msg'>{esc(f['description'])}</td><td class='dim'>{f['kb']}KB</td></tr>"
            for fi, f in enumerate(m["files"]))
        mem_nodes.append(
            f"<div class='node'><div class='scope'>{esc(m['project'])} "
            f"<span class='dim'>{esc(m['cwd'])} · {len(m['files'])} <span data-i18n='m_count'>memories</span> · <span data-i18n='m_click'>click a row to read</span></span></div>"
            f"<table><tr><th data-i18n='h_mname'>name</th><th data-i18n='h_type'>type</th><th data-i18n='h_desc'>description</th><th data-i18n='h_size'>size</th></tr>{rows}</table></div>")

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
            "<div class='node'><div class='detail' data-i18n='i_disk'><b>Disk ≠ tokens.</b> The store above never enters context as a whole. "
            "What costs tokens: (1) the injected blocks below ride the CLAUDE.md chain into <b>every</b> session, "
            "(2) recording itself runs background observer sessions after conversations, "
            "(3) searches of the store load only what is retrieved.</div></div>")
        comps = " ".join(f"<span class='chip'>{esc(c)}</span>" for c in cm["components"])
        inj_nodes.append(
            f"<div class='node'><div class='scope'>claude-mem plugin <span class='dim'>{esc(cm['path'])}</span></div>"
            f"<div class='detail'><span data-i18n='i_cm'>Records every conversation in the background and <b>rewrites CLAUDE.md files</b> "
            f"with 'Recent Activity' blocks — which is why past conversations resurface in new sessions.</span><br>{comps}</div></div>")
    if inj["blocks"]:
        items = "".join(
            f"<div class='chainbar mrow' onclick='bview({i})'><span class='seg'>injected</span> "
            f"{esc(b['path'])} <span class='dim'>{b['kb']}KB · <span data-i18n='i_click'>click to read</span></span></div>"
            for i, b in enumerate(inj["blocks"]))
        inj_nodes.append(
            f"<div class='node'><div class='scope' data-i18n='i_blocks'>Injected blocks — the exact text entering every session</div>"
            f"<div class='detail'>{items}</div></div>")
    if inj["session_hooks"]:
        cmds = "".join(f"<div class='chainbar'><code>{esc(c)}</code></div>" for c in inj["session_hooks"])
        inj_nodes.append(
            f"<div class='node'><div class='scope'><span data-i18n='i_hooks'>SessionStart hooks</span> ({len(inj['session_hooks'])})</div>"
            f"<div class='detail'><span data-i18n='i_hooksn'>These run at every session start and can inject additional context:</span><br>{cmds}</div></div>")
    # Identification → official removal steps (guidance only; Socrates never deletes)
    inj_nodes.append(
        "<div class='node'><div class='scope' data-i18n='i_rm_t'>Removing a memory — identification → official steps</div>"
        "<div class='detail' data-i18n='i_rm'>claude-mem has no delete tool; see <code>socrates mem &lt;id&gt;</code> "
        "for the official removal steps.</div></div>")
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
        (len(data["by_project"]), "k_projects", "projects"),
        (len(data["sessions"]), "k_sessions", "sessions"),
        (n_alias, "k_aliases", "★ aliases"),
        (len(gs.get("plugins", [])), "k_plugins", "plugins"),
        (len(gs.get("hooks", {})), "k_hooks", "hook events"),
        (len(data["xrays"]), "k_xrayed", "projects x-rayed"),
    ]
    kpi_html = "".join(f"<div class='kpi'><b>{v}</b><span data-i18n='{k}'>{esc(t)}</span></div>"
                       for v, k, t in kpis)

    soc_json = json.dumps({"xrays": data["xrays"], "memories": data["memories"],
                           "anatomy": data["anatomy"],
                           "tmb": data["transcripts_mb"],
                           "injection": {"blocks": data["injection"]["blocks"],
                                         "obs": data["injection"]["db"]["obs"],
                                         "full_n": data["injection"]["db"].get("full_n", 0),
                                         "budget_mb": data["injection"]["db"].get("budget_mb", 0)}},
                          ensure_ascii=False).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Socrates — Know Your Self</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1><span class="gold">Socrates</span> — Know Your Self</h1>
<div class="sub">γνῶθι σεαυτόν · generated {esc(data['generated_at'])} · socrates v{esc(soc_version())}</div>
<div class="lang">
  <button data-l="en" onclick="setLang('en')">EN</button>
  <button data-l="ko" onclick="setLang('ko')">한국어</button>
</div>

<nav class="tabs">
  <button class="on" data-t="t-over" onclick="tab('t-over')" data-i18n="tab_over">Overview</button>
  <button data-t="t-anat" onclick="tab('t-anat')" data-i18n="tab_anat">Anatomy</button>
  <button data-t="t-proj" onclick="tab('t-proj')" data-i18n="tab_proj">Projects</button>
  <button data-t="t-sess" onclick="tab('t-sess')" data-i18n="tab_sess">Sessions</button>
  <button data-t="t-xray" onclick="tab('t-xray')" data-i18n="tab_xray">Config X-ray</button>
  <button data-t="t-mem" onclick="tab('t-mem')" data-i18n="tab_mem">Memory &amp; Identity</button>
  <button data-t="t-inj" onclick="tab('t-inj')" data-i18n="tab_inj">Injection</button>
</nav>

<section class="tab on" id="t-over">
  <div class="kpis">{kpi_html}</div>
  <div class="node"><div class="detail" data-i18n="over_intro">
    Pick sessions in the terminal with <code>socrates list</code> / <code>find</code> / <code>projects</code>.
    This dashboard is a snapshot — rerun <code>socrates report</code> to refresh.
  </div></div>
</section>

<section class="tab" id="t-anat">
  <p class="dim" data-i18n="anat_intro" style="margin-bottom:6px"></p>
  <div id="anatbody"></div>
</section>

<section class="tab" id="t-proj">
  <table><tr><th data-i18n="h_project">Project</th><th data-i18n="h_path">Path</th><th data-i18n="h_sessions">Sessions</th><th data-i18n="h_aliased">Aliased</th><th data-i18n="h_last">Last activity</th></tr>
  {''.join(prows)}</table>
</section>

<section class="tab" id="t-sess">
  <div class="term"><span class="pr">socrates list ❯</span><input data-i18n-ph="ph_sess" placeholder="Search sessions (alias, project, message)…" oninput="flt(this.value,'sess')"></div>
  <p class="dim" id="findhint" style="margin:-4px 0 12px;font-size:12px"></p>
  <table id="sess"><tr><th data-i18n="h_name">Name</th><th data-i18n="h_project">Project</th><th data-i18n="h_lastcol">Last</th><th data-i18n="h_first">First message</th><th data-i18n="h_resume">Resume</th></tr>
  {''.join(srows)}</table>
</section>

<section class="tab" id="t-xray">
  <p style="margin-bottom:10px"><select id="xsel" onchange="xray()">{''.join(xopts)}</select></p>
  <div id="xbody"></div>
</section>

<section class="tab" id="t-mem">
  <h2><span data-i18n="m_h1">① How Claude identifies you</span> <span class="dim" style="font-weight:400;font-size:12px" data-i18n="m_h1n">(from the local ~/.claude.json — never leaves this machine)</span></h2>
  <table>{ident_rows or '<tr><td class="dim">no account info found</td></tr>'}</table>
  <h2><span data-i18n="m_h2">② Auto-memory</span> <span class="dim" style="font-weight:400;font-size:12px" data-i18n="m_h2n">(project-scoped only — there is no global auto-memory directory)</span></h2>
  {''.join(mem_nodes)}
  <p class="dim" data-i18n="m_pointer">Third-party injected layers (claude-mem, hooks) → see the <b>Injection</b> tab.</p>
</section>

<section class="tab" id="t-inj">
  <h2><span data-i18n="i_h1">Injected memory layers</span> <span class="dim" style="font-weight:400;font-size:12px" data-i18n="i_h1n">— why past conversations "pop up" in new sessions, and how to find the polluting entry</span></h2>
  {''.join(inj_nodes)}
  <h2><span data-i18n="i_obs">Stored observations</span> <span class="dim" style="font-weight:400;font-size:12px" data-i18n="i_obsn">browse what claude-mem remembers · full record &amp; search in the terminal: <code>socrates mem &lt;text|id&gt;</code></span></h2>
  <div class="term"><span class="pr">socrates mem ❯</span><input id="obsq" placeholder="Filter {len(data['injection']['db']['obs'])} observations by title/project…" oninput="renderObs()"></div>
  <div id="obslist"></div>
</section>

<div id="toast"></div>
<div id="mveil" onclick="mclose()"></div>
<aside id="mpanel">
  <button class="x" onclick="mclose()">×</button>
  <h3 id="mtitle"></h3>
  <div class="meta" id="mmeta"></div>
  <div class="mtog">
    <button id="tg-md" class="on" onclick="mtog(true)" data-i18n="p_rendered">Rendered</button>
    <button id="tg-raw" onclick="mtog(false)" data-i18n="p_raw">Raw</button>
  </div>
  <div id="mhtml"></div>
  <pre id="mbody" style="display:none"></pre>
</aside>
<script>window.SOC = {soc_json};</script>
<script>{JS}</script>
<script>{JS_I18N}</script>
</div></body></html>"""


JS_I18N = r"""
const I18N = {
en:{
 tab_over:'Overview',tab_anat:'Anatomy',tab_proj:'Projects',tab_sess:'Sessions',tab_xray:'Config X-ray',
 tab_mem:'Memory & Identity',tab_inj:'Injection',
 anat_intro:'Your Claude Code setup, annotated. Each known component shows its role and live metrics; dotted rows are core slots you have not created yet.',
 anat_global:'Global',anat_project:'Project',anat_absent:'(not present)',
 a_claudemd:'Instructions loaded into context (project rules)',
 a_claudelocal:'Personal instruction overrides (gitignored)',
 a_settings:'Permissions, model, hooks, plugins, MCP',
 a_settingslocal:'Personal settings (gitignored)',
 a_mcp:'MCP servers — must sit at the project root',
 a_agents:'Subagents — isolated context',
 a_skills:'Model-invokable, loaded on demand',
 a_commands:'Slash commands (flat .md files)',
 a_rules:'Path-scoped, load on glob match',
 a_styles:'Custom response formats',
 a_hooks:'Deterministic — fire on events',
 a_statusline:'Custom bottom-bar display',
 a_plugins:'Bundled commands + agents + MCP',
 k_projects:'projects',k_sessions:'sessions',k_aliases:'★ aliases',k_plugins:'plugins',
 k_hooks:'hook events',k_xrayed:'projects x-rayed',
 over_intro:'Pick sessions in the terminal with <code>socrates list</code> / <code>find</code> / <code>projects</code>. This dashboard is a snapshot — rerun <code>socrates report</code> to refresh.',
 h_project:'Project',h_path:'Path',h_sessions:'Sessions',h_aliased:'Aliased',h_last:'Last activity',
 ph_sess:'Search sessions (alias, project, message)…',
 s_findhint:'This box filters the table (names &amp; first messages). Searching INSIDE conversations ({mb}MB of transcripts — beyond what a static page can embed) lives in the terminal: <code>socrates find &lt;text&gt;</code>',
 h_name:'Name',h_lastcol:'Last',h_first:'First message',h_resume:'Resume',
 m_h1:'① How Claude identifies you',m_h1n:'(from the local ~/.claude.json — never leaves this machine)',
 m_h2:'② Auto-memory',m_h2n:'(project-scoped only — there is no global auto-memory directory)',
 m_pointer:'Third-party injected layers (claude-mem, hooks) → see the <b>Injection</b> tab.',
 m_instr:'Instruction memory (global)',m_instr_note:'loaded into EVERY session',
 m_instr_xref:'per-project chains: see the <b>Config X-ray</b> tab',
 m_count:'memories',m_click:'click a row to read',
 h_mname:'name',h_type:'type',h_desc:'description',h_size:'size',
 i_h1:'Injected memory layers',
 i_h1n:'— why past conversations "pop up" in new sessions, and how to find the polluting entry',
 i_disk:'<b>Disk ≠ tokens.</b> The store above never enters context as a whole. What costs tokens: (1) the injected blocks below ride the CLAUDE.md chain into <b>every</b> session, (2) recording runs background observer sessions after conversations, (3) searches load only what is retrieved.',
 i_cm:'Records every conversation in the background and <b>rewrites CLAUDE.md files</b> with "Recent Activity" blocks — which is why past conversations resurface in new sessions.',
 i_blocks:'Injected blocks — the exact text entering every session',i_click:'click to read',
 i_hooks:'SessionStart hooks',i_hooksn:'These run at every session start and can inject additional context:',
 i_rm_t:'Removing a memory — identification → official steps',
 i_rm:'claude-mem has <b>no delete tool</b> (<a href="https://github.com/thedotmack/claude-mem/issues/659" target="_blank" rel="noopener">issue #659</a> closed as not planned); its <a href="https://docs.claude-mem.ai/troubleshooting" target="_blank" rel="noopener">own docs</a> prescribe direct SQL — safe, because the FTS index is trigger-synced.<pre>1. claude-mem stop\n2. sqlite3 ~/.claude-mem/claude-mem.db "DELETE FROM observations WHERE id=&lt;ID&gt;;"\n3. sqlite3 ~/.claude-mem/claude-mem.db "INSERT INTO observations_fts(observations_fts) VALUES(\'rebuild\');"\n4. claude-mem start</pre>Find the ID below or with <code>socrates mem &lt;text&gt;</code>; <code>socrates mem &lt;id&gt;</code> prints the record with these steps filled in. Prevent future capture with <code>&lt;private&gt;…&lt;/private&gt;</code> tags; reduce volume via <code>CLAUDE_MEM_CONTEXT_*</code> in ~/.claude-mem/settings.json.',
 i_obs:'Stored observations',
 i_obsn:'browse what claude-mem remembers · full record &amp; search in the terminal: <code>socrates mem &lt;text|id&gt;</code>',
 ph_obs:'Filter {n} observations by title/project (e.g. a process name that keeps resurfacing)…',
 i_showing_full:'idle view shows the latest 150 — typing searches title AND full text of all {n} records',
 i_showing_part:'idle view shows the latest 150 — typing searches titles of all {n} records, full text of the latest {fn} (embed budget {mb}MB) · older bodies: socrates mem',
 i_matches:'{n} match(es)',
 p_light:'(body not embedded — over the size budget; read it with: socrates mem {id})',
 h_id:'id',h_date:'date',h_title:'title',
 x_layers:'① Settings layers (user → project)',x_chain:'② CLAUDE.md chain',
 x_chainn:'loaded root→cwd, ALL concatenated into every session here (<a href="https://code.claude.com/docs/en/memory#how-claude-md-files-load" target="_blank" rel="noopener">official rule</a>)',
 x_injected:'<b>{n} file(s), {kb}KB</b> injected at session start',
 x_anc:'{n} from ANCESTOR folders (easy to forget!)',
 x_local:'③ Project-local harness',x_other:'④ Other',
 x_nochain:'(no CLAUDE.md found)',x_nosettings:'(no settings files)',
 x_nolocal:'(no project-local skills/agents/commands)',
 w_present:'present',w_none:'none',
 p_block:'this exact text enters every session via the CLAUDE.md chain',
 p_rendered:'Rendered',p_raw:'Raw',
 p_remhint:'Removal steps for this memory: run <code>socrates mem {id}</code> in a terminal (prints the official procedure with the id filled in).'
},
ko:{
 tab_over:'개요',tab_anat:'구조 해부',tab_proj:'프로젝트',tab_sess:'세션',tab_xray:'설정 X-ray',
 anat_intro:'내 Claude Code 셋업에 주석을 단 모습입니다. 알려진 구성요소마다 역할과 실측 지표를 보여 주며, 점선 행은 아직 만들지 않은 핵심 슬롯입니다.',
 anat_global:'전역',anat_project:'프로젝트',anat_absent:'(없음)',
 a_claudemd:'컨텍스트에 로드되는 지침 (프로젝트 규칙)',
 a_claudelocal:'개인 지침 오버라이드 (gitignore)',
 a_settings:'권한·모델·hooks·plugins·MCP',
 a_settingslocal:'개인 설정 (gitignore)',
 a_mcp:'MCP 서버 — 프로젝트 루트에 있어야 함',
 a_agents:'서브에이전트 — 격리된 컨텍스트',
 a_skills:'모델이 호출, 필요 시 로드',
 a_commands:'슬래시 커맨드 (평탄한 .md)',
 a_rules:'경로 스코프, glob 매치 시 로드',
 a_styles:'커스텀 응답 형식',
 a_hooks:'결정론적 — 이벤트마다 실행',
 a_statusline:'하단 바 커스텀 표시',
 a_plugins:'커맨드+에이전트+MCP 묶음',
 tab_mem:'메모리 · 신원',tab_inj:'주입 레이어',
 k_projects:'프로젝트',k_sessions:'세션',k_aliases:'★ 별명',k_plugins:'플러그인',
 k_hooks:'훅 이벤트',k_xrayed:'X-ray 대상',
 over_intro:'세션 선택은 터미널에서 <code>socrates list</code> / <code>find</code> / <code>projects</code>로 하세요. 이 대시보드는 스냅샷입니다 — <code>socrates report</code>를 다시 실행하면 갱신됩니다.',
 h_project:'프로젝트',h_path:'경로',h_sessions:'세션 수',h_aliased:'별명',h_last:'최근 활동',
 ph_sess:'세션 검색 (별명, 프로젝트, 메시지)…',
 s_findhint:'이 검색창은 표(이름·첫 메시지)를 거릅니다. 대화 내용 검색({mb}MB transcript — 정적 페이지 임베드 한계 초과)은 터미널에서: <code>socrates find &lt;검색어&gt;</code>',
 h_name:'이름',h_lastcol:'최근',h_first:'첫 메시지',h_resume:'재개',
 m_h1:'① Claude가 나를 인식하는 정보',m_h1n:'(로컬 ~/.claude.json — 이 기기를 떠나지 않습니다)',
 m_h2:'② 자동 메모리',m_h2n:'(프로젝트 단위만 존재 — 전역 자동 메모리 폴더는 없음)',
 m_pointer:'제3자 주입 레이어(claude-mem, 훅) → <b>주입 레이어</b> 탭을 보세요.',
 m_instr:'지침 메모리 (전역)',m_instr_note:'모든 세션에 로드됨',
 m_instr_xref:'프로젝트별 체인은 <b>설정 X-ray</b> 탭 참조',
 m_count:'개 메모리',m_click:'행을 클릭하면 내용을 읽을 수 있음',
 h_mname:'이름',h_type:'종류',h_desc:'설명',h_size:'크기',
 i_h1:'주입되는 메모리 레이어',
 i_h1n:'— 과거 대화가 새 세션에 "불쑥" 나타나는 이유와, 오염 항목을 찾는 방법',
 i_disk:'<b>디스크 ≠ 토큰.</b> 위 저장소가 통째로 컨텍스트에 들어가지는 않습니다. 토큰을 쓰는 것은: (1) 아래 주입 블록이 CLAUDE.md 체인을 타고 <b>모든</b> 세션에 들어가는 부분, (2) 대화 후 백그라운드 observer 세션이 기록하는 부분, (3) 검색 시 가져온 결과뿐입니다.',
 i_cm:'모든 대화를 백그라운드로 기록하고 <b>CLAUDE.md 파일에 "Recent Activity" 블록을 직접 써넣습니다</b> — 과거 대화가 새 세션에 다시 나타나는 이유입니다.',
 i_blocks:'주입 블록 — 매 세션에 실제로 들어가는 텍스트',i_click:'클릭해서 읽기',
 i_hooks:'SessionStart 훅',i_hooksn:'세션 시작 때마다 실행되어 추가 컨텍스트를 주입할 수 있습니다:',
 i_rm_t:'기억 제거 — 식별 → 공식 절차',
 i_rm:'claude-mem에는 <b>삭제 도구가 없습니다</b> (<a href="https://github.com/thedotmack/claude-mem/issues/659" target="_blank" rel="noopener">issue #659</a> — not planned로 종료). 공식 문서 <a href="https://docs.claude-mem.ai/troubleshooting" target="_blank" rel="noopener">자체가 직접 SQL을 안내</a>하며, FTS 인덱스가 트리거로 동기화되어 안전합니다.<pre>1. claude-mem stop\n2. sqlite3 ~/.claude-mem/claude-mem.db "DELETE FROM observations WHERE id=&lt;ID&gt;;"\n3. sqlite3 ~/.claude-mem/claude-mem.db "INSERT INTO observations_fts(observations_fts) VALUES(\'rebuild\');"\n4. claude-mem start</pre>ID는 아래 목록이나 <code>socrates mem &lt;검색어&gt;</code>로 찾고, <code>socrates mem &lt;id&gt;</code>는 위 절차를 ID까지 채워서 출력합니다. 예방: 민감한 내용은 <code>&lt;private&gt;…&lt;/private&gt;</code> 태그로 감싸면 기록 자체가 안 되고, 주입량은 ~/.claude-mem/settings.json의 <code>CLAUDE_MEM_CONTEXT_*</code>로 줄일 수 있습니다.',
 i_obs:'저장된 기억 (observations)',
 i_obsn:'claude-mem이 기억하는 내용 탐색 · 전문·검색은 터미널에서: <code>socrates mem &lt;검색어|id&gt;</code>',
 ph_obs:'{n}개 기억을 제목/프로젝트로 필터 (예: 계속 거론되는 공정 이름)…',
 i_showing_full:'기본 화면은 최신 150건 — 검색어를 입력하면 전체 {n}건의 제목과 본문에서 찾습니다',
 i_showing_part:'기본 화면은 최신 150건 — 제목은 전체 {n}건, 본문은 최신 {fn}건(임베드 예산 {mb}MB)에서 검색 · 이전 본문: socrates mem',
 i_matches:'{n}건 일치',
 p_light:'(본문은 용량 예산 밖이라 임베드 안 됨 — socrates mem {id} 로 읽으세요)',
 h_id:'id',h_date:'날짜',h_title:'제목',
 x_layers:'① 설정 레이어 (전역 → 프로젝트)',x_chain:'② CLAUDE.md 체인',
 x_chainn:'루트→프로젝트 순서로 전부 이어붙여 모든 세션에 로드됨 (<a href="https://code.claude.com/docs/en/memory#how-claude-md-files-load" target="_blank" rel="noopener">공식 규칙</a>)',
 x_injected:'<b>{n}개 파일, {kb}KB</b>가 세션 시작 시 주입됨',
 x_anc:'{n}개는 조상 폴더에서 옴 (잊기 쉬움!)',
 x_local:'③ 프로젝트 로컬 하네스',x_other:'④ 기타',
 x_nochain:'(CLAUDE.md 없음)',x_nosettings:'(설정 파일 없음)',
 x_nolocal:'(프로젝트 로컬 skills/agents/commands 없음)',
 w_present:'있음',w_none:'없음',
 p_block:'이 텍스트가 CLAUDE.md 체인을 타고 매 세션에 그대로 들어갑니다',
 p_rendered:'렌더링',p_raw:'원문',
 p_remhint:'이 기억의 제거 절차: 터미널에서 <code>socrates mem {id}</code> 실행 (id가 채워진 공식 절차를 출력합니다).'
}};
let LANG = localStorage.getItem('soclang') || 'en';
function t(k){ const d=I18N[LANG]||{}; return d[k]!==undefined? d[k] : (I18N.en[k]!==undefined? I18N.en[k] : k); }
function tf(k,v){ let s=t(k); Object.keys(v||{}).forEach(x=>{ s=s.split('{'+x+'}').join(v[x]); }); return s; }
function setLang(l){ LANG=l; try{localStorage.setItem('soclang',l);}catch(e){} applyLang(); }
function applyLang(){
  document.querySelectorAll('[data-i18n]').forEach(el=>{ el.innerHTML=t(el.dataset.i18n); });
  document.querySelectorAll('[data-i18n-ph]').forEach(el=>{ el.placeholder=t(el.dataset.i18nPh); });
  const oq=document.getElementById('obsq');
  if(oq) oq.placeholder=tf('ph_obs',{n:((window.SOC.injection||{}).obs||[]).length});
  const fh=document.getElementById('findhint');
  if(fh) fh.innerHTML=tf('s_findhint',{mb:window.SOC.tmb||'?'});
  renderAnatomy();
  document.querySelectorAll('.lang button').forEach(b=>b.classList.toggle('on', b.dataset.l===LANG));
  if(document.getElementById('xsel')) xray();
  renderObs();
}
/* i18n-aware overrides of the dynamic renderers */
function xray(){
  const cwd=document.getElementById('xsel').value;
  const x=window.SOC.xrays[cwd];
  const el=document.getElementById('xbody');
  if(!x){ el.innerHTML='<p class=dim>No data.</p>'; return; }
  let h='';
  h+='<h2>'+t('x_layers')+'</h2>';
  x.layers.forEach(l=>{
    h+='<div class=node><div class=scope>'+l.scope+' <span class=dim>'+l.path+'</span></div>'
      +'<div class=detail>'+sum(l.summary)+'</div></div>';
  });
  if(!x.layers.length) h+='<p class=dim>'+t('x_nosettings')+'</p>';
  h+='<h2>'+t('x_chain')+' <span class=dim style="font-weight:400;font-size:12px">'+t('x_chainn')+'</span></h2>';
  let total=0;
  x.chain.forEach(c=>{ total+=c.kb;
    h+='<div class=chainbar><span class=seg>'+c.scope+'</span> '+c.path
      +' <span class=dim>'+c.kb+'KB</span></div>';
  });
  if(x.chain.length){
    h+='<p>'+tf('x_injected',{n:x.chain.length,kb:total.toFixed(1)});
    const anc=x.chain.filter(c=>c.scope.startsWith('ancestor'));
    if(anc.length) h+=' — <span class=warn>'+tf('x_anc',{n:anc.length})+'</span>';
    h+='</p>';
  } else h+='<p class=dim>'+t('x_nochain')+'</p>';
  h+='<h2>'+t('x_local')+'</h2>';
  const lk=Object.keys(x.local_harness||{});
  if(lk.length){ lk.forEach(k=>{
    h+='<div class=node><div class=scope>.claude/'+k+'</div><div class=detail>'
      +x.local_harness[k].map(i=>'<span class=chip>'+i+'</span>').join(' ')+'</div></div>'; });
  } else h+='<p class=dim>'+t('x_nolocal')+'</p>';
  h+='<h2>'+t('x_other')+'</h2><div class=node><div class=detail>'
    +'.mcp.json: '+(x.mcp_json?'<b>'+t('w_present')+'</b>':'<span class=dim>'+t('w_none')+'</span>')
    +' &nbsp;·&nbsp; auto-memory: '+(x.memory.exists?('<b>'+x.memory.files+'</b>'):'<span class=dim>'+t('w_none')+'</span>')
    +'</div></div>';
  el.innerHTML=h;
}
function renderObs(){
  const el=document.getElementById('obslist'); if(!el) return;
  const q=(document.getElementById('obsq').value||'').toLowerCase();
  const inj=window.SOC.injection||{}; const all=inj.obs||[];
  // lazy lowercase index over title+project+BODY (body where embedded)
  const hit=q? all.filter(o=>{
    if(o._s===undefined) o._s=(o.t+' '+o.p+' '+(o.st||'')+' '+(o.na||'')+' '+(o.fa||'')).toLowerCase();
    return o._s.includes(q);
  }) : all.slice(0,150);
  let h='<table><tr><th style="width:60px">'+t('h_id')+'</th><th style="width:90px">'+t('h_date')
    +'</th><th style="width:140px">'+t('h_project')+'</th><th>'+t('h_title')+'</th></tr>';
  hit.slice(0,500).forEach(o=>{
    h+='<tr class="mrow" onclick="oview('+o.i+')"><td>'+o.i+'</td><td class="dim">'+escj(o.d)
      +'</td><td>'+escj(o.p)+'</td><td>'+escj(o.t)+'</td></tr>';
  });
  const full=(inj.full_n||0)>=all.length;
  const idle=full? tf('i_showing_full',{n:all.length})
                 : tf('i_showing_part',{n:all.length,fn:inj.full_n,mb:inj.budget_mb});
  h+='</table><p class="dim">'+(q? tf('i_matches',{n:hit.length}) : idle)+'</p>';
  el.innerHTML=h;
}
/* ── minimal self-contained markdown renderer (tables, headers, code, lists, links) ── */
function mdEsc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function mdInline(s){
  return s
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>')
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
}
function mdRender(src){
  const stash=[];
  let s=mdEsc(src);
  s=s.replace(/^---\n([\s\S]*?)\n---\n?/, (m,fm)=>{
    stash.push('<div class="fm">'+fm+'</div>'); return '@@S'+(stash.length-1)+'@@\n'; });
  s=s.replace(/```[a-z]*\n?([\s\S]*?)```/g,(m,c)=>{
    stash.push('<pre class="cb">'+c+'</pre>'); return '@@S'+(stash.length-1)+'@@'; });
  const lines=s.split('\n'); const out=[]; let i=0;
  const isSep=l=>/^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(l)&&l.indexOf('-')>=0;
  while(i<lines.length){
    const ln=lines[i]; let m;
    if((m=ln.match(/^@@S(\d+)@@$/))){ out.push(stash[+m[1]]); i++; continue; }
    if(ln.indexOf('|')>=0 && i+1<lines.length && isSep(lines[i+1])){
      const cells=r=>r.replace(/^\s*\|/,'').replace(/\|\s*$/,'').split('|').map(c=>mdInline(c.trim()));
      let h='<table><tr>'+cells(ln).map(c=>'<th>'+c+'</th>').join('')+'</tr>'; i+=2;
      while(i<lines.length && lines[i].indexOf('|')>=0){
        h+='<tr>'+cells(lines[i]).map(c=>'<td>'+c+'</td>').join('')+'</tr>'; i++;
      }
      out.push(h+'</table>'); continue;
    }
    if((m=ln.match(/^(#{1,6})\s+(.*)$/))){
      const lv=Math.min(m[1].length,3);
      out.push('<h'+lv+'>'+mdInline(m[2])+'</h'+lv+'>');
    }
    else if((m=ln.match(/^\s*(?:[-*]|\d+\.)\s+(.*)$/))) out.push('<li>'+mdInline(m[1])+'</li>');
    else if(ln.trim()==='') out.push('');
    else out.push('<p>'+mdInline(ln)+'</p>');
    i++;
  }
  const final=[]; let inList=false;
  out.forEach(x=>{
    const li=x.startsWith('<li>');
    if(li&&!inList){ final.push('<ul>'); inList=true; }
    if(!li&&inList){ final.push('</ul>'); inList=false; }
    final.push(x);
  });
  if(inList) final.push('</ul>');
  return final.join('\n').replace(/@@S(\d+)@@/g,(m,n)=>stash[+n]);
}
function mpanelShow(title, meta, raw, rendered){
  document.getElementById('mtitle').textContent=title;
  document.getElementById('mmeta').textContent=meta;
  document.getElementById('mbody').textContent=raw;
  document.getElementById('mhtml').innerHTML=rendered;
  mtog(true);
  document.getElementById('mpanel').classList.add('open');
  document.getElementById('mveil').classList.add('open');
}
function mtog(md){
  document.getElementById('mhtml').style.display=md?'block':'none';
  document.getElementById('mbody').style.display=md?'none':'block';
  document.getElementById('tg-md').classList.toggle('on',md);
  document.getElementById('tg-raw').classList.toggle('on',!md);
}
function mview(mi,fi){
  const m=window.SOC.memories[mi], f=m.files[fi];
  mpanelShow(f.name,(f.type? f.type+' · ':'')+m.project+' · '+f.path+' · '+f.kb+'KB',
    f.content||'(empty)', mdRender(f.content||''));
}
function oview(id){
  const all=(window.SOC.injection&&window.SOC.injection.obs)||[];
  const o=all.find(x=>x.i===id); if(!o) return;
  let facts=o.fa||''; let factsHtml='';
  try{ const fl=JSON.parse(facts);
    if(Array.isArray(fl)) factsHtml='<ul>'+fl.map(x=>'<li>'+mdInline(mdEsc(String(x)))+'</li>').join('')+'</ul>';
  }catch(e){}
  if(!factsHtml && facts) factsHtml=mdRender(facts);
  const rendered='<p><b>'+mdEsc(o.t)+'</b></p>'
    +(o.st? '<p class="dim">'+mdEsc(o.st)+'</p>':'')
    +(factsHtml? '<h3>facts</h3>'+factsHtml:'')
    +(o.na? '<h3>narrative</h3>'+mdRender(o.na):'')
    +(o.L? '<p class="warn">'+tf('p_light',{id:id})+'</p>':'')
    +'<p class="dim" style="margin-top:14px">'+tf('p_remhint',{id:id})+'</p>';
  const raw=o.t+'\n'+(o.st?o.st+'\n':'')+'\n'+(facts?'facts:\n'+facts+'\n\n':'')+(o.na?'narrative:\n'+o.na:'');
  mpanelShow('observation #'+id,(o.y? o.y+' · ':'')+o.p+' · '+o.d, raw, rendered);
}
function bview(i){
  const b=window.SOC.injection.blocks[i]; if(!b) return;
  mpanelShow('Injected block', b.path+' · '+b.kb+'KB — '+t('p_block'), b.content, mdRender(b.content));
}
function renderAnatomy(){
  const el=document.getElementById('anatbody'); if(!el) return;
  const scopes=window.SOC.anatomy||[]; let h='';
  scopes.forEach((sc,si)=>{
    const label = sc.scope==='global'? t('anat_global') : t('anat_project');
    h+='<div class="anat-scope">'+label+' <span class="dim">'+escj(sc.root)+'</span></div>';
    if(!sc.exists && sc.scope==='project'){
      h+='<div class="arow absent"><span class="pfx">└─ </span><span class="role dim">'+t('anat_absent')+' — .claude/</span></div>';
      return;
    }
    const root = sc.scope==='global'? '~/.claude/' : '.claude/';
    h+='<div class="arow root"><span class="nm">'+root+'</span></div>';
    const items=sc.items;
    items.forEach((it,i)=>{
      const last = i===items.length-1;
      const clk = it.content!==undefined ? ' mrow" onclick="aview('+si+','+i+',-1)"' : '"';
      h+='<div class="arow'+clk+'><span class="pfx">'+(last?'└─ ':'├─ ')+'</span>'
        +'<span class="tag '+it.kind+'">'+it.kind+'</span>'
        +'<span class="nm">'+escj(it.name)+'</span>'
        +'<span class="role">'+t(it.role_key)+'</span>'
        +'<span class="meta">'+escj(it.meta)+'</span></div>';
      const kids=it.children||[];
      kids.forEach((c,j)=>{
        const pipe = last? '   ' : '│  ';
        const cclk = c.content!==undefined ? ' mrow" onclick="aview('+si+','+i+','+j+')"' : '"';
        h+='<div class="arow child'+cclk+'><span class="pfx">'+pipe+(j===kids.length-1?'└─ ':'├─ ')+'</span>'
          +'<span class="nm">'+escj(c.name)+'</span>'
          +'<span class="meta">'+escj(c.meta||'')+'</span></div>';
      });
    });
  });
  el.innerHTML=h;
}
function jsonHL(src){
  return mdEsc(src).replace(
    /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g,
    (m,s,colon,kw,num)=>{
      if(s!==undefined) return colon? '<span class="jk">'+s+'</span>'+colon : '<span class="js">'+s+'</span>';
      if(kw!==undefined) return '<span class="jb">'+kw+'</span>';
      if(num!==undefined) return '<span class="jn">'+num+'</span>';
      return m;
    });
}
function shHL(src){
  return mdEsc(src).split('\n').map(l=>
    /^\s*#/.test(l)? '<span class="cmt">'+l+'</span>' : l).join('\n');
}
function aview(si,ii,ci){
  const sc=(window.SOC.anatomy||[])[si]; if(!sc) return;
  const node = ci<0 ? sc.items[ii] : sc.items[ii].children[ci];
  if(!node || node.content===undefined) return;
  let rendered;
  if(node.ftype==='md') rendered=mdRender(node.content);
  else if(node.ftype==='json') rendered='<pre class="cb">'+jsonHL(node.content)+'</pre>';
  else rendered='<pre class="cb">'+shHL(node.content)+'</pre>';
  mpanelShow(node.name, node.path||'', node.content, rendered);
}
window.addEventListener('DOMContentLoaded', applyLang);
/* deep-link tabs: report.html#t-xray opens that tab (also handy for screenshots) */
window.addEventListener('DOMContentLoaded', ()=>{
  const h=location.hash.slice(1);
  if(h && document.getElementById(h)) tab(h);
});
"""


# ── Entry point ──────────────────────────────────────────────


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--terminal"
    if mode == "--mem":
        return mem_search(sys.argv[2:])
    t0 = datetime.now()
    data = collect(Path.cwd(), progress=(mode == "--html"))
    if mode == "--html":
        _stage("rendering the dashboard…", True)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(render_html(data), encoding="utf-8")
        secs = (datetime.now() - t0).total_seconds()
        print(f"Report generated in {secs:.1f}s: {REPORT_PATH}")
        if "--no-open" not in sys.argv:
            subprocess.run(["open", str(REPORT_PATH)], check=False)
    else:
        render_terminal(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
