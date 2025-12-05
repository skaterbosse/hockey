#!/usr/bin/env bash
set -euo pipefail

TEST_FILE_DEFAULT="tests/test_cases.txt"
TEST_FILE="$TEST_FILE_DEFAULT"
TMP_FILTERED=""

# Om du anger argument → filtrera på case-id eller namn
if [ "$#" -gt 0 ]; then
  TMP_FILTERED="tests/test_cases.filtered.$$"
  > "$TMP_FILTERED"

  # Bygg ett awk-skript som matchar på kolumn 1 (id) eller kolumn 2 (namn)
  awk -F';' -v ARGS="$*" '
    BEGIN {
      n = split(ARGS, a, " ");
      for (i = 1; i <= n; i++) wanted[a[i]] = 1;
    }
    {
      id = $1;
      name = $2;
      for (w in wanted) {
        if (id == w || name == w) {
          print $0;
          break;
        }
      }
    }
  ' "$TEST_FILE_DEFAULT" > "$TMP_FILTERED"

  TEST_FILE="$TMP_FILTERED"
fi

echo "==================================================================="
echo " getGames.py offline test runner"
echo " Date      : $(date '+%Y-%m-%d %H:%M:%S')"
echo " Test file : $TEST_FILE"
if [ "$TEST_FILE" != "$TEST_FILE_DEFAULT" ]; then
  echo " Filter    : $*"
fi
echo "==================================================================="

# Kör Python-test-runnern i getGames.py
set +e
python3 scripts/getGames.py -tf "$TEST_FILE" -td "tests/html"
RC=$?
set -e

echo "-------------------------------------------------------------------"
if [ "$RC" -eq 0 ]; then
  echo "SUMMARY : ALL TESTS PASSED ✓"
else
  echo "SUMMARY : SOME TESTS FAILED ✗ (exit code $RC)"
fi
echo "-------------------------------------------------------------------"

# Städning
if [ -n "$TMP_FILTERED" ] && [ -f "$TMP_FILTERED" ]; then
  rm -f "$TMP_FILTERED"
fi

exit "$RC"

