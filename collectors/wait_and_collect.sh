#!/bin/sh
# Waits for the forum's identity check to clear, then collects candidate-day
# posts. If the check reappears the collector stops (exit 2); this script
# waits 15 minutes and resumes. Already-collected days are skipped.
cd "$(dirname "$0")/.." || exit 1
for attempt in $(seq 1 24); do
  .venv/bin/python -u -m collectors.guba days
  code=$?
  [ $code -eq 0 ] && echo "COLLECTION COMPLETE" && exit 0
  echo "attempt $attempt stopped (exit $code) at $(date '+%H:%M'); waiting 15 min"
  sleep 900
done
echo "GAVE UP after 24 attempts"; exit 1
