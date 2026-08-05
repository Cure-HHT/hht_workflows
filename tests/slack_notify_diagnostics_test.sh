#!/usr/bin/env bash
# Verifies slack-notify's "post" step surfaces named diagnostics for every
# failure tier on the three hard-fail Slack API calls (conversations.list,
# conversations.join, chat.postMessage) instead of dying on a bare curl exit
# code when the transport itself fails (CUR-1879).
set -euo pipefail
cd "$(dirname "$0")/.."

script="$(python3 -c '
import yaml
a = yaml.safe_load(open(".github/actions/slack-notify/action.yml"))
print(a["runs"]["steps"][0]["run"])')"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/slack-channels.yml" <<'EOF'
routing:
  deploy-success: ops
channels:
  ops: "#ops-test"
EOF

export EVENT="deploy-success"
export ENV_KEY=""
export TEXT="test message"
export BLOCKS=""
export BOOKMARK_TITLE=""
export SLACK_TOKEN="xoxb-fake"
export ROUTING_FILE="$tmp/slack-channels.yml"
export DM_ONLY="false"
export GITHUB_OUTPUT="$tmp/github_output"; : > "$GITHUB_OUTPUT"

fail=0
run_case() {  # $1 = case name, $2 = expected grep pattern
  local out rc=0
  out="$(PATH="$tmp/bin:$PATH" bash -c "$script" 2>&1)" || rc=$?
  if [ "$rc" -eq 0 ]; then echo "FAIL($1): expected nonzero exit"; fail=1; fi
  if ! grep -qF "$2" <<<"$out"; then
    echo "FAIL($1): missing diagnostic '$2'. Got:"; echo "$out"; fail=1
  else echo "ok($1)"; fi
}

mkdir -p "$tmp/bin"

# Case 1: conversations.list transport failure (curl rc=6, no HTTP response)
# -> named diagnostic, not a bare exit code.
cat > "$tmp/bin/curl" <<'EOF'
#!/usr/bin/env bash
exit 6
EOF
chmod +x "$tmp/bin/curl"
run_case "conversations-list-transport" "Slack conversations.list got no HTTP response (curl exit 6"

# Case 2: conversations.list succeeds (one page, one channel), then
# conversations.join transport-fails.
cat > "$tmp/bin/curl" <<'EOF'
#!/usr/bin/env bash
out=/dev/stdout
args=("$@")
for ((i=0;i<${#args[@]};i++)); do [ "${args[$i]}" = "-o" ] && out="${args[$((i+1))]}"; done
case "$*" in
  *conversations.list*) printf '{"ok":true,"channels":[{"name":"ops-test","id":"C123"}],"response_metadata":{"next_cursor":""}}' > "$out"; printf '200';;
  *conversations.join*) exit 6;;
  *) printf '{}' > "$out"; printf '200';;
esac
EOF
chmod +x "$tmp/bin/curl"
run_case "conversations-join-transport" "Slack conversations.join for #ops-test (C123) got no HTTP response (curl exit 6"

# Case 3: conversations.list + conversations.join succeed, chat.postMessage
# transport-fails.
cat > "$tmp/bin/curl" <<'EOF'
#!/usr/bin/env bash
out=/dev/stdout
args=("$@")
for ((i=0;i<${#args[@]};i++)); do [ "${args[$i]}" = "-o" ] && out="${args[$((i+1))]}"; done
case "$*" in
  *conversations.list*) printf '{"ok":true,"channels":[{"name":"ops-test","id":"C123"}],"response_metadata":{"next_cursor":""}}' > "$out"; printf '200';;
  *conversations.join*) printf '{"ok":true}' > "$out"; printf '200';;
  *chat.postMessage*)   exit 6;;
  *) printf '{}' > "$out"; printf '200';;
esac
EOF
chmod +x "$tmp/bin/curl"
run_case "chat-postmessage-transport" "Slack chat.postMessage for #ops-test (C123) got no HTTP response (curl exit 6"

# Case 4: success path still works end to end (regression guard).
cat > "$tmp/bin/curl" <<'EOF'
#!/usr/bin/env bash
out=/dev/stdout
args=("$@")
for ((i=0;i<${#args[@]};i++)); do [ "${args[$i]}" = "-o" ] && out="${args[$((i+1))]}"; done
case "$*" in
  *conversations.list*) printf '{"ok":true,"channels":[{"name":"ops-test","id":"C123"}],"response_metadata":{"next_cursor":""}}' > "$out"; printf '200';;
  *conversations.join*) printf '{"ok":true}' > "$out"; printf '200';;
  *chat.postMessage*)   printf '{"ok":true,"ts":"1234.5678"}' > "$out"; printf '200';;
  *) printf '{}' > "$out"; printf '200';;
esac
EOF
chmod +x "$tmp/bin/curl"
: > "$GITHUB_OUTPUT"
rc=0
out="$(PATH="$tmp/bin:$PATH" bash -c "$script" 2>&1)" || rc=$?
if [ "$rc" -ne 0 ]; then echo "FAIL(success): expected exit 0, got $rc. Got:"; echo "$out"; fail=1; else echo "ok(success-exit)"; fi
if ! grep -qF "channel-ids=C123" "$GITHUB_OUTPUT"; then
  echo "FAIL(success): channel-ids missing from GITHUB_OUTPUT. File contents:"; cat "$GITHUB_OUTPUT"; fail=1
else echo "ok(success-output)"; fi

exit "$fail"
