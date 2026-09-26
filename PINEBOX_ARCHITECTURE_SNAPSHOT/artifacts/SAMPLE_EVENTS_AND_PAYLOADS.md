# Sample Events and Payloads

Values are reduced/sanitized live examples.

## Flow Event

```json
{
  "id": 1790458113961596,
  "at": 1790458113.9615989,
  "node": "pantry",
  "status": "ok",
  "summary": "Recorded take stored on the prepared shelf",
  "trace_id": "b60439e06687de7893abfd5a7f5fd85a9cecf413",
  "from": "tts",
  "details": {
    "keys_present": ["key", "text", "who", "voice", "kind", "clip"]
  }
}
```

## Playback Event

```json
{
  "node": "playing",
  "status": "playing",
  "summary": "listener-id: playing",
  "trace_id": "1c232a7c5e5f42d2",
  "from": "canplay",
  "details": {
    "keys_present": [
      "at", "event", "listener_id", "delivery_id", "volume",
      "audible_volume", "muted", "error", "current_time", "sequence", "started"
    ]
  }
}
```

## Lean Playout State

```json
{
  "available": true,
  "mode": "linear",
  "linear": true,
  "sounding": {
    "occurrence_id": "delivery:1c232a7c5e5f42d2",
    "route": "page",
    "lane": "interject",
    "producer": "_dj_speak_floorless:34241",
    "seconds": 27.7746,
    "position_basis": "listener",
    "acks": 7
  }
}
```

## Air Row Shape

```json
{
  "id": "line-id",
  "ts": 1790458536,
  "air_at": 1790458562.012,
  "who": "dj",
  "kind": "interject",
  "round": "gold",
  "text": "[spoken text omitted]",
  "aired": "stream",
  "heard_ack_by": "page",
  "voice": "xtts:voice-id",
  "engine": "xtts",
  "media": "media-id.wav",
  "seconds": 10.66
}
```

## System 2 Event Input Shape

From `system2_runtime.py:queue_event`:

```json
{
  "request_id": "idempotency-key",
  "kind": "call_in | station_event | guest | music_request | plotline",
  "air_at": 1790459000,
  "seconds": 90,
  "brief": "bounded operator brief",
  "priority": 0,
  "label": "optional label"
}
```

