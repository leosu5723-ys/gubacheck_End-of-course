#!/bin/sh
# Collects forum posts within the site's limits: candidate spike days first,
# then continuous history for all stocks in turn. Whenever the site serves
# its identity check the collector stops (exit 2); this script waits 15
# minutes and resumes from where it stopped. It never bypasses the check.
cd "$(dirname "$0")/.." || exit 1
stage=days
for attempt in $(seq 1 200); do
  if [ "$stage" = days ]; then
    .venv/bin/python -u -m collectors.guba days && stage=backfill && continue
  else
    .venv/bin/python -u -m collectors.guba backfill 2025-10-01 && echo "COLLECTION COMPLETE" && exit 0
  fi
  echo "attempt $attempt ($stage) stopped at $(date '+%m-%d %H:%M'); waiting 15 min"
  sleep 900
done
