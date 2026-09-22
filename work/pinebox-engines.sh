#!/usr/bin/env bash
# Pine Box engine watchdog.
#
# 2026-09-15 (#1209): ONE ENGINE AT A TIME, AND THE SWITCH SAYS WHICH.
#
# The operator: "F5 shouldnt even be up right now because I am using XTTS. I
# need to make sure that I am using only one of them at a time and that F5 is
# completely closed", and "i want to switch back and forth between them but
# never at the same time".
#
# WHAT THIS FILE USED TO DO, and why F5 would not stay closed. The loop read
#
#     for spec in "8770:xtts" "8772:f5"; do
#
# which is a standing instruction that BOTH engines must always be answering.
# Kill F5 by hand and this script notices within ninety seconds, calls it
# wedged, and deploys it again. Measured on 2026-09-15: eighteen kill-and-
# redeploy cycles in one hour, and F5 was 37 seconds old when the operator
# asked why it was up at all. No amount of killing it by hand could ever have
# worked while this loop was the thing being obeyed.
#
# WHAT IT DOES NOW. One switch file holds one word - the engine that is wanted:
#
#     data/voice_engine/mode  ->  "xtts" or "f5"
#
# The wanted engine is supervised exactly as before: probed, given three
# chances, then reclaimed and redeployed. The OTHER engine is stopped, every
# tick, for as long as it is not the one named. Switching is one word written
# to one file; the change is picked up on the next tick, within thirty seconds,
# with nothing to restart. That is the same shape as every other switch on this
# station, so it is read and written the same way.
#
# The default when the file is missing or unreadable is xtts, which is what the
# operator was using when he asked. A switch that cannot be read must still
# leave the station with a voice.
#
# TWO OTHER THINGS FIXED HERE, both found in the same audit:
#
#   The relaunch used `> ~/voice-director/logs/f5.log`, which truncates. Every
#   redeploy destroyed the log of the run that had just failed, so the reason
#   an engine stopped answering could never be read - the file only ever held
#   the run that replaced it. It appends now.
#
#   The cure ran `echo 3 > /proc/sys/vm/drop_caches`, which discards the page
#   cache for the WHOLE MACHINE, on a box whose music library is mounted over
#   CIFS. That is far too broad a hammer for one engine missing a health probe,
#   and pinebox-uma already owns cache reclaim and gates it on a floor. Gone.
set -uo pipefail
STATE=/run/pinebox-engines
mkdir -p "$STATE"

SWITCH=/home/ehm_eckx/pinevoice-stack/spark-agent/data/voice_engine/mode

# Strict one-token read, the way every switch on this station is read: the
# first word of the first line, lowercased, and nothing else. Anything that is
# not a name we know is not a vote for the other engine - it is a broken
# switch, and a broken switch keeps the default rather than silently swapping
# the station's voice.
want_engine() {
  local raw
  raw=$(head -c 64 "$SWITCH" 2>/dev/null | tr -d '\r' | awk '{print tolower($1); exit}')
  case "$raw" in
    xtts|f5) printf '%s' "$raw" ;;
    *)       printf 'xtts' ;;
  esac
}

probe() { curl -fsS --max-time 6 "http://127.0.0.1:$1/health" 2>/dev/null | grep -q '"ready"'; }
director_up() { curl -fsS --max-time 5 http://127.0.0.1:8090/host/pressure >/dev/null 2>&1; }

revive_director() {
  director_up && return 0
  logger -t pinebox-engines "voice-director is dark - restarting it"
  systemctl restart voice-director || true
  for _ in $(seq 1 12); do
    sleep 5
    director_up && { logger -t pinebox-engines "voice-director is back"; return 0; }
  done
  logger -t pinebox-engines "voice-director will not come back"
  return 1
}

# Stop an engine that is not wanted. The director's own road first, because it
# knows what it deployed and can take it down tidily; pkill only if the
# director is dark or refuses. Silence when there was nothing to stop - this
# runs every thirty seconds and must not fill the journal with news that the
# closed engine is still closed.
stop_engine() {
  local name="$1" port="$2" pat="$3"
  if ! probe "$port" && ! pgrep -f "$pat" >/dev/null 2>&1; then
    return 0                       # already closed, say nothing
  fi
  logger -t pinebox-engines "$name is not the chosen engine - closing it"
  if director_up; then
    curl -fsS --max-time 20 -X POST \
      "http://127.0.0.1:8090/director/engine/$name/terminate" >/dev/null 2>&1 \
      && logger -t pinebox-engines "$name terminated by the director"
    sleep 2
  fi
  if pgrep -f "$pat" >/dev/null 2>&1; then
    pkill -9 -f "$pat" || true
    logger -t pinebox-engines "$name stopped"
  fi
  rm -f "$STATE/$name.fail"
}

WANT=$(want_engine)

case "$WANT" in
  xtts) KEEP_PORT=8770; KEEP_PAT=voice_clone_server
        stop_engine f5 8772 f5_tts_server ;;
  f5)   KEEP_PORT=8772; KEEP_PAT=f5_tts_server
        stop_engine xtts 8770 voice_clone_server ;;
esac

# From here down this is the watchdog as it always was, narrowed to the one
# engine the switch named.
name="$WANT"; port="$KEEP_PORT"
if probe "$port"; then
  rm -f "$STATE/$name.fail"
  exit 0
fi

fails=$(( $(cat "$STATE/$name.fail" 2>/dev/null || echo 0) + 1 ))
echo "$fails" > "$STATE/$name.fail"
logger -t pinebox-engines "$name :$port not answering ($fails/3)"
[ "$fails" -lt 3 ] && exit 0

logger -t pinebox-engines "$name wedged - redeploying"
pkill -9 -f "$KEEP_PAT" || true
sleep 2

if revive_director; then
  curl -fsS --max-time 40 -X POST \
    "http://127.0.0.1:8090/director/engine/$name/deploy" >/dev/null 2>&1 \
    && logger -t pinebox-engines "$name deploy requested" \
    || logger -t pinebox-engines "$name deploy refused by the director"
else
  # The director is the usual way in, not the only way. Launch the
  # engine from its own launcher so a dead director never costs the
  # station its voices.
  logger -t pinebox-engines "launching $name directly (no director)"
  if [ "$name" = xtts ]; then
    su - ehm_eckx -c "cd ~/reachy-gateway && HF_HUB_DISABLE_XET=1 setsid ~/.local/bin/uv run --index https://download.pytorch.org/whl/cu130 --index-strategy unsafe-best-match --with coqui-tts==0.27.5 --with 'transformers>=4.57,<5' --with torch --with torchaudio --with torchcodec --with spacy python voice_clone_server.py --port 8770 --preload >> ~/voice-director/logs/xtts.log 2>&1 < /dev/null &" || true
  else
    su - ehm_eckx -c "setsid ~/f5tts/.venv/bin/python ~/reachy-gateway/f5_tts_server.py --port 8772 --preload >> ~/voice-director/logs/f5.log 2>&1 < /dev/null &" || true
  fi
fi
rm -f "$STATE/$name.fail"
exit 0
