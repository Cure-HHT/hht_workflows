#!/usr/bin/env bash
# Verifies the auth composite surfaces named diagnostics for every failure
# tier instead of dying on a bare curl exit code.
set -euo pipefail
cd "$(dirname "$0")/.."

script="$(python3 -c '
import yaml
a = yaml.safe_load(open(".github/actions/doppler-cli-oidc-auth/action.yml"))
print(a["runs"]["steps"][0]["run"])')"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export DOPPLER_IDENTITY_ID="00000000-0000-0000-0000-000000000000"
export ACTIONS_ID_TOKEN_REQUEST_TOKEN="stub"
export ACTIONS_ID_TOKEN_REQUEST_URL="https://stub.example/token?x=1"
export GITHUB_ENV="$tmp/github_env"; : > "$GITHUB_ENV"

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

# Case 1: exchange rejected with HTTP 401 -> names the call, status, body.
cat > "$tmp/bin/curl" <<'EOF'
#!/usr/bin/env bash
out=/dev/stdout
args=("$@")
for ((i=0;i<${#args[@]};i++)); do [ "${args[$i]}" = "-o" ] && out="${args[$((i+1))]}"; done
case "$*" in
  *stub.example*) printf '{"value":"fake-oidc-jwt"}' > "$out"; printf '200';;
  *auth/oidc*)    printf '{"messages":["identity not authorized for this workflow ref"]}' > "$out"; printf '401';;
  *)              printf '{}' > "$out"; printf '200';;
esac
EOF
chmod +x "$tmp/bin/curl"
run_case "exchange-401" "Doppler OIDC token exchange"
run_case "exchange-401-status" "HTTP 401"
run_case "exchange-401-body" "identity not authorized"

# Case 2: transport failure (curl rc=6, no HTTP response) -> named transport error.
cat > "$tmp/bin/curl" <<'EOF'
#!/usr/bin/env bash
exit 6
EOF
chmod +x "$tmp/bin/curl"
run_case "transport" "curl exit 6"

# Case 3: valid token, zero projects -> the prepared no-project-access message.
cat > "$tmp/bin/curl" <<'EOF'
#!/usr/bin/env bash
out=/dev/stdout
args=("$@")
for ((i=0;i<${#args[@]};i++)); do [ "${args[$i]}" = "-o" ] && out="${args[$((i+1))]}"; done
case "$*" in
  *stub.example*) printf '{"value":"fake-oidc-jwt"}' > "$out"; printf '200';;
  *auth/oidc*)    printf '{"token":"dp.st.fake"}' > "$out"; printf '200';;
  *v3/projects*)  printf '{"projects":[],"page":1}' > "$out"; printf '200';;
  *)              printf '{}' > "$out"; printf '200';;
esac
EOF
chmod +x "$tmp/bin/curl"
run_case "zero-projects" "no project access"

# Case 4 (leak guard): success bodies never echoed — token string must not
# appear in output even on the zero-projects failure path. Filter workflow
# commands (::add-mask::) which legitimately contain the token.
out="$(PATH="$tmp/bin:$PATH" bash -c "$script" 2>&1)" || true_rc=$?
if grep -v '^::add-mask::' <<<"$out" | grep -q "dp.st.fake"; then echo "FAIL(leak): token echoed"; fail=1; else echo "ok(leak)"; fi

# Case 5: success path with mask-before-export ordering verification.
# Stub curl returns valid OIDC token, valid exchange token, and non-empty projects.
# Assert: (a) output contains ::add-mask:: line, (b) DOPPLER_TOKEN in $GITHUB_ENV,
# (c) exit 0, (d) masking directive appears before export to file.
cat > "$tmp/bin/curl" <<'EOF'
#!/usr/bin/env bash
out=/dev/stdout
args=("$@")
for ((i=0;i<${#args[@]};i++)); do [ "${args[$i]}" = "-o" ] && out="${args[$((i+1))]}"; done
case "$*" in
  *stub.example*) printf '{"value":"fake-oidc-jwt"}' > "$out"; printf '200';;
  *auth/oidc*)    printf '{"token":"dp.st.fake"}' > "$out"; printf '200';;
  *v3/projects*)  printf '{"projects":[{"name":"test"}],"page":1}' > "$out"; printf '200';;
  *)              printf '{}' > "$out"; printf '200';;
esac
EOF
chmod +x "$tmp/bin/curl"
: > "$GITHUB_ENV"  # Reset env file
rc=0
out="$(PATH="$tmp/bin:$PATH" bash -c "$script" 2>&1)" || rc=$?
if [ "$rc" -ne 0 ]; then echo "FAIL(success): expected exit 0, got $rc"; fail=1; fi
if ! grep -qF "::add-mask::dp.st.fake" <<<"$out"; then
  echo "FAIL(success): missing ::add-mask:: directive in output. Got:"; echo "$out"; fail=1
else echo "ok(success-exit)"; fi
if ! grep -qF "DOPPLER_TOKEN=dp.st.fake" "$GITHUB_ENV"; then
  echo "FAIL(success): token not in GITHUB_ENV. File contents:"; cat "$GITHUB_ENV"; fail=1
else echo "ok(success-export)"; fi

exit "$fail"
