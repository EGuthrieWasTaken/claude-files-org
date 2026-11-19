"""One scenario in a fresh interpreter: the real claude-files app with EXTRA_TOOL_MODULES=claude_files_org.

Tool registration happens at import time, so every scenario needs its own process.
Run by tests/integration/test_app.py; prints one JSON object per check: {"name", "ok", "detail"}.
    python child.py <app|bad_tz|bad_files> <data dir>
"""
import concurrent.futures
import hashlib
import json
import os
import sys
import threading
from pathlib import Path

TOKEN = "rw-token-" + "a" * 24
RO_TOKEN = "ro-token-" + "b" * 24
F = "org-projects/inbox.org"
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append({"name": name, "ok": bool(ok), "detail": "" if ok else str(detail)[:600]})


class Rpc:
    def __init__(self, client):
        self.client, self._id = client, 0

    def raw(self, token, method, params=None):
        self._id += 1
        r = self.client.post("/mcp", headers={"Accept": "application/json, text/event-stream",
                                               "Content-Type": "application/json",
                                               "Authorization": f"Bearer {token}"},
                             json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        return r.json()

    def tools(self, token):
        return {t["name"]: t for t in self.raw(token, "tools/list")["result"]["tools"]}

    def call(self, token, name, args=None):
        res = self.raw(token, "tools/call", {"name": name, "arguments": args or {}})
        if "error" in res:
            return False, res["error"].get("message", "")
        result = res["result"]
        text = "".join(c.get("text", "") for c in result.get("content", []))
        if result.get("isError"):
            return False, text
        try:
            return True, json.loads(text)
        except json.JSONDecodeError:
            return True, text


def env(data, **extra):
    os.environ.update(API_TOKEN=TOKEN, API_TOKEN_READONLY=RO_TOKEN, REQUIRE_MOUNT="false", DATA_ROOT=str(data),
                      LOG_LEVEL="WARNING", RATE_LIMIT_PER_MINUTE="100000", EXTRA_TOOL_MODULES="claude_files_org",
                      TZ="UTC", **extra)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scenario_app(data):
    env(data)
    from fastapi.testclient import TestClient
    from app import main as appmain
    import claude_files_org as org

    org_file = data / F
    with TestClient(appmain.app) as client:
        rpc = Rpc(client)
        tools = rpc.tools(TOKEN)
        expected = {"org_list_items", "org_get_item", "org_lint", "org_set_state", "org_reschedule",
                    "org_set_deadline", "org_add_item", "org_add_note", "org_set_tags", "org_set_effort",
                    "org_batch", "org_archive", "org_archive_closed"}
        check("tools are listed beside the core tools", expected <= set(tools) and "read_file" in tools, sorted(tools))
        check("tools/list has exactly the documented org tools", {n for n in tools if n.startswith("org_")} == expected,
              sorted(n for n in tools if n.startswith("org_")))
        check("a read-only token sees the same list", set(rpc.tools(RO_TOKEN)) == set(tools))
        reads = {"org_list_items", "org_get_item", "org_lint"}
        check("read hints are right", all(tools[n]["annotations"]["readOnlyHint"] == (n in reads) for n in expected))
        check("no tool schema exposes ctx", all("ctx" not in t["inputSchema"].get("properties", {}) for n, t in tools.items() if n in expected))
        params = {n: set(tools[n]["inputSchema"].get("properties", {})) for n in expected}
        check("documented parameters are present",
              {"file", "state", "tags", "overdue", "text", "limit"} <= params["org_list_items"]
              and {"id", "rev", "state", "note", "dry_run"} <= params["org_set_state"]
              and {"edits", "dry_run"} <= params["org_batch"] and {"older_than_days"} <= params["org_archive_closed"]
              and {"title", "parent_id", "parent_rev", "tags", "body"} <= params["org_add_item"],
              params)
        init = rpc.raw(TOKEN, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                              "clientInfo": {"name": "org-tests", "version": "0"}})
        instr = init["result"].get("instructions", "")
        check("instructions carry the org paragraph after the base text",
              "org_*" in instr and instr.index(org.INSTRUCTIONS.split("\n")[0][:40]) > 100, instr[-300:])
        ok, info = rpc.call(RO_TOKEN, "get_folder_info")
        mods = info["extensions"]["modules"] if ok else []
        check("get_folder_info lists the module and its tools",
              ok and mods and mods[0]["module"] == "claude_files_org" and expected <= set(mods[0]["tools"]), mods)

        # -- reads -------------------------------------------------------------
        ok, listing = rpc.call(RO_TOKEN, "org_list_items", {})
        check("reads work with a read-only token", ok and listing["total"] >= 3, listing)
        alpha = next(i for i in listing["items"] if i["title"] == "alpha")
        beta = next(i for i in listing["items"] if i["title"] == "beta")
        b2 = next(i for i in listing["items"] if i["title"] == "b2")
        ok, lint = rpc.call(RO_TOKEN, "org_lint", {})
        check("org_lint works with a read-only token", ok and lint["problems"] == [], lint)
        ok, item = rpc.call(RO_TOKEN, "org_get_item", {"id": alpha["id"]})
        check("org_get_item returns the logbook", ok and item["logbook"][0]["kind"] == "rescheduled", item)
        ok, res = rpc.call(RO_TOKEN, "org_list_items", {"file": "config.org"})
        check("a file outside the set is refused, naming the allowed ones",
              not ok and "file_not_allowed" in res and F in res, res)

        # -- read-only token cannot edit ------------------------------------------
        before = sha(org_file)
        ok, res = rpc.call(RO_TOKEN, "org_set_state", {"id": alpha["id"], "rev": alpha["rev"], "state": "DONE"})
        check("a read-only token's edit is refused before anything changes",
              not ok and "read-only" in res.lower() and sha(org_file) == before, res)
        ok, res = rpc.call(RO_TOKEN, "org_archive_closed", {})
        check("a read-only token's archive is refused", not ok and sha(org_file) == before, res)

        # -- dry run -----------------------------------------------------------------
        ok, res = rpc.call(TOKEN, "org_reschedule", {"id": alpha["id"], "rev": alpha["rev"], "date": "2026-11-21",
                                                      "dry_run": True})
        check("dry run returns the diff and writes nothing",
              ok and res["dry_run"] and not res["written"] and "+SCHEDULED: <2026-11-21 Sat>" in res["diff"]
              and sha(org_file) == before, res)
        dry_sha = next(iter(res["sha256"].values())) if ok else None

        # -- a real edit ----------------------------------------------------------------
        ok, res = rpc.call(TOKEN, "org_reschedule", {"id": alpha["id"], "rev": alpha["rev"], "date": "2026-11-21"})
        text = org_file.read_text()
        check("a rw edit lands on disk with its diff and sha256",
              ok and res["written"] and "SCHEDULED: <2026-11-21 Sat>" in text and res["sha256"][F] == sha(org_file)
              and res["sha256"][F] == dry_sha, res)
        new_rev = res["rev"] if ok else None

        # -- stale -----------------------------------------------------------------------
        before = sha(org_file)
        ok, res = rpc.call(TOKEN, "org_set_state", {"id": alpha["id"], "rev": alpha["rev"], "state": "DONE"})
        check("the old rev is stale and the error carries the current state",
              not ok and "stale:" in res and new_rev in res and "edit 1" not in res and sha(org_file) == before, res)

        # -- needs a note ---------------------------------------------------------------
        ok, res = rpc.call(TOKEN, "org_set_state", {"id": b2["id"], "rev": b2["rev"], "state": "WAIT"})
        check("WAIT without a note fails with note_required", not ok and "note_required" in res, res)

        # -- two clients editing different items ------------------------------------------
        ok, listing = rpc.call(TOKEN, "org_list_items", {})
        by = {i["title"]: i for i in listing["items"]}
        results = []

        def go(title, date):
            r = Rpc(client)
            results.append(r.call(TOKEN, "org_reschedule", {"id": by[title]["id"], "rev": by[title]["rev"], "date": date}))
        threads = [threading.Thread(target=go, args=a) for a in (("beta", "2026-11-23"), ("b2", "2026-11-24"))]
        [t.start() for t in threads]
        [t.join() for t in threads]
        text = org_file.read_text()
        check("two edits to different items both land",
              all(ok for ok, _ in results) and "<2026-11-23 Mon>" in text and "<2026-11-24 Tue>" in text, results)

        # -- the worktree gate ---------------------------------------------------------------
        from app.gate import WorktreeGate
        gate = WorktreeGate(shared_timeout=0.5)
        appmain.VAULT.gate = gate
        ok, listing = rpc.call(TOKEN, "org_list_items", {})
        by = {i["title"]: i for i in listing["items"]}
        held, release = threading.Event(), threading.Event()

        def hold():
            with gate.exclusive():
                held.set()
                release.wait(10)
        t = threading.Thread(target=hold)
        t.start()
        held.wait(5)
        before = sha(org_file)
        ok, res = rpc.call(TOKEN, "org_add_note", {"id": by["b2"]["id"], "rev": by["b2"]["rev"], "note": "during pull"})
        check("an edit while the gate is held fails as busy and changes nothing",
              not ok and "git operation" in res and sha(org_file) == before, res)
        release.set()
        t.join()
        ok, res = rpc.call(TOKEN, "org_add_note", {"id": by["b2"]["id"], "rev": by["b2"]["rev"], "note": "after pull"})
        check("the same edit works once the gate is released", ok and "after pull" in org_file.read_text(), res)

        # -- batch, add_item, archive (through the vault) -----------------------------------
        ok, listing = rpc.call(TOKEN, "org_list_items", {})
        by = {i["title"]: i for i in listing["items"]}
        ok, res = rpc.call(TOKEN, "org_batch", {"edits": [
            {"op": "set_tags", "id": by["b2"]["id"], "rev": by["b2"]["rev"], "tags": ["admin"]},
            {"op": "add_item", "title": "from a batch", "tags": ["jwa"]}]})
        check("org_batch applies edits in one write", ok and len(res["results"]) == 2 and "from a batch" in org_file.read_text(), res)
        ok, res = rpc.call(TOKEN, "org_add_item", {"title": "single add", "deadline": "2026-11-30"})
        check("org_add_item returns the new id and rev", ok and res["id"] and res["rev"], res)
        ok, listing = rpc.call(TOKEN, "org_list_items", {"state": "all"})
        done = next(i for i in listing["items"] if i["title"] == "delta")
        ok, res = rpc.call(TOKEN, "org_archive", {"id": done["id"], "rev": done["rev"]})
        arch = data / "org-projects/archive/inbox.org_archive"
        check("org_archive creates the archive file and directory through the vault",
              ok and arch.exists() and "* DONE delta" in arch.read_text() and "DONE delta" not in org_file.read_text(), res)
        check("no temp files are left behind", not list(data.rglob(".upload-*")))
        ok, res = rpc.call(TOKEN, "org_archive_closed", {"older_than_days": 1, "dry_run": True})
        check("org_archive_closed dry run lists what it would do", ok and res["dry_run"], res)
    return 0


def scenario_startup(data, setting, value, needle):
    env(data)
    os.environ[setting] = value
    try:
        from app import main  # noqa: F401
    except RuntimeError as exc:
        check(f"{setting}={value} refuses to start and names the setting", setting in str(exc) and needle in str(exc), exc)
    else:
        check(f"{setting}={value} refuses to start", False, "the server started")


def main():
    scenario, data = sys.argv[1], Path(sys.argv[2])
    try:
        if scenario == "app":
            scenario_app(data)
        elif scenario == "bad_tz":
            scenario_startup(data, "ORG_TIMEZONE", "Mars/Olympus", "Mars/Olympus")
        elif scenario == "bad_files":
            scenario_startup(data, "ORG_FILES", "../outside.org", "outside.org")
    except Exception as exc:                     # report what ran, then the crash as a failed check
        import traceback
        check("scenario ran to the end", False, traceback.format_exc()[-500:] + repr(exc))
    for c in CHECKS:
        print("CHECK " + json.dumps(c))


if __name__ == "__main__":
    main()
