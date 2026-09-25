from pathlib import Path
import sys
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import station_stream


def test_listener_mix_is_bounded_and_rejects_incomplete_values():
    assert station_stream.listener_mix("62,100,60") == (62, 100, 60)
    assert station_stream.listener_mix("-1,201,12.8") == (0, 200, 12)
    assert station_stream.listener_mix("62,100") == (100, 100, 100)


def test_centered_pcm_and_program_mix_reach_both_channels():
    source = np.array([1200, -200, -800, 400], dtype="<i2").tobytes()
    centred = station_stream._centered_pcm(source).reshape(-1, 2)
    assert np.array_equal(centred[:, 0], centred[:, 1])

    bed = np.array([500, 500, 500, 500], dtype=np.int32)
    voice = np.array([1000, 1000, 1000, 1000], dtype=np.int32)
    frame = np.frombuffer(
        station_stream._mixed_program(bed, voice, False, (100, 100, 100)),
        dtype="<i2",
    ).reshape(-1, 2)
    assert np.array_equal(frame[:, 0], frame[:, 1])
    assert frame[0, 0] > 500


def test_hls_personal_mix_is_a_private_lane_without_a_join_burst(tmp_path):
    stream = station_stream.StationStream(lambda: {}, bitrate=128)
    stream._hls_root = tmp_path
    with mock.patch.object(station_stream._HlsEncoder, "start", return_value=True):
        with mock.patch.object(stream, "ensure_running"):
            one = stream.hls(128, (62, 100, 60))
            same = stream.hls(128, (62, 100, 60))
            other = stream.hls(128, (100, 100, 100))
    assert one is same
    assert one is not other
    assert one.mix == (62, 100, 60)
    assert one.prime == []
    assert station_stream.HLS_LIST_SIZE >= 15


def test_tailnet_hls_delivery_avoids_render_pool_and_video_poll_has_hls_flag():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "async def station_stream_hls_segment(" in source
    segment = source[source.index("async def station_stream_hls_segment("):
                     source.index('@app.get("/stream.m3u")')]
    assert "data = path.read_bytes()" in segment
    assert "await asyncio.to_thread(path.read_bytes)" not in segment
    video = source[source.index("async def dj_video_api("):
                   source.index('@app.post("/api/dj/voice/ack")')]
    assert 'hls: str = ""' in video
    assert "hls_listener" in video


def test_listener_and_h3_paths_are_durable_and_visible():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '"/api/listener/ads"' in source
    assert "async def listener_make_ad" in source
    assert "async def h3_capacity_relief" in source
    assert "async def h3_hourly_ad_clock" in source
    assert '"air_it": True' in source
    assert "async def gen_ads_broadcast" in source
    assert 'href="__PWA_MANIFEST__"' in source
    assert '"&hls=1"' in source
    assert "async def sfx_replay_source_api" in source
    assert "async def sfx_h3_stinger_api" in source
    assert "voice_ad_render(goal, reference_clip=reference)" in source
    assert "before >= target and not force" in source


def test_hot_corner_replay_uses_a_signed_source_and_offers_h3_in_both_bundles():
    desk = (ROOT / "desktop" / "renderer" / "hot-corners.js").read_text(encoding="utf-8")
    tablet = (ROOT / "app" / "src" / "main" / "assets" / "pine-views" / "hot-corners.js").read_text(encoding="utf-8")
    assert desk == tablet
    assert "replay-source" in desk
    assert "h3-stinger" in desk
    assert "offerReplayStinger" in desk
