import numpy as np


def test_fai_threshold_does_not_turn_missing_pixels_into_bloom():
    fai = np.array([0.01, np.nan, -0.01])
    valid = np.array([True, False, True])
    assert (valid & (fai > 0.004)).tolist() == [True, False, False]
