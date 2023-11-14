# -*- coding: utf-8 -*-
#
# Licensed under the terms of the BSD 3-Clause
# (see cdlapp/LICENSE for details)

"""
DataLab settings test
"""

# guitest: show

from guidata.qthelpers import qt_app_context

from cdlapp.core.gui.settings import edit_settings
from cdlapp.env import execenv


def test_edit_settings():
    """Test edit settings"""
    with qt_app_context():
        changed = edit_settings(None)
        execenv.print(changed)


if __name__ == "__main__":
    test_edit_settings()
