#!/bin/sh
# radicale-contact-dates daily sync wrapper.
#
# Generates/updates the read-only "*-auto-contact-dates" calendars from your
# CardDAV contacts (BDAY, ANNIVERSARY and Apple X-ABDATE/X-ABLABEL dates). The
# generator writes directly on the filesystem AS THE RADICALE STORAGE UID, so it
# bypasses Radicale's rights rules. Radicale's multifilesystem storage discovers
# filesystem changes live, so NO Radicale restart (and no container restart) is
# needed after a run.
#
# The values below are DEPLOYMENT-SPECIFIC — adjust them to your setup:
#   * <storage-uid>  : the uid:gid that owns Radicale's collection files
#                      (the user Radicale runs as inside the container).
#   * <container>    : the name of your Radicale Docker container.
#   * --config       : path to your config JSON inside the container.
#   * --root         : Radicale's multifilesystem collection root.
#
# Schedule it once a day, e.g. via cron:
#   0 3 * * * /path/to/run-contact-dates.sh
# or via Synology Task Scheduler (User-defined script, daily).
set -u

LOG="/var/log/run-contact-dates.log"
TS="$(date +%Y-%m-%dT%H:%M:%S)"

OUT="$(docker exec -e PYTHONDONTWRITEBYTECODE=1 -u <storage-uid> <container> \
  python3 /plugins/contact_dates.py \
  --config /plugins/contact-dates.config.json \
  --root /data/collections/collection-root 2>&1)"
RC=$?

printf "===== %s (exit %s) =====\n%s\n" "$TS" "$RC" "$OUT" | tee -a "$LOG"

# Keep the log bounded (last 500 lines).
tail -n 500 "$LOG" > "${LOG}.tmp" 2>/dev/null && mv "${LOG}.tmp" "$LOG" || true

exit "$RC"
