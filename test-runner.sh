#!/usr/bin/env bash
set -euo pipefail

#
# --- Argumenthantering ---
#

TEST_FILE="tests/test_cases.txt"
FILTER=""

# Om inga argument → kör standardfil utan filter
if [[ $# -gt 0 ]]; then
    # Om första argumentet är -tf
    if [[ "$1" == "-tf" ]]; then
        if [[ $# -lt 2 ]]; then
            echo "ERROR: -tf requires a filename"
            exit 1
        fi
        TEST_FILE="$2"
        shift 2
    fi

    # Om det nu finns ytterligare argument → det är filter-ID
    if [[ $# -gt 0 ]]; then
        FILTER="$1"
    fi
fi


#
# --- Filtrering ---
#
TMP_FILTERED=""
if [[ -n "$FILTER" ]]; then
    TMP_FILTERED="tests/test_cases.filtered.$$"
    grep "^${FILTER};" "$TEST_FILE" > "$TMP_FILTERED" || true
    TEST_FILE="$TMP_FILTERED"
fi


#
# --- Header ---
#
echo "==================================================================="
echo " getGames.py offline test runner"
echo " Date      : $(date '+%Y-%m-%d %H:%M:%S')"
echo " Test file : $TEST_FILE"
echo " Filter    : ${FILTER:-<none>}"
echo "==================================================================="


#
# --- Testkontainers ---
#
IDS=()
NAMES=()
RESULTS=()

PASS_COUNT=0
FAIL_COUNT=0
ERROR_COUNT=0
TOTAL=0


#
# --- Kör testfallen rad för rad ---
#

# Läs testfilen radvis (skip kommentarer och tomma rader automatiskt)
while IFS=';' read -r id name mode sd ed admin_host opts expected; do
    # Hoppa över rader som saknar ID (tom rad / kommentar)
    if [[ -z "${id// }" ]]; then
        continue
    fi

    TOTAL=$((TOTAL+1))
    IDS+=("$id")
    NAMES+=("$name")

    echo ""
    echo "[TEST] === CASE $id : $name ($mode) ==="

    CMD="python3 scripts/getGames.py -tf $TEST_FILE"

    set +e
    OUTPUT=$($CMD 2>&1)
    EXIT_CODE=$?
    set -e

    echo "$OUTPUT"

    if [[ $EXIT_CODE -eq 0 ]]; then
        RESULTS+=("PASS")
        PASS_COUNT=$((PASS_COUNT+1))
    elif grep -q "FAIL" <<< "$OUTPUT"; then
        RESULTS+=("FAIL")
        FAIL_COUNT=$((FAIL_COUNT+1))
    else
        RESULTS+=("ERROR")
        ERROR_COUNT=$((ERROR_COUNT+1))
    fi

done < "$TEST_FILE"


#
# --- Summering ---
#

echo ""
echo "[TEST] ================================================================"
echo "[TEST] SUMMARY OF ALL TEST CASES"
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
    EXIT=0
else
    echo "[TEST] SOME TESTS FAILED ✗"
    EXIT=1
fi

echo "[TEST] ================================================================"


#
# --- Städa ---
#
if [[ -n "${TMP_FILTERED}" ]]; then
    rm -f "$TMP_FILTERED"
fi

exit $EXIT

