# Troubleshoot station

Use **Troubleshoot station** in the panel menu, the warning icon, or the
station troubleshooting console. One click starts a saved check and shows its
findings and actions. Repeated clicks join the current check. Existing manual
troubleshooting steps remain available.

The check covers dialogue preparation, its recording and delivery queues, and
the services implicated by the diagnosis. It admits existing uncommitted drafts
to the recovery queue and wakes its supervised worker. When there is no draft
or ready dialogue, it requests a fresh banked round through the existing owner.
The panel also tries the current speech player's audio unlock within the click
gesture, while preserving intentional pauses, muted players and music routing.

Rejected dialogue follows the selected policy: repair failed turns, rewrite,
reroll instructions, then rebuild. Each pass makes three distinct attempts;
failed passes cool down for 60 seconds before returning to the roulette with
fresh variations and higher priority. Two matching rejections mark an approach
stuck. Due recovery work alternates with other runnable work. Rhyme, optional
length targets and decorative style relax progressively. The original speakers,
protected exact wording, grounded facts and caller/news premises remain binding.

New writing must pass speaker order, complete-plan, copy, direction and ordinary
source/profile review. Missing or rejected required conclusions must land the
exchange. Failed candidates leave the original plan intact; only retry accounting
persists. Changed approved words invalidate old audio before recording. Committed
ledger lines and dialogue already in flight cannot be rewritten.

Required handoff recovery continues when optional tint's hourly allowance is
spent. Operator interjections and model admission still take priority. A cooldown
does not issue model commands or extend itself just because it was polled; model
admission deferrals do not spend a creative attempt.

Whole-exchange requests use the model's structured-dialogue contract so speaker
labels and line breaks survive the normal model adapter. Both handoff and
recovery requests retain admission waits as deferrals, rather than treating an
unavailable writer's empty answer as a creative rejection. When an old gate
receipt refers to a removed turn, a rewrite, reroll or rebuild retains that
row as unassigned source evidence. It never guesses a new owner for those
words; surviving identities remain checked for speaker, order and uniqueness.
An exact-copy turn without identifiable wording still requires attention.

The restart option defaults on. The diagnosis selects affected services rather
than reloading every voice engine. Recording prevents destructive restarts, and
station restarts retain the existing restart interval. A repair's checkpoint must
reach disk before a restart is allowed. Checkpoint writes run off the audio loop;
an unavailable disk holds the restart and appears in the report. Saved checks
resume after startup restores station state.

The report distinguishes requested repairs, ready dialogue and verified playback.
Success requires a new dialogue playback receipt after the check began. Music
playing or text waiting in a queue cannot produce a success report. If the check
ends while work remains, it shows pending work, reasons and the next cooldown;
the durable station worker continues eligible attempts. A switched-off or paused
station, unreachable hardware and missing listener evidence are reported honestly.

The panel uses authenticated `POST /api/station/troubleshoot` and
`GET /api/station/troubleshoot/{job_id}`. Repair reports live in station data,
separately from playable inventory. The implementation is in
`station_troubleshoot.py`, `station_troubleshoot_runtime.py`, `dialogue_recovery.py`
and `dialogue_repair.py`; the existing station owners still perform production,
rendering and playback.
