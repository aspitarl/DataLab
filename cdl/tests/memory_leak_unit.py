# -*- coding: utf-8 -*-
#
# Licensed under the terms of the BSD 3-Clause or the CeCILL-B License
# (see cdl/__init__.py for details)

"""
Memory leak test

DataLab application memory leak test.
"""

import os

import numpy as np
import psutil

from cdl.env import execenv
from cdl.tests.embedded1_unit import HostWindow
from cdl.utils.qthelpers import qt_app_context
from cdl.utils.vistools import view_curves

SHOW = True  # Show test in GUI-based test launcher


def memory_leak_test(iterations=100):
    """Test for memory leak"""
    with qt_app_context():
        proc = psutil.Process(os.getpid())
        mainview = HostWindow()
        mainview.show()
        memlist = []
        for i in range(iterations):
            mainview.init_cdl()
            mainview.cdl.close()
            # mainview.cdl.destroy()
            mainview.cdl = None
            # QApplication.processEvents()
            # import time; time.sleep(2)
            # QApplication.processEvents()
            memdata = proc.memory_info().vms / 1024**2
            memlist.append(memdata)
            execenv.print(i + 1, ":", memdata, "MB")
        view_curves(
            np.array(memlist),
            title="Memory leak test for DataLab application",
            ylabel="Memory (MB)",
        )


if __name__ == "__main__":
    memory_leak_test()
