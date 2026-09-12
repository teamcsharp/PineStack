/* Building and installing the PineTab APK from the Pine Box app.
 *
 * The toolchain lives outside this repo, under C:\_tools, and records
 * itself in pinebox-toolchain.json. This reads that rather than hardcoding
 * paths, so a machine that installs it elsewhere still works.
 *
 * Two traps are encoded here because both were hit for real during setup
 * and both produce confusing failures rather than clear ones:
 *
 *   1. GRADLE_USER_HOME. Without it, a build uses %USERPROFILE%\.gradle and
 *      re-downloads the Android Gradle Plugin from scratch - minutes of
 *      apparent hanging on a machine that already has it.
 *   2. A UNC working directory. This repo lives on an SMB share, and
 *      Windows batch launchers refuse it outright: "UNC paths are not
 *      supported. Defaulting to Windows directory." Gradle must be invoked
 *      with a LOCAL cwd or it silently builds the wrong thing.
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const MANIFEST = 'C:\\_tools\\pinebox-toolchain.json';

function readToolchain(file) {
  const target = file || MANIFEST;
  if (!fs.existsSync(target)) {
    return {found: false, file: target,
      notes: ['No Android toolchain manifest. Install the toolchain first.']};
  }
  let parsed;
  try {
    /* MEASURED: the real manifest arrived with a UTF-8 BOM, because that is
     * what PowerShell writes by default - and JSON.parse refuses it with
     * "Unexpected token" on a file that is otherwise perfectly good JSON.
     * Anything written by a Windows tool has to be read this way. */
    parsed = JSON.parse(fs.readFileSync(target, 'utf8').replace(/^﻿/, ''));
  } catch (error) {
    return {found: false, file: target,
      notes: ['The toolchain manifest is not valid JSON: ' + error.message]};
  }
  const home = (section) => (parsed[section] && (parsed[section].home
    || parsed[section].root || parsed[section].path)) || '';
  const shape = {
    found: true,
    file: target,
    jdk: home('jdk'),
    sdk: home('android_sdk'),
    ndk: home('ndk'),
    cmake: home('cmake'),
    gradle: home('gradle'),
    notes: []
  };
  /* A manifest that names a path which is not there is worse than none. */
  for (const [name, value] of Object.entries({jdk: shape.jdk, sdk: shape.sdk, gradle: shape.gradle})) {
    if (!value) shape.notes.push('The manifest does not record a ' + name + ' path.');
    else if (!fs.existsSync(value)) shape.notes.push(name + ' is recorded at ' + value + ' but is not there.');
  }
  shape.ok = !shape.notes.length;
  return shape;
}

function gradleBinary(toolchain) {
  if (!toolchain || !toolchain.gradle) return '';
  const win = path.join(toolchain.gradle, 'bin', 'gradle.bat');
  const nix = path.join(toolchain.gradle, 'bin', 'gradle');
  if (process.platform === 'win32') return fs.existsSync(win) ? win : nix;
  return fs.existsSync(nix) ? nix : win;
}

/* The environment a Gradle build needs, on top of the caller's own. */
function buildEnv(toolchain, {gradleHome} = {}) {
  const env = {
    JAVA_HOME: toolchain.jdk,
    ANDROID_HOME: toolchain.sdk,
    ANDROID_SDK_ROOT: toolchain.sdk,
    /* Keeps the build self-contained and stops AGP being re-fetched into a
     * second cache under the user profile. */
    GRADLE_USER_HOME: gradleHome || 'C:\\_tools\\_gradlehome'
  };
  if (toolchain.ndk) env.ANDROID_NDK_HOME = toolchain.ndk;
  return env;
}

/* MEASURED: Node refuses to spawn a .bat or .cmd directly on Windows -
 * `spawn EINVAL` - since the fix for CVE-2024-27980. Gradle and sdkmanager
 * both ship as .bat, so every invocation of them needs a shell. The failure
 * is opaque (three words, no mention of batch files), so it is handled here
 * rather than left for each caller to rediscover. */
function spawnOptionsFor(command) {
  const isBatch = /\.(bat|cmd)$/i.test(String(command || ''));
  return (process.platform === 'win32' && isBatch) ? {shell: true} : {};
}

/* Where Gradle puts an APK for a given variant. */
function apkPath(projectDir, variant = 'debug') {
  return path.join(projectDir, 'app', 'build', 'outputs', 'apk', variant,
    'app-' + variant + '.apk');
}

function readiness(toolchain, projectDir) {
  const blockers = [];
  if (!toolchain || !toolchain.found) {
    blockers.push('No Android toolchain is installed.');
  } else {
    for (const note of toolchain.notes || []) blockers.push(note);
  }
  if (!projectDir) blockers.push('No project directory given.');
  else if (!fs.existsSync(projectDir)) blockers.push('The project directory does not exist: ' + projectDir);
  else if (!fs.existsSync(path.join(projectDir, 'settings.gradle.kts'))
        && !fs.existsSync(path.join(projectDir, 'settings.gradle'))) {
    blockers.push('That directory has no Gradle settings file, so it is not an Android project.');
  }
  /* The one that bites silently rather than loudly. */
  if (projectDir && /^\\\\/.test(projectDir)) {
    blockers.push('The project is on a UNC path. Windows batch launchers refuse '
      + 'those, so the build must live on a local disk.');
  }
  return {ok: !blockers.length, blockers};
}

/* Gradle prints its verdict; the exit code alone has been known to lie, so
 * both are read and the APK's existence settles it. */
function readOutcome(output, apk) {
  const text = String(output || '');
  const built = fs.existsSync(apk);
  return {
    built,
    apk: built ? apk : '',
    bytes: built ? fs.statSync(apk).size : 0,
    succeeded: /BUILD SUCCESSFUL/i.test(text),
    failed: /BUILD FAILED|FAILURE:/i.test(text),
    /* Both AGP and the NDK warn a lot; a warning is not a failure. */
    warnings: (text.match(/^w: .*$/gim) || []).length
  };
}

class AndroidBuild {
  /* `run(cmd, args, options)` is injected so the whole of this is testable
   * without Gradle, an SDK, or twenty minutes. */
  constructor({run, manifest, gradleHome} = {}) {
    if (typeof run !== 'function') throw new Error('AndroidBuild needs a runner.');
    this.run = run;
    this.manifest = manifest || MANIFEST;
    this.gradleHome = gradleHome;
  }

  toolchain() { return readToolchain(this.manifest); }

  async build({projectDir, variant = 'debug', tasks} = {}) {
    const toolchain = this.toolchain();
    const verdict = readiness(toolchain, projectDir);
    if (!verdict.ok) return {ok: false, ran: false, verdict, toolchain};

    const binary = gradleBinary(toolchain);
    if (!binary) return {ok: false, ran: false, toolchain,
      verdict: {ok: false, blockers: ['No gradle binary in the recorded toolchain.']}};

    const goal = tasks && tasks.length ? tasks
      : ['assemble' + variant.charAt(0).toUpperCase() + variant.slice(1)];
    let output = '';
    try {
      output = String(await this.run(binary, [...goal, '--no-daemon'], Object.assign({
        cwd: projectDir,                       /* LOCAL cwd - never the share */
        env: Object.assign({}, process.env, buildEnv(toolchain, {gradleHome: this.gradleHome}))
      }, spawnOptionsFor(binary))));
    } catch (error) {
      output = String(error.output || error.message || error);
    }
    const outcome = readOutcome(output, apkPath(projectDir, variant));
    return {
      /* An APK on disk is the only thing that actually proves a build. */
      ok: outcome.built && !outcome.failed,
      ran: true, verdict, toolchain, outcome,
      output: output.slice(-4000)
    };
  }

  /* `-r` reinstalls over an existing copy, keeping data. The serial matters
   * once the tablet is on both USB and Wi-Fi - adb refuses an untargeted
   * command when it has two transports for one device. */
  async installApk({apk, serial, adb}) {
    if (!apk || !fs.existsSync(apk)) {
      return {ok: false, blockers: ['No APK at ' + (apk || '(nothing given)')]};
    }
    const binary = adb || 'adb';
    const args = (serial ? ['-s', serial] : []).concat(['install', '-r', apk]);
    const output = String(await this.run(binary, args, spawnOptionsFor(binary)));
    return {
      ok: /\bSuccess\b/i.test(output) && !/\bFailure\b/i.test(output),
      output: output.trim().slice(0, 2000),
      apk, serial: serial || ''
    };
  }
}

module.exports = {
  AndroidBuild, readToolchain, readiness, buildEnv, apkPath,
  gradleBinary, readOutcome, spawnOptionsFor, MANIFEST
};
