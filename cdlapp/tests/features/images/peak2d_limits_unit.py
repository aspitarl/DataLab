# -*- coding: utf-8 -*-
#
# Licensed under the terms of the BSD 3-Clause
# (see cdlapp/LICENSE for details)

"""
Image peak detection test: testing algorithm limits
"""

# pylint: disable=invalid-name  # Allows short reference names like x, y, ...
# guitest: skip

from guidata.qthelpers import qt_app_context

from cdlapp.algorithms.image import get_2d_peaks_coords
from cdlapp.env import execenv
from cdlapp.tests.data import get_peak2d_data
from cdlapp.tests.features.images.peak2d_unit import exec_image_peak_detection_func


def peak2d_limit_test():
    """2D peak detection test"""
    with qt_app_context():
        execenv.print("Testing peak detection algorithm with random generated data:")
        for idx in range(100):
            execenv.print(f"  Iteration #{idx:02d}: ", end="")
            generated_data = get_peak2d_data(multi=True)
            coords = get_2d_peaks_coords(generated_data)
            if coords.shape[0] != 4:
                execenv.print(f"KO - {coords.shape[0]}/4 peaks were detected")
                exec_image_peak_detection_func(generated_data)
            else:
                execenv.print("OK")
        # Showing results for last generated sample
        exec_image_peak_detection_func(generated_data)


if __name__ == "__main__":
    peak2d_limit_test()
