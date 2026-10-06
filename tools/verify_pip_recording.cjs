#!/usr/bin/env node
'use strict';
// Full decode and timestamp audit. Metadata does not establish perceptual A/V sync.
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { findFfmpeg } = require('../desktop/clip-mux.cjs');
const finite = x => x !== undefined && x !== null && x !== 'N/A' && Number.isFinite(Number(x)) ? Number(x) : null;
const round = x => x === null ? null : Math.round(x * 1000000) / 1000000;
function fraction(x) {
  const [a, b = 1] = String(x || '0').split('/').map(Number);
  return b && Number.isFinite(a / b) ? a / b : null;
}
function run(exe, args) {
  const result = spawnSync(exe, args, { windowsHide: true, encoding: 'utf8',
    maxBuffer: 128 * 1024 * 1024, timeout: 600000 });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(String(result.stderr || result.stdout || 'Media tool failed.').trim());
  return result;
}
function summarize(stream, frames, expectedFps) {
  const declaredFps = fraction(stream.avg_frame_rate) || fraction(stream.r_frame_rate);
  const times = frames.map(f => finite(f.best_effort_timestamp_time) ?? finite(f.pts_time)).filter(x => x !== null);
  const observed = times.slice(1).map((t, i) => t - times[i]).filter(x => x > 0).sort((a, b) => a - b);
  const plausibleFps = declaredFps > 0 && declaredFps <= 240 ? declaredFps : null;
  const step = stream.codec_type === 'video' ? (expectedFps || plausibleFps ? 1 / (expectedFps || plausibleFps) : observed[Math.floor(observed.length / 2)] || 1 / 60) : null;
  let first = null, end = null, previous = null, previousDuration = 0;
  const intervals = [], gaps = [];
  let regressions = 0, repeatedPts = 0, untimedFrames = 0;
  for (const frame of frames) {
    const at = finite(frame.best_effort_timestamp_time) ?? finite(frame.pts_time);
    if (at === null) { untimedFrames++; continue; }
    const duration = stream.codec_type === 'audio'
      ? (finite(frame.nb_samples) || 0) / (Number(stream.sample_rate) || 48000)
      : finite(frame.duration_time) ?? finite(frame.pkt_duration_time) ?? step ?? 0;
    if (first === null) first = at;
    end = Math.max(end ?? at, at + duration);
    if (previous !== null) {
      const interval = at - previous;
      intervals.push(interval);
      if (interval < -0.00001) regressions++;
      if (Math.abs(interval) < 0.00001) repeatedPts++;
      const gap = stream.codec_type === 'video' ? interval - step : at - (previous + previousDuration);
      if (gap > (stream.codec_type === 'video' ? step * 0.5 : 0.002))
        gaps.push({ at: round(at), missingSeconds: round(gap) });
    }
    previous = at; previousDuration = duration;
  }
  const sorted = intervals.slice().sort((a, b) => a - b);
  const span = first === null || end === null ? null : end - first;
  return {
    index: stream.index, type: stream.codec_type, codec: stream.codec_name,
    profile: stream.profile, pixelFormat: stream.pix_fmt,
    width: stream.width, height: stream.height, channels: stream.channels,
    sampleRate: finite(stream.sample_rate), declaredFps: round(declaredFps),
    decodedFrames: frames.length, startSeconds: round(first), endSeconds: round(end),
    durationSeconds: round(span), measuredFps: stream.codec_type === 'video' && span > 0 ? round(frames.length / span) : undefined,
    medianIntervalMs: sorted.length ? round(sorted[Math.floor(sorted.length / 2)] * 1000) : null,
    maximumIntervalMs: sorted.length ? round(sorted.at(-1) * 1000) : null,
    timestampRegressions: regressions, repeatedTimestamps: repeatedPts, untimedFrames,
    gapCount: gaps.length, totalGapSeconds: round(gaps.reduce((n, g) => n + g.missingSeconds, 0)),
    gaps: gaps.slice(0, 50), gapsTruncated: gaps.length > 50,
    color: { space: stream.color_space, primaries: stream.color_primaries, transfer: stream.color_transfer, range: stream.color_range }
  };
}
function fastStart(file) {
  if (!/\.(mp4|mov|m4v)$/i.test(file)) return null;
  const fd = fs.openSync(file, 'r');
  try {
    const bytes = fs.fstatSync(fd).size, header = Buffer.alloc(16);
    let position = 0, moov = null, mdat = null;
    while (position + 8 <= bytes) {
      if (fs.readSync(fd, header, 0, 16, position) < 8) break;
      let size = header.readUInt32BE(0);
      const type = header.toString('ascii', 4, 8);
      if (size === 1) size = Number(header.readBigUInt64BE(8));
      if (size === 0) size = bytes - position;
      if (type === 'moov') moov = position;
      if (type === 'mdat' && mdat === null) mdat = position;
      if (size < 8 || !Number.isSafeInteger(size)) break;
      position += size;
    }
    return moov !== null && mdat !== null ? moov < mdat : null;
  } finally { fs.closeSync(fd); }
}
function verifyRecording(file, options = {}) {
  const fullPath = path.resolve(file), ffmpeg = findFfmpeg(options.ffmpeg).path;
  const sibling = path.join(path.dirname(ffmpeg), process.platform === 'win32' ? 'ffprobe.exe' : 'ffprobe');
  const ffprobe = options.ffprobe || (fs.existsSync(sibling) ? sibling : 'ffprobe');
  const raw = run(ffprobe, ['-v', 'error', '-show_streams', '-show_format', '-show_frames',
    '-show_entries', 'format=duration,start_time,size,format_name:stream=index,codec_type,codec_name,profile,pix_fmt,width,height,channels,sample_rate,avg_frame_rate,r_frame_rate,color_space,color_primaries,color_transfer,color_range:frame=stream_index,best_effort_timestamp_time,pts_time,duration_time,pkt_duration_time,nb_samples',
    '-of', 'json', fullPath]);
  const info = JSON.parse(raw.stdout), framesByStream = new Map();
  for (const frame of info.frames || []) {
    if (!framesByStream.has(frame.stream_index)) framesByStream.set(frame.stream_index, []);
    framesByStream.get(frame.stream_index).push(frame);
  }
  const streams = (info.streams || []).filter(s => ['video', 'audio'].includes(s.codec_type))
    .map(s => summarize(s, framesByStream.get(s.index) || [], options.fps));
  const video = streams.find(s => s.type === 'video'), audio = streams.find(s => s.type === 'audio'), problems = [];
  let decoded = false, decodeDetail = '';
  try {
    run(ffmpeg, ['-hide_banner', '-nostdin', '-v', 'error', '-xerror', '-i', fullPath, '-map', '0:v?', '-map', '0:a?', '-f', 'null', '-']);
    decoded = true;
  } catch (error) { decodeDetail = error.message; problems.push('Full decode failed: ' + error.message); }
  const validTimes = video && audio && [audio.startSeconds, video.startSeconds, audio.endSeconds, video.endSeconds].every(x => x !== null);
  const skew = validTimes ? {
    startMs: round((audio.startSeconds - video.startSeconds) * 1000),
    endMs: round((audio.endSeconds - video.endSeconds) * 1000),
    durationDifferenceMs: round((audio.durationSeconds - video.durationSeconds) * 1000)
  } : null;
  if (options.requireVideo !== false && !video) problems.push('No video stream.');
  if (options.requireAudio && !audio) problems.push('No audio stream.');
  if (video && options.fps && Math.abs(video.measuredFps - options.fps) > options.fps * 0.01)
    problems.push('Measured ' + video.measuredFps + ' fps; expected ' + options.fps + '.');
  for (const [key, label] of [['width', 'Width'], ['height', 'Height']])
    if (video && options[key] && video[key] !== options[key]) problems.push(label + ' ' + video[key] + '; expected ' + options[key] + '.');
  if (video && options.videoCodec && video.codec !== options.videoCodec) problems.push('Unexpected video codec ' + video.codec + '.');
  if (audio && options.audioCodec && audio.codec !== options.audioCodec) problems.push('Unexpected audio codec ' + audio.codec + '.');
  for (const s of streams) {
    if (!s.decodedFrames) problems.push('Stream ' + s.index + ' has no decoded frames.');
    if (s.timestampRegressions || s.repeatedTimestamps || s.untimedFrames) problems.push('Stream ' + s.index + ' has invalid or repeated frame timestamps.');
    if (s.gapCount) problems.push('Stream ' + s.index + ' has ' + s.gapCount + ' timestamp gaps.');
  }
  const maxSkew = options.maxSkewMs ?? 100;
  if (skew && [skew.startMs, skew.endMs].some(x => Math.abs(x) > maxSkew)) problems.push('Stream boundary skew exceeds ' + maxSkew + ' ms.');
  const mp4FastStart = fastStart(fullPath);
  if (options.requireFastStart && mp4FastStart !== true) problems.push('MP4 movie header does not precede its media data.');
  return { ok: !problems.length, file: fullPath, bytes: fs.statSync(fullPath).size,
    format: info.format?.format_name, durationSeconds: finite(info.format?.duration),
    fullDecode: { ok: decoded, detail: decodeDetail }, fastStart: mp4FastStart,
    streams, streamBoundarySkew: skew, problems,
    limitation: 'Timestamp cadence and stream boundaries do not measure perceptual lip sync, source motion, missing repeated source frames, or pixel equivalence with the live display. Use synchronized visual/audio markers and a display comparison for those.' };
}
if (require.main === module) {
  const args = process.argv.slice(2), options = {};
  let file;
  const numeric = { '--fps': 'fps', '--width': 'width', '--height': 'height', '--max-skew-ms': 'maxSkewMs' };
  const text = { '--ffmpeg': 'ffmpeg', '--ffprobe': 'ffprobe', '--video-codec': 'videoCodec', '--audio-codec': 'audioCodec' };
  try {
    for (let i = 0; i < args.length; i++) {
      const arg = args[i];
      if (numeric[arg]) {
        const value = Number(args[++i]);
        if (!Number.isFinite(value) || value < 0 || (arg !== '--max-skew-ms' && value === 0)) throw new Error('Invalid ' + arg + '.');
        options[numeric[arg]] = value;
      } else if (text[arg]) {
        if (!args[i + 1]) throw new Error('Missing value for ' + arg + '.');
        options[text[arg]] = args[++i];
      } else if (arg === '--require-audio') options.requireAudio = true;
      else if (arg === '--audio-only') { options.requireVideo = false; options.requireAudio = true; }
      else if (arg === '--require-faststart') options.requireFastStart = true;
      else if (arg.startsWith('--')) throw new Error('Unknown argument ' + arg + '.');
      else if (!file) file = arg;
      else throw new Error('Provide one media file.');
    }
    if (!file) throw new Error('Usage: node tools/verify_pip_recording.cjs FILE [--fps 60] [--width N --height N] [--require-audio] [--video-codec h264 --audio-codec aac] [--require-faststart] [--max-skew-ms 100]');
    const report = verifyRecording(file, options);
    console.log(JSON.stringify(report, null, 2));
    if (!report.ok) process.exitCode = 1;
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
module.exports = { verifyRecording, summarize, fastStart };

