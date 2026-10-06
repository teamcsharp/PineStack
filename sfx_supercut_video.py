"""Source-only MP4 Super Cuts: preserve each picture and its original sound."""
from __future__ import annotations
import hashlib
import math
import subprocess
import tempfile
from pathlib import Path


def require_mp4_sources(plan):
    clips = plan.get('clips') or []
    if not clips or any(Path(str(c.get('path') or '')).suffix.lower() != '.mp4' for c in clips):
        raise ValueError('The SFX Guy makes Super Cut videos exclusively from existing MP4 clips')


def video_facts(path, *, seconds=None, executable=None):
    import imageio_ffmpeg
    path = Path(path)
    if path.suffix.lower() != '.mp4' or not path.is_file() or not 0 < path.stat().st_size <= 150 * 1024 * 1024:
        raise ValueError('The complete Super Cut MP4 is missing or too large')
    reader = imageio_ffmpeg.read_frames(str(path))
    try:
        meta = next(reader)
    finally:
        reader.close()
    duration = float(meta.get('duration') or 0)
    if (not math.isfinite(duration) or duration <= 0 or not meta.get('codec')
            or not meta.get('audio_codec') or min(meta.get('size') or (0, 0)) <= 0):
        raise ValueError('The Super Cut must contain both real video and source audio')
    if seconds is not None and abs(duration - float(seconds)) > .12:
        raise ValueError('The MP4 picture and source audio do not cover the same completed montage')
    return {'video_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'video_bytes': path.stat().st_size, 'video_seconds': duration,
            'video_size': list(meta['size']), 'video_codec': meta['codec']}


def render_video(plan, result, output, executable):
    """Cut the same measured source intervals as the audio, then mux that audio."""
    require_mp4_sources(plan)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    cues = result.get('cues') or []
    if len(cues) != len(plan['clips']):
        raise ValueError('Every MP4 cut must have its original measured source cue')
    temporary = output.with_name(output.stem + '.tmp.mp4')
    run = lambda args: subprocess.run([str(executable), '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', *args],
                                      capture_output=True, timeout=180, check=True)
    try:
        with tempfile.TemporaryDirectory(prefix='pine-supercut-video-') as folder:
            folder = Path(folder)
            for ix, (clip, cue) in enumerate(zip(plan['clips'], cues)):
                source = Path(clip['path'])
                if clip.get('mtime') and abs(source.stat().st_mtime - float(clip['mtime'])) > .01:
                    raise ValueError('An MP4 source changed after composition: ' + str(clip.get('sid')))
                if cue.get('sid') != clip.get('sid'):
                    raise ValueError('The picture cue differs from its original source identity')
                start = float(cue['source_from'])
                span = float(cue['body_seconds'])
                run(['-ss', f'{start:.6f}', '-i', str(source), '-t', f'{span:.6f}', '-map', '0:v:0', '-an',
                     '-vf', 'scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,setpts=PTS-STARTPTS',
                     '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p',
                     str(folder / f'{ix}.mp4')])
            listing = folder / 'cuts.txt'
            listing.write_text(''.join(f"file '{ix}.mp4'\n" for ix in range(len(cues))), encoding='utf-8')
            run(['-f', 'concat', '-safe', '0', '-i', str(listing), '-i', str(result['path']),
                 '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
                 '-t', f"{float(result['seconds']):.6f}", '-movflags', '+faststart', str(temporary)])
            facts = video_facts(temporary, seconds=result['seconds'], executable=executable)
            run(['-i', str(temporary), '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'])
            temporary.replace(output)
        return {**facts, 'kind': 'video', 'video': output.name, 'video_path': str(output),
                'video_source_only': True}
    finally:
        temporary.unlink(missing_ok=True)
