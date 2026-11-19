#!/usr/bin/env bash
# Build the derived image and run it the way production does (read-only rootfs, no capabilities,
# no-new-privileges, a bind-mounted folder). Checks: health, org_* in tools/list, org_list_items, a dry
# run, a real edit visible on disk, and a read-only token's refusal.
#
#   tests/container_smoke.sh                 build ./Dockerfile as claude-files-org:smoke and test it
#   IMAGE=ghcr.io/...:tag SKIP_BUILD=1 ...   test an existing image
#
# Needs docker (and python3 for the JSON-RPC calls). The base image
# ghcr.io/eguthriewastaken/claude-files:1.4.0 must be pullable, or built locally and tagged with that name.
# Env: PORT (default 18080), DOCKER_NETWORK (default bridge; "host" when the daemon has no bridge).
set -euo pipefail

cd "$(dirname "$0")/.."
IMAGE="${IMAGE:-claude-files-org:smoke}"
PORT="${PORT:-18080}"
NETWORK="${DOCKER_NETWORK:-bridge}"
NAME="claude-files-org-smoke-$$"
TOKEN="rw-token-aaaaaaaaaaaaaaaaaaaaaaaa"
RO_TOKEN="ro-token-bbbbbbbbbbbbbbbbbbbbbbbb"
data="$(mktemp -d)"

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  rm -rf "$data"
}
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; docker logs "$NAME" 2>&1 | tail -20 >&2 || true; exit 1; }
pass() { echo "PASS: $*"; }

if [ -z "${SKIP_BUILD:-}" ]; then
  build_args=()
  # buildkit rejects "--network=bridge"; the default network needs no flag
  [ "$NETWORK" = "host" ] && build_args+=(--network host)
  docker build "${build_args[@]}" -t "$IMAGE" .
fi

mkdir -p "$data/org-projects"
cp tests/fixtures/clean.org "$data/org-projects/inbox.org"
chmod -R a+rwX "$data"          # the container runs as uid 1000

run_args=(--name "$NAME" -d --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges
          -v "$data:/data" -e API_TOKEN="$TOKEN" -e API_TOKEN_READONLY="$RO_TOKEN" -e REQUIRE_MOUNT=false)
if [ "$NETWORK" = "host" ]; then
  run_args+=(--network host)
else
  run_args+=(-p "127.0.0.1:$PORT:8080")
fi
docker run "${run_args[@]}" "$IMAGE" >/dev/null
[ "$NETWORK" = "host" ] && PORT=8080

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 || fail "the container did not become healthy"
pass "health OK (read-only rootfs, cap-drop ALL, no-new-privileges)"

export PORT TOKEN RO_TOKEN DATA="$data"
python3 - <<'PY'
import hashlib, json, os, sys, urllib.request

port, token, ro, data = os.environ["PORT"], os.environ["TOKEN"], os.environ["RO_TOKEN"], os.environ["DATA"]
path = os.path.join(data, "org-projects", "inbox.org")
n = [0]


def rpc(tok, method, params=None):
    n[0] += 1
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp", method="POST",
        data=json.dumps({"jsonrpc": "2.0", "id": n[0], "method": method, "params": params or {}}).encode(),
        headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
                 "Authorization": f"Bearer {tok}"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def call(tok, name, args=None):
    res = rpc(tok, "tools/call", {"name": name, "arguments": args or {}})
    if "error" in res:
        return False, res["error"].get("message", "")
    r = res["result"]
    text = "".join(c.get("text", "") for c in r.get("content", []))
    return (not r.get("isError")), (json.loads(text) if not r.get("isError") else text)


def sha():
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def check(name, ok, detail=""):
    print(("PASS: " if ok else "FAIL: ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        sys.exit(1)


names = {t["name"] for t in rpc(token, "tools/list")["result"]["tools"]}
check("tools/list includes the org_* tools and the core tools",
      {"org_list_items", "org_set_state", "org_batch", "org_archive"} <= names and "read_file" in names, sorted(names))
ok, listing = call(token, "org_list_items")
alpha = next((i for i in listing["items"] if i["title"] == "alpha"), None) if ok else None
check("org_list_items returns the open items", ok and alpha and listing["total"] >= 3, listing)
before = sha()
ok, dry = call(token, "org_reschedule", {"id": alpha["id"], "rev": alpha["rev"], "date": "2026-11-21", "dry_run": True})
check("a dry run returns the diff and leaves the file alone",
      ok and "+SCHEDULED: <2026-11-21 Sat>" in dry["diff"] and sha() == before, dry)
ok, real = call(token, "org_reschedule", {"id": alpha["id"], "rev": alpha["rev"], "date": "2026-11-21"})
check("a real edit is visible on disk", ok and "SCHEDULED: <2026-11-21 Sat>" in open(path).read()
      and real["sha256"]["org-projects/inbox.org"] == sha(), real)
before = sha()
ok, res = call(ro, "org_set_state", {"id": alpha["id"], "rev": real["rev"], "state": "DONE"})
check("a read-only token's edit is refused", not ok and "read-only" in res.lower() and sha() == before, res)
ok, res = call(ro, "org_list_items")
check("a read-only token can read", ok, res)
PY
pass "container smoke test"
