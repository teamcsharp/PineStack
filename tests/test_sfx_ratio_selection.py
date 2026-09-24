import sfx_match


CLIPS = ["general.mp3", "general.mp4", "sfx_ads/ad.mp4"]


class Draw:
    def __init__(self, *rolls):
        self.rolls = iter(rolls)

    def random(self):
        return next(self.rolls)


def pick(rows, ads, mp4, rng=None):
    return sfx_match.choose_ratio_pool(
        rows, ads, mp4,
        is_ad=lambda path: path.startswith("sfx_ads/"),
        is_video=lambda path: path.endswith(".mp4"),
        rng=rng or Draw())


def test_exact_endpoints_choose_only_requested_bucket():
    assert pick(CLIPS, 0, 0) == ["general.mp3"]
    assert pick(CLIPS, 0, 100) == ["general.mp4"]
    assert pick(CLIPS, 100, 100) == ["sfx_ads/ad.mp4"]


def test_unavailable_source_or_media_falls_back_without_dropping_clips():
    assert pick(CLIPS, 100, 0) == ["general.mp3"]
    assert pick(CLIPS, 100, 80, Draw(0.79, 0.1)) == ["sfx_ads/ad.mp4"]
    assert pick(CLIPS, 100, 80, Draw(0.80, 0.1)) == ["general.mp3"]
    assert pick(["general.mp3"], 100, 100) == ["general.mp3"]
    assert pick(["sfx_ads/ad.mp4"], 0, 0) == ["sfx_ads/ad.mp4"]
    assert pick([], 100, 100) == []


def test_independent_draws_respect_both_percentages():
    assert pick(CLIPS, 75, 80, Draw(0.79, 0.74)) == ["sfx_ads/ad.mp4"]
    assert pick(CLIPS, 75, 80, Draw(0.79, 0.94)) == ["general.mp4"]
    assert pick(CLIPS, 75, 80, Draw(0.80, 0.10)) == ["general.mp3"]
    assert pick(CLIPS, 25, 50, Draw(0.49, 0.49)) == ["sfx_ads/ad.mp4"]
    assert pick(CLIPS, 25, 50, Draw(0.49, 0.50)) == ["general.mp4"]


def test_selected_pool_preserves_weighted_duplicates():
    rows = ["general.mp3", "general.mp4", "general.mp4", "sfx_ads/ad.mp4"]
    assert pick(rows, 0, 100) == ["general.mp4", "general.mp4"]
