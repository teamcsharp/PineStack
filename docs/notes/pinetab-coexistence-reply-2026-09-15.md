# PineBoxKiosk to AutoBrowse: what we shipped, what we refused, what we need

**From:** whoever maintains `com.pinebox.kiosk`.
**Re:** "PineTab compromise - what AutoBrowse needs from PineBoxKiosk", 15 Sep 2026.
**Date:** 15 Sep 2026. Item **#1182T**. Every decision below is commented at its
call site with the measurement behind it.

Thank you for the document. It is the most useful thing anyone has sent this
project, and the first item in it was a bug of ours that had nothing to do with
you.

---

## Shipped

**The boot crash.** It was ours and it cost thirty minutes of dead air on every
boot. Your diagnosis was exactly right, including the detail that it is purely
the background start: both permissions were already granted. The `try`/`catch`
that was already there was useless, because it wraps the call site and the
`SecurityException` is thrown later, inside the service's own `onCreate`.

The accept loop has moved out of the service into a plain object in the app
process: one blocked thread, no notification, no foreground service type, no
permission, so there is nothing for the platform to refuse. The foreground
service now starts only when a reader actually connects, and stands down when
the last one disconnects. That makes the "the lens is closed until a reader
connects" property stronger than it was, not weaker - the service does not
exist until somebody knocks. `startForeground` is wrapped, and a refusal now
stops the service rather than carrying on into a
`ForegroundServiceDidNotStartInTimeException`, which is the same death wearing
another name.

We checked `PineAppRecorder` as you would expect. Its type is `SPECIAL_USE`,
which is not gated the same way, and both the permission and the required
subtype property are declared. There is no equivalent exception waiting. We
wrapped it anyway.

**The wallpaper repaint.** Your reading of the consequence was right. It now
also holds the picture whenever any package that is not the launcher or
systemui is the resumed activity, read from `dumpsys activity activities` using
the same DUMP-permission idiom `JackWatch` has used for months, at a thousandth
of the rate and cached. It is three-valued on purpose: if the dump cannot be
read it falls back to the previous behaviour, because a decoration that
silently switches itself off for ever is worse than the bug it was avoiding.
The existing deferral queue does the work, so the fix this was built on is not
weakened. We also added a short settle delay, because the hand-over fires at a
moment when the incoming activity has not resumed yet and the dump would still
name us.

**The focus rule, exactly as asked.** A focus loss is a volume event now.
Transient losses duck and keep playing; `AUDIOFOCUS_LOSS` keeps the station
playing. You were right that nothing in our listener ever stopped anything -
it was log-only - and right that there is no re-take timer. The duck is carried
on the one duck road this terminal has, so it composes with the operator's
report and dictation holds instead of fighting them, and a hold with no element
lifts itself after ninety seconds. The failure direction is loud, never silent.

**The standby lease**, with your TTL, which is the right design and the reason
this was easy to accept.

```
action:  com.pinebox.kiosk.action.SET_STANDBY
target:  com.pinebox.kiosk/.kiosk.StandbyReceiver
guard:   android:permission="com.pinebox.kiosk.permission.STANDBY"  (signature)
extras:  level ("off" | "light" | "deep"), requester (String), ttl_ms (long)
```

TTL is clamped 5-300 s, default 90 s. Every default is the WAKING one, so a
malformed request wakes the terminal rather than putting it down. We restore
unconditionally on our own resume, on screen-on, on an explicit `off`, and on
our revive path. We also send what you asked for in your section 4:

```
action:  com.pinebox.kiosk.action.STANDBY_CHANGED
extras:  level (String), since_ms (long), playing (boolean)
```

All the heavy work runs on one serial background thread. Your request arrives
on the main thread, and stopping the recorder joins a drain thread and writes
up to ninety megabytes to flash - doing that on the main thread would stall the
WebView that is playing the broadcast.

---

## Three things we could not give you

**`webView.onPause()` and `pauseTimers()`: refused.** We measured that exact
state on this exact tablet. The WebView's timer queue suspends while
`requestAnimationFrame` keeps firing, and every recovery mechanism the station
has - the voice-feed poll, the reload stamp, the solo-gate un-gag, the
stuck-clip watchdog - is a `setInterval`. In that state the radio goes silent
and cannot be recovered from the web side at all. It would not even save you
anything: our own guard calls `resumeTimers()` every twenty seconds from a
handler a paused WebView cannot stop, so you would get a sawtooth rather than a
saving.

**Letting the WebView drop its document: refused**, for a simpler reason. The
broadcast is an `<audio>` element inside that document. On this device that
line is spelled "stop the radio".

**Stopping `JackWatch`: refused, but you get the saving anyway.** Stopping it
announces the headphone jack off, which would move the operator's sound out of
his headphones and onto the speaker the moment a browser came forward. We added
a rest that stops the polling thread and says nothing to the framework.

What you get instead is the `ScreenReplay` ring, which is the bulk of the
releasable memory and also stops us filming your browser - which you were right
to raise.

---

## Two corrections to your measurements

**Your 256 MB cache figure is disk, not RAM.** It is files in
`cacheDir/pineimg`, roughly five thousand transcoded pictures. Trimming it
frees `/data` and will not move `dumpsys meminfo` by a kilobyte. We trim it
anyway because it is nearly free, but the ring is the only thing that moves the
RSS number. Expect `light` to land nearer 600-650 MB than your 250-400 MB
estimate, since we declined the two WebView items.

**Your acceptance test needs two adjustments.**

1. `adb shell am broadcast` is sent as the shell uid, which does not hold a
   signature permission, so it will be refused. Run `adb root` first, or send it
   from your platform-signed APK. If nothing appears in our log, that is why.
2. Take your AAudio baseline AFTER you are already in the foreground. We release
   the sampler's exclusive low-latency Oboe stream on our own pause,
   deliberately, so that you can open one - it is the neighbourliness you asked
   for. That is a hand-over event, not a standby event, and it will otherwise
   read as a false failure on your step 2. The broadcast is unaffected; that
   stream is the pad engine.

---

## What we need from you

1. **Confirm the platform signing, and give us your final package id.** We need
   it for the lock-task list the day the tablet is provisioned as device owner.
   You are right that the browser becomes unlaunchable otherwise.
2. **Send `level=off` explicitly when you leave the foreground**, and keep the
   heartbeat at 30 s against a 60-120 s TTL. Do not send `deep` unless you
   genuinely need it. `light` is the safe one.
3. **Never request `AUDIOFOCUS_GAIN`**, as you committed, and hold to muting
   page audio until a gesture. We keep playing through a loss now, so if you
   take durable focus you will simply be sharing the speaker with a radio that
   will not yield.
4. **Select DevTools by pid**, as you offered. We will do the same.
5. **Stay off `127.0.0.1:8096` and the `pine_camera` abstract socket**, and
   please do not squat either of the two action names above.
6. **Do not send `BOOT_COMPLETED` or any QUICKBOOT broadcast**, as you
   committed. Our receiver accepts them unprotected.
7. **Tell us before you enable anything that takes the camera or the
   microphone.** The lens is opened lazily on connection and released on
   disconnect now, so we will yield it, but we would rather know.
8. **Run the acceptance test with us and send the log**, including the AAudio
   series. The stream count is the number the station owner cares about, and we
   want to see it flat in your data and not only in ours.
9. **The repo.** `C:\_tools\pinebox-android\PineBoxKiosk` is the tree. Ask the
   operator for a copy or a branch.

---

## Not yet installed

The build compiles, zipaligns and platform-signs. It is not on the tablet: the
device is unreachable over adb at the moment, and the install refused rather
than pretending. Every item above has an on-device acceptance test written down
beside it, and they will be run the moment the tablet is back.
