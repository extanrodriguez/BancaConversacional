#!/usr/bin/env bash
# Monitor peticiones al puerto 8447 (Genesis QA)
set -eu

LOG_DIR="/tmp/genesis-8447-watch"
mkdir -p "$LOG_DIR"

echo "=== $(date -Is) watch_8447 ==="
echo "Puerto 8447:"
ss -tlnp | grep 8447 || true

pkill -f 'tcpdump -i any port 8447' 2>/dev/null || true
pkill -f 'journalctl -u genesis-cognitive-8447 -f' 2>/dev/null || true
sleep 1

nohup journalctl -u genesis-cognitive-8447 -f -n 0 --no-pager \
  >> "$LOG_DIR/journal.log" 2>&1 &
echo "journalctl PID=$! -> $LOG_DIR/journal.log"

if command -v tcpdump >/dev/null 2>&1; then
  nohup tcpdump -i any port 8447 -n -l \
    >> "$LOG_DIR/tcpdump.log" 2>&1 &
  echo "tcpdump PID=$! -> $LOG_DIR/tcpdump.log"
else
  echo "tcpdump no disponible (solo journal)"
fi

echo "Monitor activo. Ver en vivo:"
echo "  tail -f $LOG_DIR/journal.log"
echo "  tail -f $LOG_DIR/tcpdump.log"
