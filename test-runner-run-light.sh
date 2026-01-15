#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# test-runner-run-light.sh
#
# Test-runner för runLightSeriesUpdates.py
#
# Varje testfall körs i en isolerad katalog:
#   - pristine/        (orört ingångsdata)
#   - games.csv        (muteras)
#   - series_live.csv  (muteras)
#   - hashes/          (muteras)
#
# now.txt (valfri):
#   YYYY-MM-DD HH:MM
###############################################################################

ROOT_DIR="$(pwd)"
RUN_SCRIPT="$ROOT_DIR/scripts/runLightSeriesUpdates.py"
TEST_ROOT="$ROOT_DIR/tests/run_light"

echo "==================================================================="
echo " runLightSeriesUpdates.py test runner"
echo " Date      : $(date '+%Y-%m-%d %H:%M:%S')"
echo " Test root : $TEST_ROOT"
echo "==================================================================="

FAIL=0
PASS=0
ERRORS=0
TOTAL=0

# For pretty summary
RESULTS=()  # entries: "ID|NAME|RESULT"

echo "[DBG] Scanning: $TEST_ROOT/TC*"

###############################################################################
# Iterate over all test case directories
###############################################################################
ID=0
for TC_DIR in "$TEST_ROOT"/TC*; do
    [[ -d "$TC_DIR" ]] || continue

    ID=$((ID + 1))
    TOTAL=$((TOTAL + 1))

    TC_NAME="$(basename "$TC_DIR")"

    echo
    echo "[TEST] === $TC_NAME ==="

    PRISTINE="$TC_DIR/pristine"
    GAMES_FILE="$TC_DIR/games.csv"
    SERIES_LIVE="$TC_DIR/series_live.csv"
    HASH_DIR="$TC_DIR/hashes"
    HTML_ROOT="$TC_DIR/live_html"
    NOW_FILE="$TC_DIR/now.txt"

    # -------------------------------------------------------------------------
    # Validate pristine
    # -------------------------------------------------------------------------
    if [[ ! -d "$PRISTINE" ]]; then
        echo "[TEST] FAIL ✗ missing pristine/"
        FAIL=$((FAIL + 1))
        RESULTS+=("${ID}|${TC_NAME}|FAIL")
        continue
    fi

    for f in games.csv series_live.csv; do
        if [[ ! -f "$PRISTINE/$f" ]]; then
            echo "[TEST] FAIL ✗ missing pristine/$f"
            FAIL=$((FAIL + 1))
            RESULTS+=("${ID}|${TC_NAME}|FAIL")
            continue 2
        fi
    done

    # -------------------------------------------------------------------------
    # Reset state
    # -------------------------------------------------------------------------
    echo "[TEST] Resetting state from pristine/"

    cp "$PRISTINE/games.csv" "$GAMES_FILE"
    cp "$PRISTINE/series_live.csv" "$SERIES_LIVE"

    rm -rf "$HASH_DIR"
    mkdir -p "$HASH_DIR"

    if compgen -G "$PRISTINE/hashes/*.hash" > /dev/null; then
        cp "$PRISTINE/hashes/"*.hash "$HASH_DIR"/
    fi

    mkdir -p "$HTML_ROOT"

    # -------------------------------------------------------------------------
    # Build NOW args (array-safe, set -u safe)
    # -------------------------------------------------------------------------
    NOW_ARGS=()

    if [[ -f "$NOW_FILE" ]]; then
        TEST_NOW="$(<"$NOW_FILE")"
        echo "[TEST] Using NOW = $TEST_NOW"
        NOW_ARGS+=(--now "$TEST_NOW")
    fi

    # -------------------------------------------------------------------------
    # Execute test
    # -------------------------------------------------------------------------
    set +e
    python3 "$RUN_SCRIPT" \
        --gf "$GAMES_FILE" \
        --slf "$SERIES_LIVE" \
        --html-root "$HTML_ROOT" \
        --hash-dir "$HASH_DIR" \
        "${NOW_ARGS[@]}" \
        -dbg
    RC=$?
    set -e

    if [[ $RC -ne 0 ]]; then
        echo "[TEST] ERROR ✗ script exited with code $RC"
        ERRORS=$((ERRORS + 1))
        RESULTS+=("${ID}|${TC_NAME}|ERROR")
        continue
    fi

    # -------------------------------------------------------------------------
    # Assertions
    # -------------------------------------------------------------------------
    if [[ -f "$TC_DIR/expected/series_live.csv" ]]; then
        if ! diff -u "$TC_DIR/expected/series_live.csv" "$SERIES_LIVE"; then
            echo "[TEST] FAIL ✗ series_live.csv differs"
            FAIL=$((FAIL + 1))
            RESULTS+=("${ID}|${TC_NAME}|FAIL")
            continue
        fi
    fi

    # Hash compare (timestamp-agnostic) via tests/run_light/hash_compare.py
    if [[ -d "$TC_DIR/expected/hashes" ]]; then
        set +e
        python3 - <<PY
import sys
from pathlib import Path

# Se till att vi kan importera tests/run_light/hash_compare.py
sys.path.insert(0, str(Path("$TEST_ROOT").resolve()))
from hash_compare import assert_hash_dir_matches

ok = assert_hash_dir_matches("$TC_DIR")
sys.exit(0 if ok else 1)
PY
        HRC=$?
        set -e

        if [[ $HRC -ne 0 ]]; then
            echo "[TEST] FAIL ✗ hash directory differs (timestamp-agnostic compare)"
            FAIL=$((FAIL + 1))
            RESULTS+=("${ID}|${TC_NAME}|FAIL")
            continue
        fi
    fi

    if [[ -f "$TC_DIR/expected/games.csv" ]]; then
        if ! diff -u "$TC_DIR/expected/games.csv" "$GAMES_FILE"; then
            echo "[TEST] FAIL ✗ games.csv differs"
            FAIL=$((FAIL + 1))
            RESULTS+=("${ID}|${TC_NAME}|FAIL")
            continue
        fi
    fi

    echo "[TEST] PASS ✓ $TC_NAME"
    PASS=$((PASS + 1))
    RESULTS+=("${ID}|${TC_NAME}|PASS")
done

###############################################################################
# Summary (table format like other runners)
###############################################################################
echo
echo "[TEST] ================================================================"
echo "[TEST] SUMMARY OF ALL RUN-LIGHT TEST CASES"
printf "%-4s %-40s %-10s\n" "ID" "NAME" "RESULT"
echo "-----------------------------------------------------------------------"

for entry in "${RESULTS[@]}"; do
    IFS="|" read -r rid rname rres <<< "$entry"
    printf "%-4s %-40s %-10s\n" "$rid" "$rname" "$rres"
done

echo "-----------------------------------------------------------------------"
echo "TOTAL: $TOTAL tests"
echo "PASS : $PASS"
echo "FAIL : $FAIL"
echo "ERROR: $ERRORS"
echo "-----------------------------------------------------------------------"

if [[ $FAIL -ne 0 || $ERRORS -ne 0 ]]; then
    echo "[TEST] SOME TESTS FAILED ✗"
    exit 1
fi

echo "[TEST] ALL TESTS PASSED ✓"
exit 0
