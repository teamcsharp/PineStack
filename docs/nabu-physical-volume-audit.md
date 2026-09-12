# Physical Nabu volume around deployment

A read-only, consistent Home Assistant recorder transaction examined 50 media-player state rows. The physical master reached 30% at **1788811172.548**, about **264 seconds before** the backend restart at 1788811437. The earlier 60% observation therefore cannot serve as the immediate predeployment baseline.

The recorder shows 70% then 75% at 1788810058, followed by 65%, 50%, 45%, 35%, and 30% across 0.828 seconds at 1788811171–1172. Those changes have no Home Assistant user or parent context. This is consistent with device-side dial changes, but does not identify a person or establish the cause conclusively. The value remained 30% through the final snapshot at 1788811725.596.

There were 14 retained `call_service` events in the inspected window from 1788811100, and no retained `media_player.volume_set` event. Recorder retention is not a complete service-call audit, so absence alone is not proof that a call never occurred.

Source review found two volume setters. The music startup path returns through Nabu's encoded digital-audio dispatch before reaching the automatic setter. The other setter requires an explicit operator argument and its current settings caller bypasses it for Nabu. No unconditional 30% initialization or Nabu startup setter was found.

The evidence establishes that deployment preserved an already-existing 30% setting; it does not show a startup volume reset. This investigation sent no volume or playback commands. Aggregate timestamps and context-presence evidence are saved in `docs/nabu-physical-volume-audit.json`.
