# -*- coding: utf-8 -*-
#
# Licensed under the terms of the BSD 3-Clause
# (see cdlapp/LICENSE for details)

"""
Profiling
"""

# guitest: skip

from cdlapp.env import execenv
from cdlapp.tests import test_cdl_app_context


def test():
    """Profiling test"""
    execenv.unattended = True
    with test_cdl_app_context() as win:
        win.open_h5_files(
            [
                "C:/Dev/Projets/X-GRID_data/Projets_Oasis/XGRID5/"
                "VS000001-blobs_doh_profiling.h5"
            ],
            import_all=True,
        )


if __name__ == "__main__":
    test()
