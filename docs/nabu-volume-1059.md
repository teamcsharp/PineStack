# Nabu physical volume ownership — inbox #1059

The later [independent stream controls](nabu-independent-mix-2026-09-07.md)
supersede this document's explicit Music-slider exception. Nabu's Music slider
now adjusts the music audio itself and sends no shared-volume command.
The investigation below records the earlier implementation and measurements.

The physical Nabu dial is authoritative. Automatic playback, a new track,
startup, reconnection and replay cannot reapply the application's stored level,
even if an older configuration enabled “Keep the record level applied on the
box.” Selecting or restoring Nabu disables that old opt-in without sending any
volume command. The desktop control is disabled for Nabu and explains why.

The backend's two Home Assistant `volume_set` sites were traced. The automatic
music path now rejects Nabu by both selected device and actual entity. The
one-shot `box_level_send` path requires an explicit operator flag; only a
deliberate authenticated Music slider request supplies it. System routing
restores ignore saved `music_level` payloads. Deliberate volume controls still
send exactly the requested adjustment once.

Voice announcements use `play_media` with `announce=true` and no volume or
restore fields. The installed Home Assistant ESPHome integration's
`async_play_media` forwards the media URL and announcement flag without writing
the device volume. Its `async_set_volume_level` is a separate command. No
`volume_set` references were found in the installed Home Assistant
`automations.yaml` or `scripts.yaml`. Browser music ducking changes local audio
gain and does not issue a Home Assistant volume command.

Read-only inspection before deployment found the Nabu unmuted at 84%, while the
application retained a 64% music level and `box_volume_control=true`. That stale
opt-in could previously apply 64% after the application's in-memory “already
sent” cache reset. No live volume adjustment, audio test or device restart was
performed for this request.

After backend deployment, read-only Home Assistant state still reported 84%
and unmuted. The saved automatic-control setting was false; the unused stored
64% level remained intact. The pipeline contained no volume-reset events.
The updated renderer is installed in the persistent local desktop runner and
was activated through the normal Start-menu shortcut during a measured speech
gap. Its source hash matches the shared renderer, and both saved route-file
hashes remained unchanged through the relaunch. The disabled Nabu checkbox's
desktop regression passed independently. The backend protection also applies
to already-open older controls.

Seven backend regressions exercise repeated playback across cache resets,
announcement replay, stale route metadata, startup migration, old checkbox
requests, system routing restoration and deliberate one-shot user adjustment.
The desktop regression verifies that the Nabu control cannot re-enable automatic
resets while other speakers retain their explicit opt-in.
