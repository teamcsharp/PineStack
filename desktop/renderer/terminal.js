/* The Terminal panel - turning a stock tablet into a Pine Box kiosk.
 *
 * This screen deliberately reads as a checklist of REFUSALS. Every gate the
 * tested modules enforce is shown here in the same words, so the operator
 * can see what is standing in the way before pressing anything, rather than
 * discovering it from a failure.
 *
 * The unlock control is the only destructive thing in the whole desktop. It
 * makes you type the confirmation out, it stays disabled until a verified
 * restore image exists, and the main process checks all of that again
 * regardless of what this page believes.
 */
(function (root) {
  "use strict";

  const api = () => root.pineDesktop;
  const CONFIRM = "ERASE THIS TABLET";

  let host = null;
  let last = null;
  let busy = false;

  const el = (id) => document.getElementById(id);

  function say(text, bad) {
    const line = el("tmNote");
    if (!line) return;
    line.textContent = text || "";
    line.classList.toggle("bad", !!bad);
  }

  function chip(label, value, tone) {
    const box = document.createElement("div");
    box.className = "tm-chip" + (tone ? " " + tone : "");
    const name = document.createElement("span");
    name.textContent = label;
    const body = document.createElement("b");
    body.textContent = value == null || value === "" ? "—" : String(value);
    box.appendChild(name);
    box.appendChild(body);
    return box;
  }

  /* Blockers stop the flow; warnings are things to know. They are never
   * merged, because "you cannot proceed" and "mind this" are different
   * messages and blurring them is how an operator learns to ignore both. */
  function paintVerdict(target, verdict) {
    const box = el(target);
    if (!box) return;
    box.replaceChildren();
    if (!verdict) return;
    for (const text of verdict.blockers || []) {
      const line = document.createElement("p");
      line.className = "tm-blocker";
      line.textContent = text;
      box.appendChild(line);
    }
    for (const text of verdict.warnings || []) {
      const line = document.createElement("p");
      line.className = "tm-warning";
      line.textContent = text;
      box.appendChild(line);
    }
  }

  function paint(survey) {
    last = survey;
    const tools = survey.tools || {};
    el("tmTools").textContent = tools.found
      ? "adb: " + tools.adb
      : tools.onPath
        ? "adb: looking on PATH (not found where expected)"
        : "adb: not found";
    el("tmTools").classList.toggle("bad", !tools.found);

    /* The Android toolchain is separate from adb and reported separately -
     * having one says nothing about the other. */
    if (api().terminalToolchain) {
      api().terminalToolchain().then((tc) => {
        const box = el("tmAppState");
        if (!box || box.textContent) return;
        box.textContent = tc && tc.ok ? "toolchain ready" : "no toolchain";
        box.className = "tm-state " + (tc && tc.ok ? "good" : "bad");
      }).catch(() => {});
    }

    const facts = el("tmFacts");
    facts.replaceChildren();
    const device = survey.device || {};
    const identity = device.identity || {};

    if (!device.found) {
      facts.appendChild(chip("tablet", "none connected", "bad"));
    } else if (!device.authorized) {
      facts.appendChild(chip("tablet", device.serial || "connected", "warn"));
      facts.appendChild(chip("state", device.state || "unauthorized", "warn"));
    } else {
      facts.appendChild(chip("serial", identity.serial || device.serial, "good"));
      facts.appendChild(chip("model", identity.model));
      facts.appendChild(chip("android", identity.android
        ? identity.android + " (sdk " + identity.sdk + ")" : ""));
      facts.appendChild(chip("bootloader", identity.bootloader,
        identity.bootloader === "unlocked" ? "warn" : "good"));
      facts.appendChild(chip("OEM unlock", identity.oemUnlock,
        identity.oemUnlock === "allowed" ? "good" : "bad"));
      facts.appendChild(chip("battery",
        typeof survey.device.battery === "number" ? survey.device.battery + "%" : "",
        survey.device.battery >= 50 ? "good" : "bad"));
    }

    const need = survey.requirement;
    if (need) {
      facts.appendChild(chip("needs", [
        need.arch,
        need.ab ? "A/B" : "A-only",
        need.vndklite ? "vndklite" : "full vndk",
        need.platform
      ].filter(Boolean).join(" · ")));
    }

    paintVerdict("tmVerdict", survey.verdict);

    /* The restore image. Until this is green, unlocking stays refused. */
    const fw = survey.firmware;
    el("tmFwState").textContent = !fw
      ? "no folder set"
      : fw.verdict.ok
        ? "verified — " + (fw.report.images || []).length + " images"
        : "not a restore image";
    el("tmFwState").className = "tm-state " + (!fw ? "" : fw.verdict.ok ? "good" : "bad");
    paintVerdict("tmFwVerdict", fw ? fw.verdict : null);

    const image = survey.gsi;
    el("tmGsiState").textContent = !image
      ? "no image set"
      : image.verdict && image.verdict.ok
        ? "matches this tablet"
        : image.image && !image.image.exists
          ? "not downloaded"
          : "does not match";
    el("tmGsiState").className = "tm-state "
      + (!image ? "" : image.verdict && image.verdict.ok ? "good" : "bad");
    paintVerdict("tmGsiVerdict", image ? image.verdict : null);

    /* The unlock is gated on the same facts the main process checks. This
     * only removes the temptation; it is not the guard. */
    const ready = !!(device.authorized
      && identity.oemUnlock === "allowed"
      && identity.bootloader === "locked"
      && fw && fw.verdict.ok);
    el("tmUnlockConfirm").disabled = !ready;
    el("tmUnlock").disabled = !ready || el("tmUnlockConfirm").value.trim() !== CONFIRM;
    el("tmUnlockWhy").textContent = ready
      ? "Type " + CONFIRM + " to arm this."
      : identity.bootloader === "unlocked"
        ? "Already unlocked — nothing to do."
        : "Blocked: a connected, authorized tablet with OEM unlocking on and a "
          + "verified restore image are all required.";
  }

  async function refresh() {
    if (busy) return;
    busy = true;
    say("surveying…");
    try {
      paint(await api().terminalSurvey());
      say("");
    } catch (error) {
      say(error.message || String(error), true);
    } finally {
      busy = false;
    }
  }

  async function saveAndRefresh(patch) {
    const cfg = await api().readConfig();
    await api().writeConfig(Object.assign({}, cfg, patch));
    await refresh();
  }

  async function build() {
    host.innerHTML =
      '<div class="tm-wrap">'
      + '<div class="tm-head"><h2>Terminal</h2>'
      + '<span id="tmTools" class="tm-tools"></span>'
      + '<button id="tmRefresh" class="tm-btn">Refresh</button></div>'

      + '<section class="tm-card"><h3>The tablet</h3>'
      + '<div id="tmFacts" class="tm-facts"></div>'
      + '<div id="tmVerdict" class="tm-verdict"></div>'
      + '<div class="tm-row">'
      + '<button id="tmSnapshot" class="tm-btn">Snapshot</button>'
      + '<button id="tmToBootloader" class="tm-btn">→ bootloader</button>'
      + '<button id="tmToFastbootd" class="tm-btn">→ fastbootd</button>'
      + '<button id="tmToSystem" class="tm-btn">→ system</button>'
      + '</div></section>'

      + '<section class="tm-card"><h3>The way back '
      + '<span id="tmFwState" class="tm-state"></span></h3>'
      + '<p class="tm-hint">Lenovo stock firmware, from Rescue and Smart '
      + 'Assistant. Unlocking erases the tablet, so this must exist and be '
      + 'verified before the unlock will run.</p>'
      + '<div class="tm-row"><input id="tmFwDir" class="tm-input" '
      + 'placeholder="C:\\ProgramData\\RSA\\Download\\RomFiles\\...\\image" spellcheck="false">'
      + '<button id="tmFwSave" class="tm-btn">Use</button>'
      + '<button id="tmFwVerify" class="tm-btn">Verify + hash</button></div>'
      + '<div id="tmFwVerdict" class="tm-verdict"></div></section>'

      + '<section class="tm-card"><h3>The GSI '
      + '<span id="tmGsiState" class="tm-state"></span></h3>'
      + '<p class="tm-hint">The system image to flash. Checked against what '
      + 'this tablet actually reports — architecture, A/B, VNDK — not against '
      + 'its filename.</p>'
      + '<div class="tm-row"><input id="tmGsiFile" class="tm-input" '
      + 'placeholder="C:\\_tools\\pinebox-gsi\\lineage-...-arm64_bvN.img" spellcheck="false">'
      + '<button id="tmGsiSave" class="tm-btn">Use</button>'
      + '<button id="tmGsiVerify" class="tm-btn">Verify + hash</button></div>'
      + '<div id="tmGsiVerdict" class="tm-verdict"></div></section>'

      + '<section class="tm-card"><h3>Over the network '
      + '<span id="tmNetState" class="tm-state"></span></h3>'
      + '<p class="tm-hint">Once a terminal is provisioned the cable is '
      + 'optional. Discovery asks mDNS first and only sweeps the private '
      + 'subnets this machine is on if nothing answers.</p>'
      + '<div class="tm-row">'
      + '<button id="tmDiscover" class="tm-btn">Scan the network</button>'
      + '<button id="tmWirelessOn" class="tm-btn">Enable over Wi-Fi (needs the cable)</button>'
      + '</div>'
      + '<div id="tmFound" class="tm-found"></div>'
      + '<div class="tm-row">'
      + '<input id="tmConnectHost" class="tm-input" spellcheck="false" '
      + 'placeholder="10.89.1.x  (or host:port)">'
      + '<button id="tmConnect" class="tm-btn">Connect</button>'
      + '<button id="tmDisconnect" class="tm-btn">Disconnect all</button>'
      + '</div></section>'

      + '<section class="tm-card"><h3>Send the broadcast '
      + '<span id="tmSendState" class="tm-state"></span></h3>'
      + '<p class="tm-hint">The station routes each stream to the box, a '
      + 'page, both, off or the Nabu. Both this app and the tablet are '
      + '"page" clients, so choosing the PineTab moves the route to a page '
      + 'AND makes this desktop stay quiet.</p>'
      + '<div id="tmSendRow" class="tm-row"></div>'
      + '<p id="tmSendWhy" class="tm-hint"></p></section>'

      + '<section class="tm-card"><h3>Which device makes the noise '
      + '<span id="tmMixState" class="tm-state"></span></h3>'
      + '<p class="tm-hint">One row per device, each with its own volumes, '
      + 'so the tablet can be set from here while it is the one playing. '
      + 'A device only plays if it is switched on <i>and</i> the station can '
      + 'still see it — turn the tablet off and whichever row is marked '
      + '<b>takes over</b> picks the show up automatically.</p>'
      + '<div id="tmMix" class="tm-mix"></div></section>'

      + '<section class="tm-card"><h3>The PineTab app '
      + '<span id="tmAppState" class="tm-state"></span></h3>'
      + '<p class="tm-hint">Builds the kiosk APK and puts it on the tablet. '
      + 'The Android toolchain lives outside this repo and records its own '
      + 'paths; the build must run from a local disk, never the share.</p>'
      + '<div class="tm-row">'
      + '<input id="tmProject" class="tm-input" spellcheck="false" '
      + 'placeholder="C:\_tools\pinebox-android\PineBoxKiosk">'
      + '<button id="tmBuild" class="tm-btn">Build APK</button>'
      + '<button id="tmInstall" class="tm-btn">Install on tablet</button>'
      + '</div>'
      + '<div id="tmAppVerdict" class="tm-verdict"></div></section>'

      + '<section class="tm-card danger"><h3>Unlock the bootloader</h3>'
      + '<p class="tm-hint">This <b>erases every byte of user data</b> on the '
      + 'tablet and cannot be undone. The tablet will ask you to confirm on '
      + 'its own screen as well.</p>'
      + '<div class="tm-row">'
      + '<input id="tmUnlockConfirm" class="tm-input" spellcheck="false" '
      + 'placeholder="type the confirmation to arm this">'
      + '<button id="tmUnlock" class="tm-btn danger">Unlock</button></div>'
      + '<p id="tmUnlockWhy" class="tm-hint"></p></section>'

      + '<div id="tmNote" class="tm-note"></div>'
      + '<pre id="tmOut" class="tm-out"></pre>'
      + '</div>';

    const cfg = await api().readConfig();
    el("tmFwDir").value = cfg.firmwareDir || "";
    el("tmGsiFile").value = cfg.gsiImage || "";

    el("tmRefresh").onclick = refresh;
    el("tmFwSave").onclick = () => saveAndRefresh({firmwareDir: el("tmFwDir").value.trim()});
    el("tmGsiSave").onclick = () => saveAndRefresh({gsiImage: el("tmGsiFile").value.trim()});

    el("tmSnapshot").onclick = async () => {
      say("reading the tablet…");
      const shot = await api().terminalSnapshot();
      el("tmOut").textContent = shot && shot.ok
        ? "Snapshot " + shot.serial + "\n" + shot.caveat
        : "Could not snapshot — the tablet has not authorized this computer.";
      say("");
    };
    el("tmToBootloader").onclick = async () => {
      say("rebooting to the bootloader…");
      await api().terminalReboot("bootloader");
      setTimeout(refresh, 9000);
    };
    el("tmToFastbootd").onclick = async () => {
      say("rebooting to fastbootd…");
      await api().terminalReboot("fastbootd");
      setTimeout(refresh, 9000);
    };
    el("tmToSystem").onclick = async () => {
      say("rebooting…");
      await api().terminalReboot("system");
      setTimeout(refresh, 30000);
    };

    el("tmFwVerify").onclick = async () => {
      say("hashing the firmware — this reads several gigabytes…");
      const result = await api().terminalVerifyFirmware(el("tmFwDir").value.trim());
      el("tmOut").textContent = JSON.stringify({
        manifest: result.report && result.report.manifest,
        images: result.report && (result.report.images || []).length,
        verdict: result.verdict
      }, null, 1);
      say("");
      refresh();
    };
    el("tmGsiVerify").onclick = async () => {
      say("hashing the GSI…");
      const result = await api().terminalVerifyGsi(el("tmGsiFile").value.trim());
      el("tmOut").textContent = JSON.stringify(result, null, 1);
      say("");
      refresh();
    };

    el("tmDiscover").onclick = async () => {
      say("scanning — mDNS first, then the local subnets…");
      const result = await api().terminalDiscover({});
      const box = el("tmFound");
      box.replaceChildren();
      for (const found of result.found || []) {
        const row = document.createElement("div");
        row.className = "tm-found-row";
        const where = found.how === "usb" ? "on the cable" : found.host + ":" + found.port;
        row.innerHTML = '<b>' + (found.serial || "terminal") + '</b>'
          + '<span>' + where + '</span><em>' + found.how + '</em>';
        if (found.host) {
          row.style.cursor = "pointer";
          row.onclick = () => { el("tmConnectHost").value = found.host + ":" + found.port; };
        }
        box.appendChild(row);
      }
      el("tmNetState").textContent = (result.found || []).length + " found";
      el("tmNetState").className = "tm-state " + ((result.found || []).length ? "good" : "");
      say((result.notes || []).join(" "));
    };

    el("tmWirelessOn").onclick = async () => {
      say("switching the tablet to TCP mode…");
      const result = await api().terminalWirelessEnable(5555);
      el("tmOut").textContent = JSON.stringify(result, null, 1);
      if (result.address) el("tmConnectHost").value = result.address.address + ":" + result.port;
      /* Said plainly because it is the thing people trip over: adb tcpip
       * does not survive a reboot on a build that does not persist it. */
      say(result.note + (result.persists ? "" : "  (this does not survive a reboot)"),
        !result.ok);
    };

    el("tmConnect").onclick = async () => {
      const target = el("tmConnectHost").value.trim();
      if (!target) { say("Give it an address first.", true); return; }
      say("connecting to " + target + "…");
      const result = await api().terminalWirelessConnect(target);
      say(result.output || "", !result.ok);
      refresh();
    };
    el("tmDisconnect").onclick = async () => {
      await api().terminalWirelessDisconnect();
      say("disconnected");
      refresh();
    };

    /* Where the broadcast goes. Painted from the station's own state on
     * every refresh, never from anything this page remembers. */
    async function paintSend() {
      const row = el("tmSendRow");
      if (!row || !api().pinetabWhere) return;
      let where;
      try { where = await api().pinetabWhere(); }
      catch (error) { el("tmSendWhy").textContent = error.message; return; }
      el("tmSendState").textContent = where.current.label || "—";
      /* Green means SINGULAR - going to exactly one place. Red is the
       * state the operator asked never to be in: "individually but never at
       * the same time". Worth shouting: two rooms playing a half-second
       * apart sounds like a fault in the show rather than two copies of a
       * show that is fine. */
      el("tmSendState").className = "tm-state "
        + (where.current.singular ? "good" : "bad");
      row.replaceChildren();
      for (const option of where.offered) {
        const button = document.createElement("button");
        button.className = "tm-btn" + (option.key === where.current.key ? " on" : "");
        button.textContent = option.label;
        button.title = option.why;
        button.onclick = async () => {
          say("sending the broadcast to " + option.label + "…");
          try {
            const done = await api().pinetabSend(option.key);
            say(done.ok ? done.why : (done.blockers || []).join(" "), !done.ok);
          } catch (error) { say(error.message, true); }
          paintSend();
          /* The destination decides which device is the room, so the
           * mixer below is stale the moment this lands. */
          paintAudio();
        };
        row.appendChild(button);
      }
      /* Say what is TRUE first - including when it is not what was asked
       * for - and only then what the tablet is doing. */
      el("tmSendWhy").textContent = (where.current.singular ? "" : "⚠ ")
        + (where.current.why || "")
        + (where.tabShouldPlay
          ? "  The tablet " + (where.tabShouldPlay.play ? "is playing." : "is quiet.")
          : "");
    }
    paintSend();

    /* The routing table. The decision itself is made in terminal-audio.cjs
     * so the tablet reaches the same answer from the same two documents -
     * if the two disagreed, the show would play twice or not at all. */
    async function paintAudio() {
      const host = el("tmMix");
      if (!host || !api().terminalAudioTable) return;
      let table;
      try { table = await api().terminalAudioTable(); }
      catch (error) { host.textContent = error.message; return; }

      el("tmMixState").textContent = table.silent ? "nothing is playing"
        : table.playing.map((id) => (table.rows[id] || {}).name || id).join(" + ");
      el("tmMixState").className = "tm-state " + (table.silent ? "bad" : "good");

      host.replaceChildren();
      const ids = Object.keys(table.rows).sort();
      if (!ids.length) {
        host.innerHTML = '<p class="tm-hint">No devices yet. One appears the '
          + 'first time a client claims a row.</p>';
        return;
      }
      for (const id of ids) {
        const row = table.rows[id];
        const card = document.createElement("div");
        card.className = "tm-dev" + (row.play ? " playing" : "");

        const head = document.createElement("div");
        head.className = "tm-dev-head";
        const name = document.createElement("b");
        name.textContent = row.name;
        const seen = document.createElement("span");
        seen.className = "tm-dev-seen" + (row.present ? " here" : "");
        seen.textContent = row.present
          ? "here, " + Math.round(row.seen) + "s ago"
          : (row.gone || "not here");
        const why = document.createElement("span");
        why.className = "tm-dev-why";
        why.textContent = row.why || (row.wants ? "switched on, waiting" : "off");

        const sw = document.createElement("button");
        sw.className = "tm-btn" + (row.wants ? " on" : "");
        sw.textContent = row.wants ? "On air" : "Off";
        sw.title = "Switch this device's broadcast on or off";
        sw.onclick = () => set(id, {play: !row.wants});

        const fb = document.createElement("button");
        fb.className = "tm-btn small" + (row.fallback ? " on" : "");
        fb.textContent = "Takes over";
        fb.title = "When nothing else is playing, this device picks the show up";
        fb.onclick = () => set(id, {fallback: !row.fallback});

        head.append(name, seen, why, sw, fb);
        card.appendChild(head);

        for (const [stream, label] of [["music", "Music"], ["voice", "DJs"],
          ["reply", "Replies"]]) {
          const line = document.createElement("label");
          line.className = "tm-dev-level";
          const tag = document.createElement("span");
          tag.textContent = label;
          const slider = document.createElement("input");
          slider.type = "range";
          slider.min = "0"; slider.max = "1"; slider.step = "0.05";
          slider.value = String(row.levels[stream]);
          const read = document.createElement("i");
          read.textContent = Math.round(row.levels[stream] * 100) + "%";
          slider.oninput = () => {
            read.textContent = Math.round(Number(slider.value) * 100) + "%";
          };
          /* On release, not on every pixel - each write is a whole settings
           * document, and dragging would put hundreds through the station. */
          slider.onchange = () => set(id, {[stream]: Number(slider.value)});
          line.append(tag, slider, read);
          card.appendChild(line);
        }
        host.appendChild(card);
      }

      async function set(id, patch) {
        try {
          const done = await api().terminalAudioSet(id, patch);
          if (!done.ok) say((done.blockers || []).join(" "), true);
        } catch (error) { say(error.message, true); }
        paintAudio();
      }
    }
    paintAudio();
    /* Presence goes stale in 15s, so a dark tablet must show as dark
     * without the operator having to reopen the panel. */
    setInterval(paintAudio, 6000);

    el("tmBuild").onclick = async () => {
      const dir = el("tmProject").value.trim() || undefined;
      say("building the APK — a first build fetches dependencies and takes minutes…");
      const result = await api().terminalBuildApk(dir ? {projectDir: dir} : {});
      paintVerdict("tmAppVerdict", result.verdict);
      el("tmOut").textContent = (result.output || "").slice(-3000);
      if (result.ok) {
        el("tmAppState").textContent = "built — "
          + Math.round(result.outcome.bytes / 1024) + " KB";
        el("tmAppState").className = "tm-state good";
        say("Built " + result.outcome.apk
          + (result.outcome.warnings ? "  (" + result.outcome.warnings + " warnings)" : ""));
      } else {
        el("tmAppState").textContent = "not built";
        el("tmAppState").className = "tm-state bad";
        say(result.ran ? "The build failed — see below." : "Blocked before it started.", true);
      }
    };

    el("tmInstall").onclick = async () => {
      const dir = el("tmProject").value.trim();
      say("installing on the tablet…");
      const apk = dir
        ? dir.replace(/[\/]+$/, "") + "\app\build\outputs\apk\debug\app-debug.apk"
        : undefined;
      const result = await api().terminalInstallApk(apk ? {apk} : {});
      el("tmOut").textContent = result.output || (result.blockers || []).join(" ");
      say(result.ok ? "Installed on " + (result.serial || "the tablet")
        : "Install failed — see below.", !result.ok);
    };

    el("tmUnlockConfirm").addEventListener("input", () => {
      el("tmUnlock").disabled = el("tmUnlockConfirm").value.trim() !== CONFIRM;
    });
    el("tmUnlock").onclick = async () => {
      say("unlocking — CONFIRM ON THE TABLET SCREEN", false);
      el("tmUnlock").disabled = true;
      try {
        const result = await api().terminalUnlock(el("tmUnlockConfirm").value.trim());
        el("tmOut").textContent = JSON.stringify(result, null, 1);
        say(result.ok ? "Unlocked." : "Not unlocked — see below.", !result.ok);
        el("tmUnlockConfirm").value = "";
      } catch (error) {
        say(error.message || String(error), true);
      }
      refresh();
    };
  }

  async function mount(target) {
    if (!target) return;
    if (host === target) { refresh(); return; }
    host = target;
    await build();
    await refresh();
  }

  function bootstrap() {
    const tab = document.getElementById("terminalTabBtn");
    const view = document.getElementById("terminal");
    if (!tab || !view) return;
    tab.addEventListener("click", () => mount(view));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrap);
  } else {
    bootstrap();
  }

  root.PineTerminalPanel = {mount, refresh};
})(typeof window !== "undefined" ? window : globalThis);
