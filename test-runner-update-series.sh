#!/usr/bin/env bash
set -euo pipefail

TEST_FILE="tests/test_cases_update_series.txt"
FILTER="${1:-}"

echo "==================================================================="
echo " updateLightSeriesResults.py test runner"
echo " Date      : $(date '+%Y-%m-%d %H:%M:%S')"
echo " Test file : $TEST_FILE"
echo " Filter    : ${FILTER:-<none>}"
echo "==================================================================="

TOTAL=0
PASS_COUNT=0
FAIL_COUNT=0
ERROR_COUNT=0

# Arrays for storing results
IDS=()
NAMES=()
RESULTS=()

# Helper to store result
store_result() {
    local id="$1"
    local name="$2"
    local result="$3"

    IDS+=("$id")
    NAMES+=("$name")
    RESULTS+=("$result")
}

while IFS=';' read -r id name mode series_id version rest1 rest2 rest3; do
    [[ -z "$id" || "$id" = "#"* ]] && continue

    if [[ -n "$FILTER" && "$FILTER" != "$id" ]]; then
        continue
    fi

    TOTAL=$((TOTAL + 1))

    if [[ "$mode" != "live-update" ]]; then
        echo "[TEST] ERROR: Unknown mode '$mode' for case $id"
        store_result "$id" "$name" "ERROR"
        ERROR_COUNT=$((ERROR_COUNT + 1))
        continue
    fi

    echo ""
    echo "[TEST] === CASE $id : $name (live-update) ==="

    INPUT_FILE=$(echo "$rest1" | sed 's/input=//')
    HTML_FILE=$(echo "$rest2" | sed 's/series_html=//')
    EXPECTED_FILE=$(echo "$rest3" | sed 's/expected=//')

    INPUT_PATH="tests/input/$INPUT_FILE"
    HTML_PATH="tests/html/$HTML_FILE"
    EXPECTED_PATH="tests/expected/$EXPECTED_FILE"
    TMP_OUT="tests/tmp/${name}_output.csv"

    # Validate files exist
    if [[ ! -f "$INPUT_PATH" ]]; then
        echo "[TEST] ERROR: Missing input file $INPUT_PATH"
        store_result "$id" "$name" "ERROR"
        ERROR_COUNT=$((ERROR_COUNT + 1))
        continue
    fi
    if [[ ! -f "$HTML_PATH" ]]; then
        echo "[TEST] ERROR: Missing HTML file $HTML_PATH"
        store_result "$id" "$name" "ERROR"
        ERROR_COUNT=$((ERROR_COUNT + 1))
        continue
    fi
    if [[ ! -f "$EXPECTED_PATH" ]]; then
        echo "[TEST] ERROR: Missing expected file $EXPECTED_PATH"
        store_result "$id" "$name" "ERROR"
        ERROR_COUNT=$((ERROR_COUNT + 1))
        continue
    fi

    # Run script
    set +e
    python3 scripts/updateLightSeriesResults.py \
        -i "$INPUT_PATH" \
        -o "$TMP_OUT" \
        --html-file "$HTML_PATH" \
        --series-id "$series_id" \
        2>&1 | tee "tests/tmp/${name}_run.log"
    EXIT_CODE=$?
    set -e

    if [[ $EXIT_CODE -ne 0 ]]; then
        echo "[TEST] ERROR: Script returned exit code $EXIT_CODE"
        store_result "$id" "$name" "ERROR"
        ERROR_COUNT=$((ERROR_COUNT + 1))
        continue
    fi

    # Normalize comparison
    EXPECTED_SORTED=$(sed 's/\r$//' "$EXPECTED_PATH" | sort)
    OUT_SORTED=$(sed 's/\r$//' "$TMP_OUT" | sort)

    if [[ "$EXPECTED_SORTED" == "$OUT_SORTED" ]]; then
        echo "[TEST] PASS ✓ $name"
        store_result "$id" "$name" "PASS"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo "[TEST] FAIL ✗ $name"
        store_result "$id" "$name" "FAIL"
        FAIL_COUNT=$((FAIL_COUNT + 1))

        echo "---- DIFF ----"
        diff <(echo "$EXPECTED_SORTED") <(echo "$OUT_SORTED") || true
        echo "--------------"
    fi

done < "$TEST_FILE"

echo ""
echo "[TEST] ================================================================"
echo "[TEST] SUMMARY OF ALL LIVE-UPDATE TEST CASES"
printf "%-4s %-40s %-10s\n" "ID" "NAME" "RESULT"
echo "-----------------------------------------------------------------------"

for i in "${!IDS[@]}"; do
    printf "%-4s %-40s %-10s\n" "${IDS[$i]}" "${NAMES[$i]}" "${RESULTS[$i]}"
done

echo "-----------------------------------------------------------------------"
echo "TOTAL: $TOTAL tests"
echo "PASS : $PASS_COUNT"
echo "FAIL : $FAIL_COUNT"
echo "ERROR: $ERROR_COUNT"
echo "-----------------------------------------------------------------------"

if [[ $FAIL_COUNT -eq 0 && $ERROR_COUNT -eq 0 ]]; then
    echo "[TEST] ALL TESTS PASSED ✓"
    exit 0
else
    echo "[TEST] SOME TESTS FAILED ✗"
    exit 1
fi

