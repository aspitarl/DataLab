# Copyright (c) DataLab Platform Developers, BSD 3-Clause license, see LICENSE file.

"""
DataLab Text Import Wizard
--------------------------

The DataLab Import Wizard is a tool for importing data from a text source:

- Clipboard
- File (csv, txt, etc.)

It is based on the DataLab Wizard widget, which is a widget that guides the user
through a series of steps to complete a task. It is implemented as a series of
pages, each of which is a separate widget.
"""

from __future__ import annotations

import io
import os.path as osp
from itertools import islice
from typing import TYPE_CHECKING

import guidata.dataset as gds
import guidata.dataset.qtwidgets as gdq
import numpy as np
import pandas as pd
from guidata.configtools import get_icon
from guidata.widgets.codeeditor import CodeEditor
from plotpy.plot import PlotOptions, PlotWidget
from qtpy import QtCore as QC
from qtpy import QtGui as QG
from qtpy import QtWidgets as QW

from cdl.config import Conf, _
from cdl.core.io.signal.funcs import get_labels_units_from_dataframe
from cdl.core.model.signal import CURVESTYLES
from cdl.obj import ImageObj, SignalObj, create_image, create_signal
from cdl.utils.qthelpers import create_progress_bar
from cdl.widgets.wizard import Wizard, WizardPage

if TYPE_CHECKING:
    from plotpy.items import CurveItem, MaskedImageItem
    from plotpy.plot import BasePlot
    from qtpy.QtWidgets import QWidget


def count_lines(filename: str) -> int:
    """Count the number of lines in a file

    Args:
        filename: File name

    Returns:
        The number of lines in the file
    """
    with open(filename, "r") as file:
        line_count = sum(1 for line in file)
    return line_count


def read_first_n_lines(filename: str, n: int = 100000) -> str:
    """Read the first n lines of a file

    Args:
        filename: File name
        n: Number of lines to read

    Returns:
        The first n lines of the file
    """
    with open(filename, "r", encoding="utf-8") as file:
        lines = list(islice(file, n))
    return "".join(lines)


class SourceParam(gds.DataSet):
    """Source parameters dataset"""

    def __init__(self, source_page: SourcePage) -> None:
        super().__init__()
        self.source_page = source_page

    def source_callback(self, item: gds.ChoiceItem, value: str) -> None:
        """Source callback"""
        if value == "clipboard":
            is_valid = bool(QW.QApplication.clipboard().text())
        else:
            is_valid = self.path is not None and osp.isfile(self.path)
        self.source_page.set_valid(is_valid)

    def file_callback(self, item: gds.FileOpenItem, value: str | None) -> None:
        """File callback"""
        self.source_page.set_valid(value is not None and osp.isfile(value))

    _prop = gds.GetAttrProp("choice")
    source = (
        gds.ChoiceItem(
            _("Source"),
            [("clipboard", _("Clipboard")), ("file", _("File"))],
            default="file",
            help=_("Source of the data"),
            radio=True,
        )
        .set_prop("display", store=_prop)
        .set_prop("display", callback=source_callback)
    )
    path = (
        gds.FileOpenItem(
            _("File"),
            formats=("txt", "csv", "dat", "asc"),
            check=False,
            help=_("File containing the data"),
        )
        .set_prop("display", active=gds.FuncProp(_prop, lambda x: x == "file"))
        .set_prop("display", callback=file_callback)
    )
    _bg = gds.BeginGroup(_("Preview parameters"))
    preview_max_rows = gds.IntItem(
        _("Maximum Number of Rows"),
        default=100000,
        min=1,
        check=False,
        help=_("Maximum number of rows to display"),
    ).set_prop("display", active=gds.FuncProp(_prop, lambda x: x == "file"))
    _eg = gds.EndGroup(_("Preview parameters"))


class SourcePage(WizardPage):
    """Source page"""

    def __init__(self) -> None:
        super().__init__()
        self.__text = ""
        self.__path = ""
        self.__loaded_partially = True
        self.set_title(_("Source"))
        self.set_subtitle(_("Select the source of the data:"))

        self.param_widget = gdq.DataSetEditGroupBox(
            _("Source Parameters"), SourceParam, show_button=False, source_page=self
        )
        self.param = self.param_widget.dataset
        self.add_to_layout(self.param_widget)

        self.add_stretch()
        self.set_valid(False)

    def get_source_path(self) -> str | None:
        """Return the selected source path, or None if clipboard is selected"""
        return self.param.path if self.param.source == "file" else None

    def get_source_text(self, preview: bool) -> str:
        """Return the source text"""
        if not self.__loaded_partially or preview:
            return self.__text
        with open(self.__path, "r", encoding="utf-8") as file:
            self.__text = file.read()
        self.__loaded_partially = False
        return self.__text

    def validate_page(self) -> bool:
        """Validate the page"""
        self.__text = ""
        self.param_widget.set()
        if self.param.source == "file":
            self.__path = self.get_source_path()
            if self.__path is not None and osp.isfile(self.__path):
                try:
                    self.__text = read_first_n_lines(
                        self.__path, n=self.param.preview_max_rows
                    )
                except Exception:  # pylint:disable=broad-except
                    return False
                self.__loaded_partially = (
                    count_lines(self.__path) > self.param.preview_max_rows
                )
            else:
                return False
        else:
            self.__text = QW.QApplication.clipboard().text()
            self.__loaded_partially = False
        return bool(self.__text)


class BaseImportParam(gds.DataSet):
    """Import parameters dataset"""

    delimiter_choice = gds.ChoiceItem(
        _("Delimiter"),
        [
            (",", ","),
            (";", ";"),
            ("\t", _("Tab")),
            (" ", _("Space")),
        ],
        help=_("Column delimiter character"),
    )
    comment_char = gds.StringItem(
        _("Comments"),
        default="#",
        help=_("Character that indicates a comment line"),
    ).set_pos(col=1)
    skip_rows = gds.IntItem(
        _("Rows to Skip"),
        default=0,
        help=_(
            "Number of rows to skip at the beginning of the file (including comments)"
        ),
    ).set_pos(col=2)
    max_rows = gds.IntItem(
        _("Max. nb of rows"),
        default=None,
        min=1,
        check=False,
        help=_("Maximum number of rows to import"),
    )
    header = gds.ChoiceItem(
        _("Header"),
        ((None, _("None")), ("infer", _("Infer")), (0, _("First row"))),
        default="infer",
        help=_("Row index to use as the column names"),
    ).set_pos(col=1)
    transpose = gds.BoolItem(
        _("Transpose"),
        default=False,
        help=_("Transpose the data (swap rows and columns)"),
    ).set_pos(col=2)


class SignalImportParam(BaseImportParam):
    """Signal import parameters dataset"""

    VALID_DTYPES_STRLIST = SignalObj.get_valid_dtypenames()

    dtype_str = gds.ChoiceItem(
        _("Data type"),
        list(zip(VALID_DTYPES_STRLIST, VALID_DTYPES_STRLIST)),
        help=_("Output signal data type."),
        default="float64",
    )
    first_col_is_x = gds.BoolItem(
        _("First Column is X"),
        default=True,
        help=_(
            _(
                "First column contains the X values\n"
                "(ignored if there is only one column)"
            )
        ),
    ).set_pos(col=1)


class ImageImportParam(BaseImportParam):
    """Image import parameters dataset"""

    VALID_DTYPES_STRLIST = ImageObj.get_valid_dtypenames()

    dtype_str = gds.ChoiceItem(
        _("Data type"),
        list(zip(VALID_DTYPES_STRLIST, VALID_DTYPES_STRLIST)),
        help=_("Output image data type."),
        default="uint16",
    )


class ArrayModel(QC.QAbstractTableModel):
    """Array model

    Args:
        parent: Parent widget
        data: Data array
        horizontal_headers: Horizontal headers
    """

    # pylint: disable=invalid-name

    def __init__(
        self,
        parent: QWidget,
        data: np.ndarray,
        horizontal_headers: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.__data = data
        self.__horizontal_headers = horizontal_headers

    def rowCount(self, _parent: QC.QModelIndex) -> int:
        """Return the row count
        (reimplement the `QC.QAbstractTableModel` method)"""
        return self.__data.shape[0]

    def columnCount(self, _parent: QC.QModelIndex) -> int:
        """Return the column count
        (reimplement the `QC.QAbstractTableModel` method)"""
        return self.__data.shape[1]

    def data(self, index: QC.QModelIndex, role: int) -> str | None:
        """Return the data
        (reimplement the `QC.QAbstractTableModel` method)"""
        if role == QC.Qt.DisplayRole:
            return str(self.__data[index.row(), index.column()])
        return None

    def headerData(self, section: int, orientation: int, role: int) -> str | None:
        """Return the header data
        (reimplement the `QC.QAbstractTableModel` method)"""
        if (
            role == QC.Qt.DisplayRole
            and orientation == QC.Qt.Horizontal
            and self.__horizontal_headers is not None
        ):
            return self.__horizontal_headers[section]
        return super().headerData(section, orientation, role)


class ArrayView(QW.QTableView):
    """Array view

    Args:
        parent: Parent widget
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setShowGrid(True)
        self.setAlternatingRowColors(True)

    def set_data(
        self, data: np.ndarray, horizontal_headers: list[str] | None = None
    ) -> None:
        """Set the data

        Args:
            data: Data array
            horizontal_headers: Horizontal headers
        """
        model = ArrayModel(self, data, horizontal_headers)
        self.setModel(model)


class PreviewWidget(QW.QWidget):
    """Widget showing the raw data, the prefiltered data and a preview of the data"""

    def __init__(self, parent: QWidget, destination: str) -> None:
        super().__init__(parent)
        self.destination = destination
        main_layout = QW.QVBoxLayout()
        self.setLayout(main_layout)

        self.tabwidget = tw = QW.QTabWidget()
        self._raw_text_edit = self.create_editor()
        tw.addTab(
            self._raw_text_edit, get_icon("libre-gui-questions.svg"), _("Raw Data")
        )
        self._preview_table = ArrayView(self)
        self._preview_table.setFont(self._raw_text_edit.font())
        self._preview_table.setEditTriggers(QW.QAbstractItemView.NoEditTriggers)
        tw.addTab(self._preview_table, get_icon("table.svg"), _("Preview"))
        main_layout.addWidget(tw)

    def create_editor(self) -> CodeEditor:
        """Create a code editor"""
        editor = CodeEditor()
        font = editor.font()
        font.setPointSize(font.pointSize() - 2)
        editor.setFont(font)
        editor.setReadOnly(True)
        editor.setWordWrapMode(QG.QTextOption.NoWrap)
        return editor

    def set_raw_data(self, data: str) -> None:
        """Set the raw data"""
        self._raw_text_edit.setPlainText(data)

    def __clear_preview_table(self, enable: bool) -> None:
        """Clear the preview table"""
        self._preview_table.setModel(None)
        self._preview_table.setEnabled(enable)
        idx = self.tabwidget.indexOf(self._preview_table)
        icon_name = "table.svg" if enable else "table_unavailable.svg"
        self.tabwidget.setTabIcon(idx, get_icon(icon_name))
        if enable:
            self.tabwidget.setCurrentIndex(idx)

    def set_preview_data(
        self, df: pd.DataFrame | None, first_col_is_x: bool | None
    ) -> None:
        """Set the preview data"""
        data = df.to_numpy() if df is not None else None
        if data is None or len(data.shape) not in (1, 2) or data.size == 0:
            self.__clear_preview_table(False)
        else:
            self.__clear_preview_table(True)
            if self.destination == "signal":
                assert first_col_is_x is not None
                h_headers = df.columns.tolist()
            else:
                h_headers = None
            self._preview_table.set_data(data, horizontal_headers=h_headers)


def str_to_dataframe(
    raw_data: str,
    param: SignalImportParam | ImageImportParam,
) -> pd.DataFrame | None:
    """Convert raw data to a DataFrame

    Args:
        raw_data: Raw data
        param: Import parameters

    Returns:
        The DataFrame, or None if the conversion failed
    """
    if not raw_data:
        return None
    file_obj = io.StringIO(raw_data)
    dtype = np.dtype(param.dtype_str)
    try:
        df = pd.read_csv(
            file_obj,
            delimiter=param.delimiter_choice,
            skiprows=param.skip_rows,
            nrows=param.max_rows,
            comment=param.comment_char,
            dtype=dtype,
            header=param.header,
        )
    except Exception:  # pylint:disable=broad-except
        return None
    # Remove rows and columns where all values are NaN in the DataFrame:
    df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")
    if param.transpose:
        return df.T
    return df


class DataPreviewPage(WizardPage):
    """Data preview page

    Args:
        destination: Destination type ('signal' or 'image')
    """

    def __init__(self, source_page: SourcePage, destination: str) -> None:
        super().__init__()
        self.__quick_update = False
        self.source_page = source_page
        self.destination = destination
        self.__preview_df: pd.DataFrame | None = None
        self.set_title(_("Data Preview"))
        self.set_subtitle(_("Preview and modify the import settings:"))

        self.param_widget = gdq.DataSetEditGroupBox(
            _("Import Parameters"),
            SignalImportParam if destination == "signal" else ImageImportParam,
        )
        self.param_widget.SIG_APPLY_BUTTON_CLICKED.connect(self.update_preview)
        self.param_widget.set_apply_button_state(False)
        self.param = self.param_widget.dataset
        self.add_to_layout(self.param_widget)

        self.preview_widget = PreviewWidget(self, destination)
        self.preview_widget.setSizePolicy(
            QW.QSizePolicy(QW.QSizePolicy.Expanding, QW.QSizePolicy.Expanding)
        )
        self.add_to_layout(self.preview_widget)

    def get_dataframe(self) -> pd.DataFrame | None:
        """Return the data

        Returns:
            The data frame, or None if the data could not be converted
        """
        source_text = self.source_page.get_source_text(preview=False)
        return str_to_dataframe(source_text, self.param)

    def update_preview(self) -> None:
        """Update the preview"""
        # Raw data
        raw_data = self.source_page.get_source_text(preview=True)
        self.preview_widget.set_raw_data(raw_data)
        # Preview
        df = str_to_dataframe(raw_data, self.param)
        first_col_is_x = None
        if isinstance(self.param, SignalImportParam):
            first_col_is_x = self.param.first_col_is_x
        if not self.__quick_update:
            self.preview_widget.set_preview_data(df, first_col_is_x=first_col_is_x)
        self.__preview_df = df
        self.set_valid(df is not None)

    def initialize_page(self) -> None:
        """Initialize the page"""
        super().initialize_page()
        self.param_widget.get()
        self.update_preview()

    def validate_page(self) -> bool:
        """Validate the page"""
        self.__quick_update = True
        self.param_widget.set()
        self.__quick_update = False
        if self.destination == "signal":
            nb_sig = len(self.__preview_df.columns)
            if self.param.first_col_is_x:
                nb_sig -= 1
            if (
                nb_sig > 20
                and QW.QMessageBox.warning(
                    self,
                    _("Warning"),
                    _(
                        "The number of signals to import is very high (%d).\n"
                        "This may be an error.\n\n"
                        "Are you sure you want to continue?"
                    )
                    % nb_sig,
                    QW.QMessageBox.Yes | QW.QMessageBox.No,
                )
                == QW.QMessageBox.No
            ):
                return False
        return super().validate_page()


class GraphicalRepresentationPage(WizardPage):
    """Graphical representation page"""

    def __init__(self, data_page: DataPreviewPage, destination: str) -> None:
        super().__init__()
        self.__objitmlist: list[
            tuple[SignalObj | ImageObj, CurveItem | MaskedImageItem]
        ] = []
        self.set_title(_("Graphical Representation"))
        self.set_subtitle(_("Graphical representation of the imported data"))
        self.data_page = data_page
        self.destination = destination
        layout = QW.QVBoxLayout()
        instruction = QW.QLabel(
            _("Unselect the %s that you do not want to import:")
            % (_("signals") if destination == "signal" else _("images"))
        )
        layout.addWidget(instruction)
        plot_type = "curve" if destination == "signal" else "image"
        self.plot_widget = PlotWidget(
            self,
            toolbar=True,
            options=PlotOptions(
                type=plot_type,
                show_itemlist=True,
                show_contrast=True,
            ),
        )
        plot = self.plot_widget.get_plot()
        plot.SIG_ITEMS_CHANGED.connect(self.items_changed)
        layout.addWidget(self.plot_widget)
        self.add_to_layout(layout)

    def items_changed(self, _plot: BasePlot) -> None:
        """Item selection changed"""
        objs = self.get_objs()
        self.set_valid(len(objs) > 0)

    def get_objs(self) -> list[SignalObj | ImageObj]:
        """Return the objects"""
        return [obj for obj, item in self.__objitmlist if item.isVisible()]

    def initialize_page(self) -> None:
        """Initialize the page"""
        df = self.data_page.get_dataframe()
        assert df is not None
        data = df.to_numpy()
        param = self.data_page.param
        plot = self.plot_widget.get_plot()
        plot.del_all_items()
        if self.destination == "signal":
            xydata = data.T
            x = np.arange(len(xydata[0]))
            if len(xydata) == 1:
                obj = create_signal("", x=x, y=xydata[0])
                with CURVESTYLES.suspend():
                    item = obj.make_item()
                plot.add_item(item)
                self.__objitmlist = [(obj, item)]
            else:
                xlabel, ylabels, xunit, yunits = get_labels_units_from_dataframe(df)
                if param.first_col_is_x:
                    x = xydata[0]
                    plot.set_axis_title("bottom", xlabel)
                self.__objitmlist = []
                zorder = 1000
                with create_progress_bar(
                    self, _("Adding data to the plot"), max_=len(xydata) - 1
                ) as progress:
                    for ycol in range(1 if param.first_col_is_x else 0, len(xydata)):
                        progress.setValue(ycol - 1)
                        if progress.wasCanceled():
                            break
                        yidx = ycol if param.first_col_is_x else ycol - 1
                        obj = create_signal(
                            ylabels[ycol - 1],
                            x=x,
                            y=xydata[yidx],
                            labels=(xlabel, ylabels[ycol - 1]),
                            units=(xunit, yunits[ycol - 1]),
                        )
                        with CURVESTYLES.suspend():
                            item = obj.make_item()
                        plot.add_item(item, z=zorder)
                        zorder -= 1
                        self.__objitmlist.append((obj, item))
                        QW.QApplication.processEvents()
        else:
            obj = create_image("", data)
            item = obj.make_item()
            plot.add_item(item)
            self.__objitmlist = [(obj, item)]
            plot.set_active_item(item)
            item.unselect()
        plot.do_autoscale()
        self.items_changed(plot)
        return super().initialize_page()

    def validate_page(self) -> bool:
        """Validate the page"""
        objs = self.get_objs()
        if len(objs) == 0:
            return False
        return super().validate_page()


class SignalParam(gds.DataSet):
    """Signal parameters dataset"""

    title = gds.StringItem(_("Title"), default="").set_pos(col=0, colspan=2)
    xlabel = gds.StringItem(_("X label"), default="")
    ylabel = gds.StringItem(_("Y label"), default="").set_pos(col=1)
    xunit = gds.StringItem(_("X unit"), default="")
    yunit = gds.StringItem(_("Y unit"), default="").set_pos(col=1)


class ImageParam(gds.DataSet):
    """Image parameters dataset"""

    title = gds.StringItem(_("Title"), default="").set_pos(col=0, colspan=3)
    xlabel = gds.StringItem(_("X label"), default="")
    ylabel = gds.StringItem(_("Y label"), default="").set_pos(col=1)
    zlabel = gds.StringItem(_("Z label"), default="").set_pos(col=2)
    xunit = gds.StringItem(_("X unit"), default="")
    yunit = gds.StringItem(_("Y unit"), default="").set_pos(col=1)
    zunit = gds.StringItem(_("Z unit"), default="").set_pos(col=2)


def update_dataset_non_empty_values(dest: gds.DataSet, source: gds.DataSet) -> None:
    """Update the destination dataset from the non-empty values of the source dataset

    Args:
        dest: Destination dataset
        source: Source dataset
    """
    for item in source.get_items():
        key = item.get_name()
        value = getattr(source, key)
        if value in (None, "") and hasattr(dest, key):
            setattr(dest, key, value)


class LabelsPage(WizardPage):
    """Labels page"""

    def __init__(
        self,
        source_page: SourcePage,
        plot_page: GraphicalRepresentationPage,
        destination: str,
    ) -> None:
        super().__init__()
        self.set_title(_("Labels and units"))
        self.set_subtitle(_("Set the labels and units for the imported data"))
        self.source_page = source_page
        self.plot_page = plot_page
        self.param_widget = gdq.DataSetEditGroupBox(
            _("Parameters"),
            SignalParam if destination == "signal" else ImageParam,
            show_button=False,
        )
        self.param = self.param_widget.dataset
        label = QW.QLabel(
            _(
                "The following title, labels and units will be applied to the data."
                "<br><br><i><u>Note</u>: "
                "Leave empty the labels and units to keep the default values "
                "(i.e. the values which were inferred from the data).</i>"
            )
        )
        self.add_to_layout(label)
        self.add_to_layout(self.param_widget)
        self.add_stretch()

    def get_objs(self) -> list[SignalObj | ImageObj]:
        """Return the objects"""
        objs = self.plot_page.get_objs()
        for idx, obj in enumerate(objs):
            update_dataset_non_empty_values(obj, self.param)
            if len(objs) > 1:
                obj.title = f"{obj.title} {idx + 1:02d}"
        return objs

    def initialize_page(self) -> None:
        """Initialize the page"""
        path = self.source_page.get_source_path()
        if path is None:
            path = _("clipboard")
        else:
            path = osp.basename(path)
        self.param.title = _("Imported from:") + " " + path
        self.param_widget.get()
        return super().initialize_page()

    def validate_page(self) -> bool:
        """Validate the page"""
        self.param_widget.set()
        return super().validate_page()


class TextImportWizard(Wizard):
    """Text data import wizard

    Args:
        destination: Destination type ('signal' or 'image')
    """

    def __init__(self, destination: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        assert destination in ("signal", "image")
        self.setWindowTitle(_("DataLab Import Wizard"))
        self.source_page = SourcePage()
        self.add_page(self.source_page)
        self.data_page = DataPreviewPage(self.source_page, destination)
        self.add_page(self.data_page)
        self.plot_page = GraphicalRepresentationPage(self.data_page, destination)
        self.add_page(self.plot_page)
        self.labels_page = LabelsPage(self.source_page, self.plot_page, destination)
        self.add_page(self.labels_page, last_page=True)

    def get_objs(self) -> list[SignalObj | ImageObj]:
        """Return the objects"""
        return self.labels_page.get_objs()
