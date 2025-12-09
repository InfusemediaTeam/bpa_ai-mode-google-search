#!/bin/sh
# Periodic cleanup of Chromium profiles and heavy caches inside the container.
# This script runs INSIDE the browser-worker container and does NOT use docker CLI.
# It detects active --user-data-dir paths by scanning /proc/*/cmdline and avoids
# cleaning the active base profile directory.
#
# Config via env:
#   CLEANUP_MIN_AGE_MINUTES  - min age for session_* dirs to delete (default: 60)
#   CLEANUP_INCLUDE_ACTIVE_CACHES - if "1", also clean caches in active base (default: 0)
#
set -eu

MIN_AGE_MINUTES="${CLEANUP_MIN_AGE_MINUTES:-60}"
INCLUDE_ACTIVE_CACHES="${CLEANUP_INCLUDE_ACTIVE_CACHES:-0}"

log() { printf '%s\n' "$*"; }

# Collect active user-data-dir paths by reading /proc cmdlines
ACTIVE_DIRS=""
for f in /proc/[0-9]*/cmdline; do
  [ -r "$f" ] || continue
  cmd=$(tr '\0' ' ' < "$f" || true)
  case "$cmd" in
    *--user-data-dir=*)
      # extract value after --user-data-dir=
      ud=$(printf '%s' "$cmd" | sed -n 's/.*--user-data-dir=\([^ ]*\).*/\1/p') || true
      if [ -n "$ud" ]; then
        # de-dup by checking presence in string (space-delimited)
        case " $ACTIVE_DIRS " in
          *" $ud "*) :;;
          *) ACTIVE_DIRS="$ACTIVE_DIRS $ud";;
        esac
      fi
      ;;
  esac
done

log "[cleanup] Active user-data-dir(s):${ACTIVE_DIRS:- none}"

is_base_active() {
  # returns 0 if any active dir equals base or is a subdir of base
  base="$1"
  for ad in $ACTIVE_DIRS; do
    [ -n "$ad" ] || continue
    case "$ad" in
      "$base"|"$base"/*) return 0 ;;
    esac
  done
  return 1
}

clean_caches_in_base() {
  base="$1"
  # Heavy caches
  for name in "Cache" "Code Cache" "GPUCache" "ShaderCache" "GrShaderCache" "DawnShaderCache"; do
    # print
    find "$base" -type d -name "$name" -prune -print 2>/dev/null || true
    # delete
    find "$base" -type d -name "$name" -prune -exec rm -rf {} + 2>/dev/null || true
  done
  find "$base" -type d -path "*/Service Worker/CacheStorage" -prune -print 2>/dev/null || true
  find "$base" -type d -path "*/Service Worker/CacheStorage" -prune -exec rm -rf {} + 2>/dev/null || true
  find "$base" -type d -name "Crashpad" -prune -print 2>/dev/null || true
  find "$base" -type d -name "Crashpad" -prune -exec rm -rf {} + 2>/dev/null || true
  find "$base" -maxdepth 1 -type d -name "DeferredBrowserMetrics" -print 2>/dev/null || true
  find "$base" -maxdepth 1 -type d -name "DeferredBrowserMetrics" -exec rm -rf {} + 2>/dev/null || true
  find "$base" -maxdepth 1 -type d -name "component_crx_cache" -print 2>/dev/null || true
  find "$base" -maxdepth 1 -type d -name "component_crx_cache" -exec rm -rf {} + 2>/dev/null || true
}

# Iterate over profile bases
for base in /data/.ai_mode_chrome_*; do
  [ -d "$base" ] || continue
  if is_base_active "$base"; then
    log "[cleanup] SKIP active base: $base"
    if [ "$INCLUDE_ACTIVE_CACHES" = "1" ]; then
      log "[cleanup] CLEAN caches in active base: $base (use with care)"
      clean_caches_in_base "$base"
    fi
    continue
  fi

  log "[cleanup] Cleaning base: $base"
  # 1) old session_* dirs
  find "$base" -maxdepth 1 -type d -name "session_*" -mmin "+$MIN_AGE_MINUTES" -print 2>/dev/null \
    | while IFS= read -r d; do [ -n "$d" ] || continue; log "[cleanup] delete $d"; rm -rf "$d"; done

  # 2) heavy caches in non-active base
  clean_caches_in_base "$base"

done

log "[cleanup] done"
