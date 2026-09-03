#!/usr/bin/env python
"""Local, live, browser-based chat UI for TreasuryAI.

A real-time alternative to main.py's terminal REPL, backed by the exact
same TreasurySession — the real specialist agents, the real tools/*.py
functions, the real AuditLogger. No new dependency: built entirely on
Python's standard library http.server, honoring implementation-plan.md's
"no database, no web framework, no message broker" decision — this is a
thin JSON API + one static page, not a framework.

    python scripts/web_ui.py --scenario base_case --port 8765

Then open http://127.0.0.1:8765 in a browser. Requires a real
ANTHROPIC_API_KEY in .env (see .env.example) for live model reasoning —
without one, starting a session returns the same configuration error
main.py shows, rendered in the chat window instead of the terminal.

This is a demo/presentation tool, not part of the audited application
surface — it has no automated tests, unlike everything under agents/,
tools/, models/, core/, and data/.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from threading import Lock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # allow `python scripts/web_ui.py` from anywhere

from rich.console import Console

import main as cli
from main import TreasurySession
from models.audit import ApprovalGate, AuditEntry, EventType

SESSIONS: dict[str, TreasurySession] = {}
SESSIONS_LOCK = Lock()


def _silent_console() -> Console:
    return Console(file=StringIO(), force_terminal=False)


def _new_session_id(request_scenario: str) -> str:
    session = TreasurySession(scenario=request_scenario)
    with SESSIONS_LOCK:
        SESSIONS[session.session_id] = session
    return session.session_id


def _run_command(session: TreasurySession, command: str, argument: str | None) -> dict:
    if command not in cli._COMMANDS:
        raise KeyError(command)

    before = len(session.audit_logger.read_session(session.session_id))
    response = cli._COMMANDS[command](session, _silent_console(), argument)
    if response is None:
        return {"ok": False, "error": "That command needs a question — try again with some text."}

    after = session.audit_logger.read_session(session.session_id)
    new_events = after[before:]

    return {
        "ok": True,
        "response": response.model_dump(mode="json"),
        "events": [e.model_dump(mode="json") for e in new_events],
    }


def _log_approval(session: TreasurySession, approved: bool) -> None:
    now = datetime.now(timezone.utc)
    session.audit_logger.log(
        AuditEntry(
            timestamp=now,
            session_id=session.session_id,
            agent_id="OPERATOR",
            event_type=EventType.APPROVAL_GATE,
            payload=ApprovalGate(recommendation_id=str(uuid.uuid4()), approved=approved, timestamp=now).model_dump(mode="json"),
        )
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "TreasuryAI-WebUI/1.0"

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - quiet the default access log
        pass

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/" or self.path == "/index.html":
            body = PAGE_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        parts = [p for p in self.path.split("/") if p]

        try:
            if parts == ["api", "session"]:
                body = self._read_json_body()
                scenario = body.get("scenario", "base_case")
                try:
                    session_id = _new_session_id(scenario)
                except RuntimeError as exc:
                    self._send_json(200, {"ok": False, "error": str(exc)})
                    return
                except FileNotFoundError as exc:
                    self._send_json(200, {"ok": False, "error": str(exc)})
                    return
                self._send_json(200, {"ok": True, "session_id": session_id, "scenario": scenario})
                return

            if len(parts) == 4 and parts[0] == "api" and parts[1] == "session" and parts[3] in ("message", "approve"):
                session_id = parts[2]
                with SESSIONS_LOCK:
                    session = SESSIONS.get(session_id)
                if session is None:
                    self._send_json(404, {"ok": False, "error": "Unknown session — start a new one."})
                    return

                body = self._read_json_body()

                if parts[3] == "message":
                    command = body.get("command", "")
                    argument = body.get("argument")
                    result = _run_command(session, command, argument)
                    self._send_json(200, result)
                    return

                if parts[3] == "approve":
                    _log_approval(session, bool(body.get("approved")))
                    self._send_json(200, {"ok": True})
                    return

            self.send_error(404)
        except KeyError as exc:
            self._send_json(400, {"ok": False, "error": f"Unknown command: {exc}"})
        except Exception as exc:  # last-resort guard so the demo never just hangs
            self._send_json(500, {"ok": False, "error": str(exc)})


PAGE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TreasuryAI — Live Session</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
  :root {
    --page:#FAF7EF; --surface:#FFFFFF; --surface-2:#F3EFE3; --ink:#14181F; --ink-2:#4B5566; --muted:#8A8F98;
    --hair:rgba(20,24,31,0.11); --gold:#B98A22; --gold-ink:#7A5D16;
    --good:#0ca30c; --warning:#b8790a; --critical:#d03b3b;
    --orion:#2a78d6; --tara:#d1622e; --atlas:#16966a; --fira:#c68600; --cora:#147000; --aria:#d1393a;
    color-scheme: light;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --page:#10161F; --surface:#171E2A; --surface-2:#1D2531; --ink:#F3F1EA; --ink-2:#B9C2D0; --muted:#7C879A;
      --hair:rgba(243,241,234,0.12); --gold:#E0BA5E; --gold-ink:#E0BA5E;
      --warning:#fab219; --critical:#e66767;
      --orion:#3987e5; --tara:#d95926; --atlas:#199e70; --fira:#c98500; --cora:#1c9c00; --aria:#e66767;
      color-scheme: dark;
    }
  }
  * { box-sizing:border-box; }
  html,body { height:100%; margin:0; }
  body { background:var(--page); color:var(--ink); font-family:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif; display:flex; flex-direction:column; }
  .mono { font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace; }

  header { padding:16px 24px; border-bottom:1px solid var(--hair); display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px; background:var(--surface); }
  header .brand { display:flex; align-items:baseline; gap:10px; }
  header .brand b { font-size:16px; }
  header .brand span { font-size:12px; color:var(--muted); font-family:"IBM Plex Mono",monospace; }
  header select, header button.cmdbtn {
    font-family:"IBM Plex Mono",monospace; font-size:12.5px; padding:6px 10px; border-radius:7px;
    border:1px solid var(--hair); background:var(--surface-2); color:var(--ink-2); cursor:pointer;
  }
  header button.cmdbtn:hover { color:var(--ink); border-color:var(--gold); }
  header button.cmdbtn:disabled { opacity:.4; cursor:not-allowed; }

  main { flex:1; overflow-y:auto; padding:24px; display:flex; flex-direction:column; gap:16px; max-width:820px; margin:0 auto; width:100%; }
  .empty { color:var(--muted); font-size:14px; margin-top:40px; text-align:center; line-height:1.6; }

  .turn { display:flex; flex-direction:column; gap:10px; }
  .user-msg { align-self:flex-end; background:var(--surface-2); border-radius:12px 12px 2px 12px; padding:10px 14px; font-size:14px; max-width:70%; }
  .agent-card { background:var(--surface); border:1px solid var(--hair); border-radius:10px; overflow:hidden; }
  .agent-head { display:flex; align-items:center; gap:8px; padding:10px 14px; border-bottom:1px solid var(--hair); }
  .agent-name { font-family:"IBM Plex Mono",monospace; font-weight:600; font-size:13px; }
  .status-pill { margin-left:auto; font-family:"IBM Plex Mono",monospace; font-size:10.5px; font-weight:600; padding:3px 9px; border-radius:20px; }
  .status-complete{background:color-mix(in srgb,var(--good) 16%,transparent);color:var(--good);}
  .status-pending_approval{background:color-mix(in srgb,var(--warning) 18%,transparent);color:var(--warning);}
  .status-error{background:color-mix(in srgb,var(--critical) 16%,transparent);color:var(--critical);}
  .agent-body { padding:12px 14px; }
  .agent-body p { margin:0 0 8px; font-size:13.5px; line-height:1.55; color:var(--ink-2); }
  details.calls summary { cursor:pointer; font-family:"IBM Plex Mono",monospace; font-size:11.5px; color:var(--muted); list-style:none; }
  details.calls summary::-webkit-details-marker{display:none;}
  details.calls summary::before{content:"▸ ";}
  details.calls[open] summary::before{content:"▾ ";}
  .call { font-family:"IBM Plex Mono",monospace; font-size:11.5px; padding:6px 0; border-top:1px solid var(--hair); overflow-x:auto; }
  .call:first-child{border-top:none;}
  .call .tool{font-weight:600;}
  .call .arrow{color:var(--muted);margin:0 4px;}

  .briefing { background:var(--surface-2); border-left:3px solid var(--orion); border-radius:8px; padding:12px 14px; }
  .briefing.aria{border-left-color:var(--aria);}
  .briefing .who{font-family:"IBM Plex Mono",monospace;font-size:11px;font-weight:600;color:var(--orion);margin-bottom:4px;}
  .briefing.aria .who{color:var(--aria);}
  .briefing p{margin:0;font-size:14px;line-height:1.55;}

  .approval { background:color-mix(in srgb,var(--warning) 10%,var(--surface)); border:1px solid color-mix(in srgb,var(--warning) 35%,transparent); border-radius:10px; padding:14px; }
  .approval .title{font-family:"IBM Plex Mono",monospace;font-size:11.5px;font-weight:600;color:var(--warning);margin-bottom:8px;}
  .approval .rec{margin-bottom:10px;font-size:13.5px;line-height:1.5;}
  .approval .rec b{display:block;margin-bottom:2px;}
  .approval .rec .impact{color:var(--muted);font-size:12.5px;}
  .approval .btns{display:flex;gap:8px;}
  .approval button{font-family:"IBM Plex Mono",monospace;font-size:12px;font-weight:600;padding:7px 14px;border-radius:7px;border:1px solid var(--hair);cursor:pointer;}
  .approval button.approve{background:var(--good);color:#fff;border-color:var(--good);}
  .approval button.reject{background:transparent;color:var(--ink-2);}
  .approval.done{opacity:.6;}
  .decided{font-family:"IBM Plex Mono",monospace;font-size:12px;font-weight:600;}
  .decided.yes{color:var(--good);} .decided.no{color:var(--critical);}

  .error-msg{color:var(--critical);font-size:13.5px;background:color-mix(in srgb,var(--critical) 10%,transparent);border-radius:8px;padding:10px 14px;}

  footer.composer { border-top:1px solid var(--hair); background:var(--surface); padding:14px 24px; }
  .composer-inner { max-width:820px; margin:0 auto; display:flex; gap:8px; }
  #question { flex:1; font-family:"IBM Plex Sans",sans-serif; font-size:14px; padding:10px 14px; border-radius:9px; border:1px solid var(--hair); background:var(--surface-2); color:var(--ink); }
  #question:focus { outline:2px solid var(--gold); outline-offset:1px; }
  #send { font-family:"IBM Plex Mono",monospace; font-weight:600; font-size:13px; padding:0 18px; border-radius:9px; border:none; background:var(--gold); color:#241a05; cursor:pointer; }
  #send:disabled { opacity:.5; cursor:not-allowed; }
</style>
</head>
<body data-palette="#2a78d6,#d1622e,#16966a,#c68600,#147000,#d1393a">
<header>
  <div class="brand"><b>TreasuryAI</b><span id="session-label">no session</span></div>
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
    <select id="scenario">
      <option value="base_case">base_case</option>
      <option value="liquidity_stress">liquidity_stress</option>
      <option value="fx_shock">fx_shock</option>
    </select>
    <button class="cmdbtn" id="new-session">New session</button>
    <button class="cmdbtn" data-cmd="brief" disabled>Brief</button>
    <button class="cmdbtn" data-cmd="stress-test" disabled>Stress test</button>
    <button class="cmdbtn" data-cmd="risk-review" disabled>Risk review</button>
    <button class="cmdbtn" data-cmd="alerts" disabled>Alerts</button>
  </div>
</header>

<main id="main">
  <div class="empty">Start a session to begin — ORION and the specialists respond live, with every real tool call shown.</div>
</main>

<footer class="composer">
  <div class="composer-inner">
    <input id="question" type="text" placeholder="Ask a treasury question…" disabled>
    <button id="send" disabled>Ask</button>
  </div>
</footer>

<script>
const AGENT_LABEL = { ORION:"ORION", ATLAS:"ATLAS", CORA:"CORA", TARA:"TARA", FIRA:"FIRA", ARIA:"ARIA" };
let sessionId = null;

const mainEl = document.getElementById("main");
const sessionLabel = document.getElementById("session-label");
const questionInput = document.getElementById("question");
const sendBtn = document.getElementById("send");
const cmdBtns = document.querySelectorAll("[data-cmd]");

function setActive(active) {
  questionInput.disabled = !active;
  sendBtn.disabled = !active;
  cmdBtns.forEach(b => b.disabled = !active);
}

function clearEmpty() {
  const empty = mainEl.querySelector(".empty");
  if (empty) empty.remove();
}

function fmtVal(v) {
  if (v == null) return "null";
  if (typeof v === "string" && /^-?\d+(\.\d+)?$/.test(v)) {
    const n = parseFloat(v);
    if (Math.abs(n) >= 1000) return "$" + n.toLocaleString("en-US", {maximumFractionDigits:0});
  }
  if (Array.isArray(v)) return `[${v.length}]`;
  if (typeof v === "object") return "{…}";
  return String(v);
}
function kv(obj) { return Object.entries(obj||{}).map(([k,v]) => `${k}=${fmtVal(v)}`).join(", "); }

function buildCallsHTML(events, agentId) {
  const calls = events.filter(e => e.agent_id === agentId && e.event_type === "TOOL_CALL");
  const results = events.filter(e => e.agent_id === agentId && e.event_type === "TOOL_RESULT");
  if (!calls.length) return "";
  const rows = calls.map(c => {
    const r = results.find(x => x.payload.call_id === c.payload.call_id);
    const out = r ? (r.payload.error ? `error: ${r.payload.error}` : fmtVal(r.payload.output)) : "…";
    return `<div class="call"><span class="tool">${c.payload.tool_name}</span>(${kv(c.payload.inputs)})<span class="arrow">&rarr;</span>${out}</div>`;
  }).join("");
  return `<details class="calls"><summary>tool calls (${calls.length})</summary>${rows}</details>`;
}

function agentCardHTML(agentId, resp, events) {
  const status = (resp.status || "COMPLETE").toLowerCase();
  return `<div class="agent-card">
    <div class="agent-head"><span class="agent-name" style="color:var(--${agentId.toLowerCase()})">${AGENT_LABEL[agentId]}</span>
      <span class="status-pill status-${status}">${resp.status.replace("_"," ")}</span></div>
    <div class="agent-body">
      <p>${resp.reasoning || ""}</p>
      ${buildCallsHTML(events, agentId)}
    </div>
  </div>`;
}

function approvalHTML(turnId, recs) {
  const list = recs.map(r => `<div class="rec"><b>${r.action}</b>${r.rationale}<div class="impact">Estimated impact: ${r.estimated_impact}</div></div>`).join("");
  return `<div class="approval" id="${turnId}">
    <div class="title">PENDING APPROVAL</div>
    ${list}
    <div class="btns">
      <button class="approve" onclick="decide('${turnId}', true)">Approve</button>
      <button class="reject" onclick="decide('${turnId}', false)">Reject</button>
    </div>
  </div>`;
}

async function decide(turnId, approved) {
  const el = document.getElementById(turnId);
  el.querySelectorAll("button").forEach(b => b.disabled = true);
  await fetch(`/api/session/${sessionId}/approve`, { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({approved}) });
  el.classList.add("done");
  const btns = el.querySelector(".btns");
  btns.outerHTML = `<div class="decided ${approved ? "yes" : "no"}">${approved ? "Approved" : "Rejected"} — logged, nothing executed.</div>`;
}

function renderTurn(userText, result) {
  clearEmpty();
  const turn = document.createElement("div");
  turn.className = "turn";
  let html = "";
  if (userText) html += `<div class="user-msg">${userText}</div>`;

  if (!result.ok) {
    html += `<div class="error-msg">${result.error}</div>`;
    turn.innerHTML = html;
    mainEl.appendChild(turn);
    mainEl.scrollTop = mainEl.scrollHeight;
    return;
  }

  const resp = result.response;
  const events = result.events;
  const specialistIds = resp.agents_invoked || (resp.agent_id !== "ORION" ? [resp.agent_id] : []);

  specialistIds.forEach(id => {
    // find that specialist's own AGENT_RESPONSE event for its reasoning/status
    const own = events.find(e => e.agent_id === id && e.event_type === "AGENT_RESPONSE");
    const specResp = own ? own.payload : resp;
    html += agentCardHTML(id, specResp, events);
  });

  if (resp.agent_id === "ORION") {
    html += `<div class="briefing"><div class="who">ORION — synthesised briefing</div><p>${resp.final_briefing}</p></div>`;
  } else if (resp.agent_id) {
    html += agentCardHTML(resp.agent_id, resp, events);
    html += `<div class="briefing aria"><div class="who">${resp.agent_id} — direct (ORION does not invoke ARIA)</div><p>${resp.reasoning}</p></div>`;
  }

  const turnId = "approval-" + Math.random().toString(36).slice(2);
  if (resp.status === "PENDING_APPROVAL" && resp.recommendations && resp.recommendations.length) {
    html += approvalHTML(turnId, resp.recommendations);
  }

  turn.innerHTML = html;
  mainEl.appendChild(turn);
  mainEl.scrollTop = mainEl.scrollHeight;
}

async function send(command, argument) {
  setActive(false);
  const res = await fetch(`/api/session/${sessionId}/message`, {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({command, argument})
  });
  const result = await res.json();
  renderTurn(argument && command === "ask" ? argument : null, result);
  setActive(true);
  questionInput.focus();
}

document.getElementById("new-session").addEventListener("click", async () => {
  const scenario = document.getElementById("scenario").value;
  mainEl.innerHTML = `<div class="empty">Starting session…</div>`;
  const res = await fetch("/api/session", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({scenario}) });
  const result = await res.json();
  if (!result.ok) {
    mainEl.innerHTML = `<div class="error-msg" style="margin:40px auto;max-width:480px;">${result.error}</div>`;
    sessionLabel.textContent = "no session";
    setActive(false);
    return;
  }
  sessionId = result.session_id;
  sessionLabel.textContent = `${result.scenario} · ${sessionId.slice(0,8)}`;
  mainEl.innerHTML = `<div class="empty">Session ready. Try a command above, or ask a question below.</div>`;
  setActive(true);
});

cmdBtns.forEach(btn => btn.addEventListener("click", () => send(btn.dataset.cmd, null)));
sendBtn.addEventListener("click", () => {
  const text = questionInput.value.trim();
  if (!text) return;
  questionInput.value = "";
  send("ask", text);
});
questionInput.addEventListener("keydown", e => { if (e.key === "Enter") sendBtn.click(); });
</script>
</body>
</html>
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scripts/web_ui.py", description="Local live chat UI for TreasuryAI.")
    parser.add_argument("--port", type=int, default=8765, help="Port to serve on (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open a browser tab")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"TreasuryAI live chat UI running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")


if __name__ == "__main__":
    main()
