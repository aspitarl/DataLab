# -*- coding: utf-8 -*-
#
# Licensed under the terms of the BSD 3-Clause
# (see cdlapp/LICENSE for details)

"""
Signal FFT application test.
"""

# pylint: disable=invalid-name  # Allows short reference names like x, y, ...
# guitest: show

from cdlapp.obj import SignalTypes, create_signal_from_param, new_signal_param
from cdlapp.tests import test_cdl_app_context


def test():
    """FFT application test."""
    with test_cdl_app_context() as win:
        panel = win.signalpanel
        newparam = new_signal_param(stype=SignalTypes.COSINUS, size=10000)
        s1 = create_signal_from_param(newparam)
        panel.add_object(s1)
        panel.processor.compute_fft()
        panel.processor.compute_ifft()


if __name__ == "__main__":
    test()
