#!/data/data/com.termux/files/usr/bin/sh
# Usage: sh watch.sh [minutes]     (default 10)
# Holds the wake lock, runs check_grades.py in a loop. Stop with Ctrl+C.
cd "$(dirname "$0")" || exit 1
MINUTES=${1:-10}
INTERVAL=$((MINUTES * 60))

command -v termux-wake-lock >/dev/null && termux-wake-lock
trap 'kill $! 2>/dev/null; command -v termux-wake-unlock >/dev/null && termux-wake-unlock; echo; echo "stopped, wake lock released"; exit 0' INT TERM

echo "Checking every ${MINUTES} min. Ctrl+C to stop."
while true; do
  python check_grades.py 2>&1 | tee -a log.txt
  sleep "$INTERVAL" &
  wait $!
done
