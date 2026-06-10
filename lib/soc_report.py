#!/usr/bin/env python3
"""Socrates — Claude Code 설정·하네스·세션 현황 분석기.

사용법:
    soc_report.py --terminal   터미널 ANSI 요약 (soc map)
    soc_report.py --html       HTML 대시보드 생성 후 브라우저로 열기 (soc report)

읽기 전용: ~/.claude/, ~/.claude.json, 경로 계층의 .claude/
쓰기는 ~/.claude/socrates/report.html 뿐.
표준 라이브러리만 사용한다.
"""

import html
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
REGISTRY = CLAUDE_DIR / "socrates" / "sessions.json"
REPORT_PATH = CLAUDE_DIR / "socrates" / "report.html"

# ── 데이터 수집 ──────────────────────────────────────────────


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def settings_summary(path: Path) -> dict:
    """settings(.local).json 하나를 요약."""
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


def settings_hierarchy(cwd: Path) -> list:
    """전역 → cwd까지 경로 계층의 .claude 설정 파일들을 수집."""
    entries = []
    for name in ("settings.json", "settings.local.json"):
        p = CLAUDE_DIR / name
        if p.is_file():
            entries.append({"scope": "전역 (~/.claude)", "path": p, "summary": settings_summary(p)})
    chain = [d for d in [*reversed(cwd.parents), cwd] if d not in (Path("/"), HOME.parent) and d != HOME]
    for d in chain:
        for name in ("settings.json", "settings.local.json"):
            p = d / ".claude" / name
            if p.is_file():
                entries.append({"scope": str(d).replace(str(HOME), "~"), "path": p, "summary": settings_summary(p)})
    return entries


def list_md_items(base: Path) -> list:
    """skills/agents/commands 폴더에서 항목 이름 수집."""
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
    """전역/프로젝트의 skills, agents, commands 인벤토리."""
    inv = {}
    for scope, root in (("전역", CLAUDE_DIR), ("프로젝트", cwd / ".claude")):
        for kind in ("skills", "agents", "commands"):
            items = list_md_items(root / kind)
            if items:
                inv.setdefault(scope, {})[kind] = items
    return inv


def first_fields(jsonl: Path, max_lines: int = 60) -> dict:
    """jsonl 앞부분에서 cwd/slug/첫 사용자 메시지를 추출 (읽기 전용)."""
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


def scan_sessions() -> list:
    """모든 프로젝트 폴더의 세션을 수집해 최근순 정렬."""
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
            })
    sessions.sort(key=lambda s: s["mtime"], reverse=True)
    return sessions


def project_meta() -> dict:
    """~/.claude.json 의 projects 메타데이터 (비용 등)."""
    data = load_json(HOME / ".claude.json") or {}
    return data.get("projects", {}) if isinstance(data.get("projects"), dict) else {}


def collect(cwd: Path) -> dict:
    sessions = scan_sessions()
    by_project = {}
    for s in sessions:
        key = s["cwd"] or "(unknown)"
        by_project.setdefault(key, []).append(s)
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "hierarchy": settings_hierarchy(cwd),
        "inventory": harness_inventory(cwd),
        "sessions": sessions,
        "by_project": by_project,
        "meta": project_meta(),
        "aliases": load_json(REGISTRY) or {},
    }


# ── 터미널 출력 (soc map) ────────────────────────────────────

GOLD, BLUE, GREEN, DIM, BOLD, RST = "\033[33m", "\033[34m", "\033[32m", "\033[2m", "\033[1m", "\033[0m"


def reltime(mtime: float) -> str:
    diff = int(datetime.now().timestamp() - mtime)
    if diff < 60:
        return f"{diff}초 전"
    if diff < 3600:
        return f"{diff // 60}분 전"
    if diff < 86400:
        return f"{diff // 3600}시간 전"
    return f"{diff // 86400}일 전"


def render_terminal(data: dict) -> None:
    print(f"\n{BOLD}{GOLD}Socrates{RST} — Know Your Self  {DIM}({data['generated_at']}){RST}\n")

    print(f"{BOLD}■ 설정 계층{RST}")
    for e in data["hierarchy"]:
        s = e["summary"]
        parts = []
        if "model" in s:
            parts.append(f"model={s['model']}")
        if "language" in s:
            parts.append(f"lang={s['language']}")
        if "hooks" in s:
            parts.append(f"hooks={len(s['hooks'])}종")
        if "plugins" in s:
            parts.append(f"plugins={len(s['plugins'])}")
        if "mcpServers" in s:
            parts.append(f"mcp={len(s['mcpServers'])}")
        if "permissions" in s:
            perm = ", ".join(f"{k}:{v}" for k, v in s["permissions"].items())
            parts.append(f"permissions({perm})")
        print(f"  {GREEN}{e['scope']}{RST} {DIM}{e['path'].name}{RST}")
        if parts:
            print(f"    └ {' · '.join(parts)}")
        if "hooks" in s:
            hooks = " ".join(f"{k}({v})" for k, v in s["hooks"].items())
            print(f"    └ hooks: {DIM}{hooks}{RST}")
        if "plugins" in s and s["plugins"]:
            print(f"    └ plugins: {DIM}{', '.join(s['plugins'])}{RST}")
        if "mcpServers" in s and s["mcpServers"]:
            print(f"    └ mcp: {DIM}{', '.join(s['mcpServers'])}{RST}")

    print(f"\n{BOLD}■ 하네스 인벤토리 (skills / agents / commands){RST}")
    if not data["inventory"]:
        print(f"  {DIM}(없음){RST}")
    for scope, kinds in data["inventory"].items():
        print(f"  {GREEN}{scope}{RST}")
        for kind, items in kinds.items():
            print(f"    └ {kind} ({len(items)}): {DIM}{', '.join(items)}{RST}")

    print(f"\n{BOLD}■ 프로젝트 × 세션 (최근 활동순 상위 12){RST}")
    ranked = sorted(data["by_project"].items(), key=lambda kv: kv[1][0]["mtime"], reverse=True)
    for cwd, sess in ranked[:12]:
        short = cwd.replace(str(HOME), "~")
        named = [s for s in sess if s["alias"]]
        tag = f" {GOLD}★{len(named)}{RST}" if named else ""
        print(f"  {BLUE}{Path(cwd).name:<24}{RST} 세션 {len(sess):>3}개  {DIM}{reltime(sess[0]['mtime'])}{RST}{tag}  {DIM}{short}{RST}")

    print(f"\n{BOLD}■ 별명 등록 세션 (★){RST}")
    aliases = data["aliases"]
    if not aliases:
        print(f"  {DIM}아직 없음 — Claude 세션에서 /soc <별명> 으로 등록{RST}")
    for uuid, v in sorted(aliases.items(), key=lambda kv: kv[1].get("named_at", ""), reverse=True):
        print(f"  {GOLD}★ {v.get('alias', '?'):<28}{RST} {DIM}--resume {uuid}{RST}")
        print(f"    └ {DIM}{v.get('cwd', '').replace(str(HOME), '~')}{RST}")

    total = len(data["sessions"])
    print(f"\n{DIM}총 {len(data['by_project'])}개 프로젝트, {total}개 세션 · 'soc list'로 선택, 'soc report'로 HTML 대시보드{RST}\n")


# ── HTML 출력 (soc report) ───────────────────────────────────


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def render_html(data: dict) -> str:
    rows = []
    for s in data["sessions"][:200]:
        name = s["alias"] or s["slug"] or (s["first_msg"][:60] if s["first_msg"] else s["uuid"][:8])
        star = "★ " if s["alias"] else ""
        cls = ' class="aliased"' if s["alias"] else ""
        when = datetime.fromtimestamp(s["mtime"]).strftime("%m-%d %H:%M")
        rows.append(
            f"<tr{cls}><td>{esc(star + name)}</td>"
            f"<td>{esc(Path(s['cwd']).name if s['cwd'] else '?')}</td>"
            f"<td>{esc(when)}</td>"
            f"<td class='msg'>{esc(s['first_msg'][:90])}</td>"
            f"<td><button onclick=\"cp('--resume {esc(s['uuid'])}', this)\">--resume 복사</button></td></tr>"
        )

    hier = []
    for e in data["hierarchy"]:
        s = e["summary"]
        detail = []
        for key in ("model", "language"):
            if key in s:
                detail.append(f"<code>{key}={esc(s[key])}</code>")
        if "hooks" in s:
            detail.append("hooks: " + " ".join(f"<code>{esc(k)}({v})</code>" for k, v in s["hooks"].items()))
        if "plugins" in s:
            detail.append("plugins: " + ", ".join(f"<code>{esc(p)}</code>" for p in s["plugins"]))
        if "mcpServers" in s:
            detail.append("mcp: " + ", ".join(f"<code>{esc(m)}</code>" for m in s["mcpServers"]))
        if "permissions" in s:
            detail.append("permissions: " + " ".join(f"<code>{esc(k)}:{v}</code>" for k, v in s["permissions"].items()))
        hier.append(f"<div class='node'><div class='scope'>{esc(e['scope'])} <span class='dim'>{esc(e['path'].name)}</span></div>"
                    f"<div class='detail'>{'<br>'.join(detail) or '<span class=dim>(요약 없음)</span>'}</div></div>")

    inv = []
    for scope, kinds in data["inventory"].items():
        for kind, items in kinds.items():
            chips = " ".join(f"<span class='chip'>{esc(i)}</span>" for i in items)
            inv.append(f"<div class='node'><div class='scope'>{esc(scope)} · {esc(kind)} ({len(items)})</div><div class='detail'>{chips}</div></div>")

    proj_rows = []
    ranked = sorted(data["by_project"].items(), key=lambda kv: kv[1][0]["mtime"], reverse=True)
    for cwd, sess in ranked:
        named = sum(1 for s in sess if s["alias"])
        last = datetime.fromtimestamp(sess[0]["mtime"]).strftime("%Y-%m-%d %H:%M")
        proj_rows.append(f"<tr><td>{esc(Path(cwd).name if cwd != '(unknown)' else cwd)}</td>"
                         f"<td class='dim'>{esc(cwd.replace(str(HOME), '~'))}</td>"
                         f"<td>{len(sess)}</td><td>{'★ ' + str(named) if named else '-'}</td><td>{esc(last)}</td></tr>")

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<title>Socrates — Know Your Self</title>
<style>
:root {{ --bg:#ffffff; --panel:#f7f8fa; --panel2:#eef1f5; --text:#1f2430; --dim:#6b7280;
        --line:#dde2ea; --gold:#a16207; --blue:#2563eb; }}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:var(--bg); color:var(--text); font-family:-apple-system,"Apple SD Gothic Neo",sans-serif;
       line-height:1.6; padding:36px 24px 80px; }}
.wrap {{ max-width:1100px; margin:0 auto; }}
h1 {{ font-size:28px; }} h1 .gold {{ color:var(--gold); }}
.sub {{ color:var(--dim); font-size:13px; margin-bottom:28px; }}
h2 {{ font-size:18px; margin:36px 0 12px; padding-bottom:6px; border-bottom:1px solid var(--line); }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ border:1px solid var(--line); padding:7px 10px; text-align:left; }}
th {{ background:var(--panel2); }} td {{ background:var(--panel); }}
tr.aliased td {{ background:#fdf6e3; }} tr.aliased td:first-child {{ color:var(--gold); font-weight:600; }}
td.msg {{ color:var(--dim); font-size:12px; }}
button {{ background:var(--panel2); color:var(--blue); border:1px solid var(--line); border-radius:5px;
         padding:3px 10px; font-size:12px; cursor:pointer; font-family:Menlo,monospace; }}
button:hover {{ border-color:var(--blue); }}
code {{ font-family:Menlo,monospace; font-size:12px; background:var(--panel2); border:1px solid var(--line);
       border-radius:4px; padding:1px 5px; color:#92400e; }}
.node {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px 16px; margin:8px 0; }}
.scope {{ color:var(--gold); font-weight:600; font-size:14px; margin-bottom:4px; }}
.detail {{ font-size:13px; color:var(--text); }}
.chip {{ display:inline-block; background:var(--panel2); border:1px solid var(--line); border-radius:10px;
        padding:1px 10px; margin:2px; font-size:12px; font-family:Menlo,monospace; color:var(--blue); }}
.dim {{ color:var(--dim); }}
#toast {{ position:fixed; bottom:24px; right:24px; background:var(--gold); color:#ffffff;
         padding:8px 16px; border-radius:8px; font-size:13px; display:none; }}
input#filter {{ width:100%; background:var(--panel); color:var(--text); border:1px solid var(--line);
               border-radius:6px; padding:8px 12px; font-size:14px; margin-bottom:10px; }}
</style></head><body><div class="wrap">
<h1><span class="gold">Socrates</span> — Know Your Self</h1>
<div class="sub">γνῶθι σεαυτόν · 생성: {esc(data['generated_at'])} · 프로젝트 {len(data['by_project'])}개 · 세션 {len(data['sessions'])}개</div>

<h2>① 세션 (최근 200개 · ★ = 별명 등록)</h2>
<input id="filter" placeholder="세션 검색 (별명, 프로젝트, 메시지)…" oninput="flt(this.value)">
<table id="sess"><tr><th>이름</th><th>프로젝트</th><th>최근</th><th>첫 메시지</th><th>재개</th></tr>
{''.join(rows)}</table>

<h2>② 설정 계층 (전역 → 프로젝트)</h2>
{''.join(hier)}

<h2>③ 하네스 인벤토리</h2>
{''.join(inv) or '<div class="node dim">skills / agents / commands 항목 없음</div>'}

<h2>④ 프로젝트 활동</h2>
<table><tr><th>프로젝트</th><th>경로</th><th>세션 수</th><th>별명</th><th>최근 활동</th></tr>
{''.join(proj_rows)}</table>

<div id="toast">클립보드에 복사됨</div>
<script>
function cp(t, btn) {{
  navigator.clipboard.writeText(t).then(() => {{
    const o = document.getElementById('toast');
    o.textContent = '복사됨: ' + t; o.style.display = 'block';
    setTimeout(() => o.style.display = 'none', 1800);
  }});
}}
function flt(q) {{
  q = q.toLowerCase();
  document.querySelectorAll('#sess tr').forEach((tr, i) => {{
    if (i === 0) return;
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
}}
</script>
</div></body></html>"""


# ── 진입점 ───────────────────────────────────────────────────


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--terminal"
    data = collect(Path.cwd())
    if mode == "--html":
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(render_html(data), encoding="utf-8")
        print(f"리포트 생성: {REPORT_PATH}")
        if "--no-open" not in sys.argv:
            subprocess.run(["open", str(REPORT_PATH)], check=False)
    else:
        render_terminal(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
