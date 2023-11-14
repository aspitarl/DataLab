# -*- coding: utf-8 -*-
#
# Licensed under the terms of the BSD 3-Clause
# (see cdlapp/LICENSE for details)

"""
Circular ROI test
"""

# pylint: disable=invalid-name  # Allows short reference names like x, y, ...
# guitest: show

import numpy as np
from skimage import draw

from cdlapp.env import execenv
from cdlapp.obj import RoiDataGeometries, create_image
from cdlapp.tests import test_cdl_app_context
from cdlapp.tests.features.common.roi_app import print_obj_shapes


def create_test_image_with_roi(roi_geometry: RoiDataGeometries):
    """Create test image with ROIs"""
    data = np.zeros((500, 750), dtype=np.uint16)
    xc, yc, r = 500, 200, 100
    rr, cc = draw.disk((yc, xc), r)
    data[rr, cc] = 10000
    data[yc + r - 20 : yc + r, xc + r - 30 : xc + r - 10] = 50000
    if roi_geometry is RoiDataGeometries.RECTANGLE:
        roi = [xc - r, yc - r, xc + r, yc + r]
        geom = "Rectangular"
    else:
        roi = [xc - r, yc, xc + r, yc]
        geom = "Circular"
    ima = create_image(f"{geom} ROI test image", data)
    ima.roi = np.array([roi], int)
    return ima


def test():
    """Run circular ROI application test scenario"""
    with test_cdl_app_context() as win:
        execenv.print("Circular ROI test:")
        panel = win.imagepanel
        for geometry in RoiDataGeometries:
            ima = create_test_image_with_roi(geometry)
            panel.add_object(ima)
            print_obj_shapes(ima)
            panel.processor.compute_stats()
            panel.processor.compute_centroid()


if __name__ == "__main__":
    test()
