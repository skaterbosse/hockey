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
HASH_COMPARE="$TEST_ROOT/hash_compare.py"

echo "==================================================================="
echo " runLightSeriesUpdates.py test runner"
echo " Date      : $(date '+%Y-%m-%d %H:%M:%S')"
echo " Test root : $TEST_ROOT"
echo "==================================================================="

FAIL=0
PASS=0

echo "[DBG] Scanning: $TEST_ROOT/TC*"

###############################################################################
# Iterate over all test case directories
###############################################################################
for TC_DIR in "$TEST_ROOT"/TC*; do
    [[ -d "$TC_DIR" ]] || continue

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
        continue
    fi

    for f in games.csv series_live.csv; do
        if [[ ! -f "$PRISTINE/$f" ]]; then
            echo "[TEST] FAIL ✗ missing pristine/$f"
            FAIL=$((FAIL + 1))
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
        echo "[TEST] FAIL ✗ script exited with code $RC"
        FAIL=$((FAIL + 1))
        continue
    fi

    # -------------------------------------------------------------------------
    # Assertions
    # -------------------------------------------------------------------------
    if [[ -f "$TC_DIR/expected/series_live.csv" ]]; then
        if ! diff -u "$TC_DIR/expected/series_live.csv" "$SERIES_LIVE"; then
            echo "[TEST] FAIL ✗ series_live.csv differs"
            FAIL=$((FAIL + 1))
            continue
        fi
    fi

    # Hash compare (normalized: ignore timestamp in hash files)
    if [[ -d "$TC_DIR/expected/hashes" ]]; then
        if [[ ! -f "$HASH_COMPARE" ]]; then
            echo "[TEST] FAIL ✗ missing hash compare helper: $HASH_COMPARE"
            FAIL=$((FAIL + 1))
            continue
        fi

        set +e
        python3 "$HASH_COMPARE" "$TC_DIR"
        RC_HASH=$?
        set -e

        if [[ $RC_HASH -ne 0 ]]; then
            echo "[TEST] FAIL ✗ hash directory differs (normalized compare)"
            FAIL=$((FAIL + 1))
            continue
        fi
    fi

    if [[ -f "$TC_DIR/expected/games.csv" ]]; then
        if ! diff -u "$TC_DIR/expected/games.csv" "$GAMES_FILE"; then
            echo "[TEST] FAIL ✗ games.csv differs"
            FAIL=$((FAIL + 1))
            continue
        fi
    fi

    echo "[TEST] PASS ✓ $TC_NAME"
    PASS=$((PASS + 1))
done

###############################################################################
# Summary
###############################################################################
echo
echo "==================================================================="
echo "[TEST] SUMMARY"
echo "PASS : $PASS"
echo "FAIL : $FAIL"
echo "TOTAL: $((PASS + FAIL))"
echo "==================================================================="

if [[ $FAIL -ne 0 ]]; then
    echo "[TEST] SOME TESTS FAILED ✗"
    exit 1
fi

echo "[TEST] ALL TESTS PASSED ✓"
exit 0
