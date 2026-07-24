#!/usr/bin/env bash
# =====================================================
# Git-hooks activation guard — shared, repo-agnostic
# =====================================================
#
# The canonical home of the guard the whole org vendors (CUR-1780),
# generalized from hht_diary's tools/lib/hooks-guard.sh (CUR-1775). One
# implementation, reused — not reinvented per repo — so a covered repo's
# fresh-clone verifier and its developer entry points agree on what "hooks
# are active" means. See HHT-OPS-repo-bootstrap/F in Cure-HHT/hht_admin.
#
# Why it exists: `core.hooksPath` is LOCAL git config a repo's setup command
# writes, and no git config survives a clone. Git offers no clone-time
# execution point to fix that automatically (`init.templateDir` is itself
# machine-local), so the only honest mechanism is for the developer entry
# points people actually reach to say so when hooks are inert.
#
# The path may legitimately be absolute rather than the literal hooks dir:
# a Claude Code session-start hook sets core.hooksPath globally to an
# absolute path. Resolve before comparing, or this guard tells a contributor
# whose hooks ARE active that they are not.
#
# Usage (source it, then call):
#   source "$REPO_ROOT/bootstrap/hooks-guard.sh"
#   hht_hooks_guard "$REPO_ROOT" [hooks_dir] [setup_cmd] [verify_cmd]
#
# Arguments (all optional except repo_root):
#   repo_root   path to the repository root (default ".")
#   hooks_dir   hooks directory relative to repo_root (default ".githooks")
#   setup_cmd   the command that activates hooks   (default "scripts/setup.sh")
#   verify_cmd  the command that verifies the setup (default "scripts/setup.sh --check")
#
# Two entry points, one comparison:
#
#   hht_hooks_active <repo_root> [hooks_dir]
#       Pure predicate — 0 = this repo's hooks are active, 1 = not. No output,
#       and NOT silent under CI. Use it from an authoritative verify command
#       (HHT-OPS-repo-bootstrap/B), which must report the not-set-up state
#       through its exit status even on a CI runner.
#
#   hht_hooks_guard <repo_root> [hooks_dir] [setup_cmd] [verify_cmd]
#       Developer-facing warning (HHT-OPS-repo-bootstrap/F). Wraps the same
#       predicate but is CI-silent (the pipeline runs the checks directly, so
#       local hooks are irrelevant there) and prints actionable guidance.
#       Warns by default; HHT_HOOKS_GUARD=strict makes it fatal,
#       HHT_HOOKS_GUARD=off silences it.
#
# Both resolve an absolute core.hooksPath before comparing, so a setting
# pointing at THIS repo's hooks dir (what a Claude session-start hook writes)
# counts as active, while one pointing at another checkout's hooks does not.

hht_hooks_active() {
    local repo_root="${1:-.}"
    local hooks_dir="${2:-.githooks}"
    local hooks_path resolved expected
    hooks_path="$(git -C "$repo_root" config --get core.hooksPath 2>/dev/null)" || hooks_path=""
    [ -n "$hooks_path" ] || return 1
    # Relative values resolve against the repo root, absolute ones stand.
    case "$hooks_path" in
        /*) resolved="$hooks_path" ;;
        *)  resolved="$repo_root/$hooks_path" ;;
    esac
    expected="$repo_root/$hooks_dir"
    [ -d "$resolved" ] && [ -d "$expected" ] &&
        [ "$(cd "$resolved" && pwd -P)" = "$(cd "$expected" && pwd -P)" ]
}

# Implements: HHT-OPS-repo-bootstrap/F
hht_hooks_guard() {
    local repo_root="${1:-.}"
    local hooks_dir="${2:-.githooks}"
    local setup_cmd="${3:-scripts/setup.sh}"
    local verify_cmd="${4:-scripts/setup.sh --check}"
    local mode="${HHT_HOOKS_GUARD:-warn}"

    [ "$mode" = "off" ] && return 0
    [ -n "${CI:-}" ] && return 0

    hht_hooks_active "$repo_root" "$hooks_dir" && return 0

    local hooks_path expected
    hooks_path="$(git -C "$repo_root" config --get core.hooksPath 2>/dev/null)" || hooks_path=""
    expected="$repo_root/$hooks_dir"

    if [ -n "$hooks_path" ]; then
        echo ""
        echo "  !!  core.hooksPath does not point at this repo's hooks:"
        echo "        configured: $hooks_path"
        echo "        expected:   $expected"
        echo "      Another checkout's hooks may be running against this one. Fix with:"
        echo ""
        echo "          $setup_cmd"
        echo ""
        if [ "$mode" = "strict" ]; then
            echo "  !!  HHT_HOOKS_GUARD=strict — refusing to continue."
            echo ""
            return 1
        fi
        return 0
    fi

    echo ""
    echo "  !!  This clone's git hooks are NOT active (core.hooksPath is unset)."
    echo "      The hooks bound only to $hooks_dir/ are not running at all."
    echo "      Activate the supported set with:"
    echo ""
    echo "          $setup_cmd"
    echo ""
    echo "      Verify with: $verify_cmd"
    echo ""

    if [ "$mode" = "strict" ]; then
        echo "  !!  HHT_HOOKS_GUARD=strict — refusing to continue."
        echo ""
        return 1
    fi
    return 0
}

# =====================================================
# elspais associate guard
# =====================================================
#
# Cross-repo requirement citations (Refines:/Integrates: naming another repo's
# REQ) resolve only when that repo is linked as an elspais associate. The link
# lives in .elspais.local.toml, which names filesystem paths and is git-ignored
# -- so, exactly like core.hooksPath, it cannot survive a clone.
#
#   hht_associates_linked <repo_root>
#       Pure predicate. 0 = nothing to link, or something is linked.
#       1 = this repo cites another repo and nothing is linked. No output.
#
#   hht_associates_guard <repo_root>
#       CI-silent developer warning naming `elspais associate --all`.

# Returns 0 when spec/ contains a structured citation whose namespace differs
# from this repo's own; 1 otherwise.
hht_cites_foreign_repo() {
    local repo_root="${1:-.}"
    local ns
    [ -f "$repo_root/.elspais.toml" ] || return 1
    [ -d "$repo_root/spec" ] || return 1
    ns="$(sed -n 's/^ *namespace *= *"\([A-Za-z0-9]*\)".*/\1/p' \
          "$repo_root/.elspais.toml" | head -1)"
    [ -n "$ns" ] || return 1
    # One pass: collect every namespace cited by a structured edge, then ask
    # whether any of them is not ours.
    # Organization's elspais levels -- update this alternation when a new
    # level is introduced.
    grep -rhE '^\*\*(Refines|Implements|Integrates)\*\*:' "$repo_root/spec" 2>/dev/null \
        | grep -oE '[A-Za-z0-9]+-(PRD|OPS|DEV|GUI|BASE)-' \
        | grep -qvE "^${ns}-"
}

# Implements: HHT-OPS-repo-bootstrap/I
hht_associates_linked() {
    local repo_root="${1:-.}"
    hht_cites_foreign_repo "$repo_root" || return 0
    [ -s "$repo_root/.elspais.local.toml" ] &&
        grep -q '\[associates\.' "$repo_root/.elspais.local.toml"
}

# Implements: HHT-OPS-repo-bootstrap/I
hht_associates_guard() {
    local repo_root="${1:-.}"
    local mode="${HHT_HOOKS_GUARD:-warn}"

    [ "$mode" = "off" ] && return 0
    [ -n "${CI:-}" ] && return 0

    hht_associates_linked "$repo_root" && return 0

    echo ""
    echo "  !!  This repo cites requirements owned by another Cure-HHT repo,"
    echo "      but no elspais associate is linked, so those citations will"
    echo "      not resolve and \`elspais checks\` will report broken references."
    echo "      Link the sibling repos you have cloned with:"
    echo ""
    echo "          elspais associate --all"
    echo ""

    if [ "$mode" = "strict" ]; then
        echo "  !!  HHT_HOOKS_GUARD=strict — refusing to continue."
        echo ""
        return 1
    fi
    return 0
}
