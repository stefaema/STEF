from shared import film_formats as ff


def test_symmetric_formats_have_equal_margins():
    symmetric = (
        ff.FILM_35MM_SILENT,
        ff.FILM_35MM_SOUND,
        ff.FILM_16MM_SILENT,
    )
    for film_format in symmetric:
        assert film_format.guide_side_margin == film_format.opposite_side_margin


def test_super16_frame_is_wider_than_standard_16():
    assert ff.FILM_SUPER16.frame_width > ff.FILM_16MM_SILENT.frame_width


def test_symmetric_formats_mirror_their_band_start():
    symmetric = (
        ff.FILM_35MM_SILENT,
        ff.FILM_35MM_SOUND,
        ff.FILM_16MM_SILENT
    )
    for film_format in symmetric:
        assert film_format.opposite_side_start == -film_format.guide_side_start


def test_super16_opposite_margin_is_thinner_than_the_guide_side():
    assert 0 < ff.FILM_SUPER16.opposite_side_margin < ff.FILM_SUPER16.guide_side_margin


def test_band_finishes_at_the_film_edge():
    film_format = ff.FILM_35MM_SILENT
    assert film_format.guide_side_band is not None
    assert film_format.opposite_side_band is not None
    _, guide_finish = film_format.guide_side_band
    _, opposite_finish = film_format.opposite_side_band
    assert guide_finish == film_format.width / 2
    assert opposite_finish == -film_format.width / 2


def test_zero_margin_has_no_usable_band():
    no_margin = ff.FilmFormat(
        width=10.0,
        frame_width=10.0,
        frame_height=5.0,
        guide_side_margin=0.0,
        opposite_side_margin=0.0,
        has_sound=False,
    )
    assert no_margin.guide_side_band is None
    assert no_margin.opposite_side_band is None


def test_frame_fits_within_film_width():
    every_format = (
        ff.FILM_35MM_SILENT,
        ff.FILM_35MM_SOUND,
        ff.FILM_16MM_SILENT,
        ff.FILM_16MM_SOUND,
        ff.FILM_SUPER16,
        ff.FILM_SUPER8,
    )
    for film_format in every_format:
        margins = film_format.guide_side_margin + film_format.opposite_side_margin
        assert film_format.frame_width + margins <= film_format.width
