/* Building and installing the PineTab APK from the desktop.
 *
 * Two of these tests exist because the traps they cover were hit for real
 * while installing the toolchain, and both fail CONFUSINGLY rather than
 * loudly: a UNC working directory that Windows batch launchers silently
 * refuse, and a missing GRADLE_USER_HOME that sends a build off to
 * re-download the Android Gradle Plugin while appearing to hang.
 *
 * Nothing here runs Gradle. The runner is injected.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {
  AndroidBuild, readToolchain, readiness, buildEnv, apkPath, readOutcome
} = require('../desktop/android-build.cjs');

/* Shaped like the real C:\_tools\pinebox-toolchain.json. */
function toolchainFile(overrides) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-tc-'));
  const jdk = path.join(dir, 'jdk17');
  const sdk = path.join(dir, 'android-sdk');
  const gradle = path.join(dir, 'gradle');
  for (const d of [jdk, sdk, gradle, path.join(gradle, 'bin')]) fs.mkdirSync(d, {recursive: true});
  fs.writeFileSync(path.join(gradle, 'bin', 'gradle.bat'), '@echo off');
  fs.writeFileSync(path.join(gradle, 'bin', 'gradle'), '#!/bin/sh');
  const body = Object.assign({
    jdk: {home: jdk, version: '17.0.20.1'},
    android_sdk: {root: sdk},
    ndk: {home: path.join(sdk, 'ndk', '26.1.10909125')},
    cmake: {home: path.join(sdk, 'cmake', '3.22.1')},
    gradle: {home: gradle, version: '8.14.5'}
  }, overrides || {});
  const file = path.join(dir, 'pinebox-toolchain.json');
  fs.writeFileSync(file, JSON.stringify(body, null, 1));
  return {file, dir, jdk, sdk, gradle};
}

function projectDir(withSettings = true) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-proj-'));
  if (withSettings) fs.writeFileSync(path.join(dir, 'settings.gradle.kts'), '');
  return dir;
}

function makeApk(dir, variant = 'debug') {
  const apk = apkPath(dir, variant);
  fs.mkdirSync(path.dirname(apk), {recursive: true});
  fs.writeFileSync(apk, Buffer.alloc(4096, 1));
  return apk;
}

test('the toolchain is read from its manifest, not hardcoded', () => {
  const tc = toolchainFile();
  const read = readToolchain(tc.file);
  assert.equal(read.found, true);
  assert.equal(read.ok, true);
  assert.equal(read.jdk, tc.jdk);
  assert.equal(read.sdk, tc.sdk);
  assert.equal(read.gradle, tc.gradle);
  fs.rmSync(tc.dir, {recursive: true, force: true});
});

test('a manifest naming a path that is not there is worse than none, and says so', () => {
  const tc = toolchainFile({jdk: {home: 'C:\\nope\\jdk17'}});
  const read = readToolchain(tc.file);
  assert.equal(read.found, true);
  assert.equal(read.ok, false);
  assert.match(read.notes.join(' '), /jdk is recorded at .*but is not there/);
  fs.rmSync(tc.dir, {recursive: true, force: true});
});

test('a missing or broken manifest is reported plainly', () => {
  const missing = readToolchain(path.join(os.tmpdir(), 'pine-no-toolchain-xyz.json'));
  assert.equal(missing.found, false);
  assert.match(missing.notes.join(' '), /No Android toolchain manifest/);

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-tc-bad-'));
  const bad = path.join(dir, 'broken.json');
  fs.writeFileSync(bad, '{ not json');
  assert.equal(readToolchain(bad).found, false);
  assert.match(readToolchain(bad).notes.join(' '), /not valid JSON/);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('GRADLE_USER_HOME is always set - without it AGP is re-downloaded', () => {
  const tc = toolchainFile();
  const env = buildEnv(readToolchain(tc.file));
  assert.ok(env.GRADLE_USER_HOME, 'this is the difference between seconds and minutes');
  assert.equal(env.JAVA_HOME, tc.jdk);
  assert.equal(env.ANDROID_HOME, tc.sdk);
  assert.equal(env.ANDROID_SDK_ROOT, tc.sdk, 'both spellings, because tools disagree');
  assert.ok(env.ANDROID_NDK_HOME);
  fs.rmSync(tc.dir, {recursive: true, force: true});
});

test('a project on a UNC path is refused before Gradle can silently misbehave', () => {
  const tc = toolchainFile();
  const verdict = readiness(readToolchain(tc.file),
    '\\\\10.89.1.246\\ehm_eckx\\pinevoice-stack\\spark-agent\\android');
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers.join(' '), /UNC path/);
  assert.match(verdict.blockers.join(' '), /local disk/);
  fs.rmSync(tc.dir, {recursive: true, force: true});
});

test('a directory with no Gradle settings is not an Android project', () => {
  const tc = toolchainFile();
  const bare = projectDir(false);
  const verdict = readiness(readToolchain(tc.file), bare);
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers.join(' '), /not an Android project/);
  fs.rmSync(tc.dir, {recursive: true, force: true});
  fs.rmSync(bare, {recursive: true, force: true});
});

test('a build runs gradle with a LOCAL cwd and the right environment', async () => {
  const tc = toolchainFile();
  const proj = projectDir();
  const seen = [];
  const builder = new AndroidBuild({
    manifest: tc.file,
    run: async (cmd, args, options) => {
      seen.push({cmd, args, options});
      makeApk(proj);                       /* gradle produced an APK */
      return 'BUILD SUCCESSFUL in 2m 30s';
    }
  });
  const result = await builder.build({projectDir: proj});
  assert.equal(result.ok, true);
  assert.equal(result.outcome.built, true);
  assert.ok(result.outcome.bytes > 0);

  const call = seen[0];
  assert.match(call.cmd, /gradle(\.bat)?$/);
  assert.ok(call.args.includes('assembleDebug'));
  assert.equal(call.options.cwd, proj, 'gradle must run from the project, locally');
  assert.equal(call.options.env.JAVA_HOME, tc.jdk);
  assert.ok(call.options.env.GRADLE_USER_HOME);
  fs.rmSync(tc.dir, {recursive: true, force: true});
  fs.rmSync(proj, {recursive: true, force: true});
});

test('an APK on disk is what proves a build, not what Gradle printed', async () => {
  const tc = toolchainFile();
  const proj = projectDir();
  /* Gradle claims success but produced nothing. */
  const liar = new AndroidBuild({manifest: tc.file, run: async () => 'BUILD SUCCESSFUL in 1s'});
  const result = await liar.build({projectDir: proj});
  assert.equal(result.ok, false, 'no APK means no build, whatever it said');
  assert.equal(result.outcome.built, false);
  fs.rmSync(tc.dir, {recursive: true, force: true});
  fs.rmSync(proj, {recursive: true, force: true});
});

test('a failed build is reported with its output, not swallowed', async () => {
  const tc = toolchainFile();
  const proj = projectDir();
  const builder = new AndroidBuild({manifest: tc.file,
    run: async () => { throw Object.assign(new Error('gradle died'),
      {output: 'FAILURE: Build failed with an exception.\nCould not resolve AGP'}); }});
  const result = await builder.build({projectDir: proj});
  assert.equal(result.ok, false);
  assert.equal(result.ran, true);
  assert.match(result.output, /Could not resolve AGP/);
  fs.rmSync(tc.dir, {recursive: true, force: true});
  fs.rmSync(proj, {recursive: true, force: true});
});

test('warnings are counted, never mistaken for failure', () => {
  const dir = projectDir();
  const apk = makeApk(dir);
  const outcome = readOutcome(
    'w: file:///x/Main.kt:3:9 variable is never used\n'
    + 'w: file:///x/Other.kt:9:1 deprecated\n'
    + 'BUILD SUCCESSFUL in 45s', apk);
  assert.equal(outcome.succeeded, true);
  assert.equal(outcome.failed, false);
  assert.equal(outcome.warnings, 2);
  assert.equal(outcome.built, true);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('installing targets a serial, because two transports make adb ambiguous', async () => {
  const dir = projectDir();
  const apk = makeApk(dir);
  const seen = [];
  const builder = new AndroidBuild({run: async (cmd, args) => {
    seen.push([cmd, ...args].join(' '));
    return 'Performing Streamed Install\nSuccess';
  }});
  const result = await builder.installApk({apk, serial: 'HA1Y7RCV', adb: 'adb.exe'});
  assert.equal(result.ok, true);
  assert.match(seen[0], /-s HA1Y7RCV install -r/);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('a refused install is not reported as success', async () => {
  const dir = projectDir();
  const apk = makeApk(dir);
  const builder = new AndroidBuild({run: async () =>
    'Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: signatures do not match]'});
  const result = await builder.installApk({apk});
  assert.equal(result.ok, false);
  assert.match(result.output, /INSTALL_FAILED_UPDATE_INCOMPATIBLE/);

  const nothing = await builder.installApk({apk: path.join(dir, 'nope.apk')});
  assert.equal(nothing.ok, false);
  assert.match(nothing.blockers.join(' '), /No APK at/);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('a builder without a runner cannot silently shell out', () => {
  assert.throws(() => new AndroidBuild({}), /needs a runner/);
});

test('a manifest with a UTF-8 BOM is read, because Windows writes them', () => {
  /* MEASURED: the real C:\_tools\pinebox-toolchain.json arrived with a BOM
   * - PowerShell writes one by default - and JSON.parse rejected the whole
   * file with "Unexpected token" despite it being valid JSON. */
  const tc = toolchainFile();
  const raw = fs.readFileSync(tc.file, 'utf8');
  fs.writeFileSync(tc.file, '\ufeff' + raw, 'utf8');
  const read = readToolchain(tc.file);
  assert.equal(read.found, true, 'a BOM must not make a good manifest unreadable');
  assert.equal(read.ok, true);
  assert.equal(read.jdk, tc.jdk);
  fs.rmSync(tc.dir, {recursive: true, force: true});
});

test('a Windows .bat is spawned through a shell, or Node refuses it', () => {
  /* MEASURED: `execFile` on gradle.bat answers `spawn EINVAL` on Windows
   * since the CVE-2024-27980 fix. Three words, no mention of batch files -
   * so the knowledge lives here rather than in every caller. */
  const {spawnOptionsFor} = require('../desktop/android-build.cjs');
  const onWindows = process.platform === 'win32';
  assert.equal(!!spawnOptionsFor('C:\_tools\gradle\bin\gradle.bat').shell, onWindows);
  assert.equal(!!spawnOptionsFor('C:\_tools\sdk\sdkmanager.CMD').shell, onWindows);
  /* A real executable must NOT get a shell - that would reintroduce the
   * quoting problems the shell-less spawn exists to avoid. */
  assert.equal(spawnOptionsFor('C:\_tools\platform-tools\adb.exe').shell, undefined);
  assert.equal(spawnOptionsFor('/usr/bin/gradle').shell, undefined);
});

test('the shell option reaches the runner for a batch gradle', async () => {
  const tc = toolchainFile();
  const proj = projectDir();
  let seenOptions = null;
  const builder = new AndroidBuild({manifest: tc.file, run: async (cmd, args, options) => {
    seenOptions = options;
    makeApk(proj);
    return 'BUILD SUCCESSFUL in 1s';
  }});
  await builder.build({projectDir: proj});
  if (process.platform === 'win32') {
    assert.equal(seenOptions.shell, true, 'gradle.bat needs it');
  }
  assert.equal(seenOptions.cwd, proj, 'and the cwd survives the merge');
  assert.ok(seenOptions.env.GRADLE_USER_HOME, 'and so does the environment');
  fs.rmSync(tc.dir, {recursive: true, force: true});
  fs.rmSync(proj, {recursive: true, force: true});
});
