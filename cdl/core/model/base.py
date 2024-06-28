# Copyright (c) DataLab Platform Developers, BSD 3-Clause license, see LICENSE file.

"""
DataLab Datasets
"""

# pylint: disable=invalid-name  # Allows short reference names like x, y, ...

from __future__ import annotations

import abc
import enum
import json
import sys
from collections.abc import Callable, Iterable
from copy import deepcopy
from typing import TYPE_CHECKING, Any, Literal

import guidata.dataset as gds
import numpy as np
import pandas as pd
from guidata.configtools import get_font
from guidata.dataset import update_dataset
from guidata.io import JSONReader, JSONWriter
from plotpy.builder import make
from plotpy.io import load_items, save_items
from plotpy.items import (
    AbstractLabelItem,
    AnnotatedPoint,
    AnnotatedSegment,
    AnnotatedShape,
    LabelItem,
)

from cdl.algorithms import coordinates
from cdl.algorithms.datatypes import is_integer_dtype
from cdl.config import PLOTPY_CONF, Conf, _

if TYPE_CHECKING:
    from plotpy.items import (
        AbstractShape,
        AnnotatedCircle,
        AnnotatedEllipse,
        AnnotatedRectangle,
        CurveItem,
        Marker,
        MaskedImageItem,
        PolygonShape,
    )
    from plotpy.styles import AnnotationParam, ShapeParam

ROI_KEY = "_roi_"
ANN_KEY = "_ann_"


def deepcopy_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Deepcopy metadata, except keys starting with "_" (private keys)
    with the exception of "_roi_" and "_ann_" keys."""
    mdcopy = deepcopy(metadata)
    for key, value in metadata.items():
        rshape = ResultShape.from_metadata_entry(key, value)
        if rshape is None and key.startswith("_") and key not in (ROI_KEY, ANN_KEY):
            mdcopy.pop(key)
    return mdcopy


@enum.unique
class Choices(enum.Enum):
    """Object associating an enum to guidata.dataset.ChoiceItem choices"""

    # Reimplement enum.Enum method as suggested by Python documentation:
    # https://docs.python.org/3/library/enum.html#enum.Enum._generate_next_value_
    # Here, it is only needed for ImageDatatypes (see core/model/image.py).
    # pylint: disable=unused-argument,no-self-argument,no-member
    def _generate_next_value_(name, start, count, last_values):
        return name.lower()

    @classmethod
    def get_choices(cls):
        """Return tuple of (key, value) choices to be used as parameter of
        guidata.dataset.ChoiceItem"""
        return tuple((member, member.value) for member in cls)


class BaseProcParam(gds.DataSet):
    """Base class for processing parameters"""

    def __init__(self, title=None, comment=None, icon=""):
        super().__init__(title, comment, icon)
        self.set_global_prop("data", min=None, max=None)

    def apply_integer_range(self, vmin, vmax):  # pylint: disable=unused-argument
        """Do something in case of integer min-max range"""

    def apply_float_range(self, vmin, vmax):  # pylint: disable=unused-argument
        """Do something in case of float min-max range"""

    def set_from_datatype(self, dtype):
        """Set min/max range from NumPy datatype"""
        if is_integer_dtype(dtype):
            info = np.iinfo(dtype)
            self.apply_integer_range(info.min, info.max)
        else:
            info = np.finfo(dtype)
            self.apply_float_range(info.min, info.max)
        self.set_global_prop("data", min=info.min, max=info.max)


class BaseRandomParam(BaseProcParam):
    """Random signal/image parameters"""

    seed = gds.IntItem(_("Seed"), default=1)


class UniformRandomParam(BaseRandomParam):
    """Uniform-law random signal/image parameters"""

    def apply_integer_range(self, vmin, vmax):
        """Do something in case of integer min-max range"""
        self.vmin, self.vmax = vmin, vmax

    vmin = gds.FloatItem(
        "V<sub>min</sub>", default=-0.5, help=_("Uniform distribution lower bound")
    )
    vmax = gds.FloatItem(
        "V<sub>max</sub>", default=0.5, help=_("Uniform distribution higher bound")
    ).set_pos(col=1)


class NormalRandomParam(BaseRandomParam):
    """Normal-law random signal/image parameters"""

    DEFAULT_RELATIVE_MU = 0.1
    DEFAULT_RELATIVE_SIGMA = 0.02

    def apply_integer_range(self, vmin, vmax):
        """Do something in case of integer min-max range"""
        delta = vmax - vmin
        self.mu = int(self.DEFAULT_RELATIVE_MU * delta + vmin)
        self.sigma = int(self.DEFAULT_RELATIVE_SIGMA * delta)

    mu = gds.FloatItem(
        "μ", default=DEFAULT_RELATIVE_MU, help=_("Normal distribution mean")
    )
    sigma = gds.FloatItem(
        "σ",
        default=DEFAULT_RELATIVE_SIGMA,
        help=_("Normal distribution standard deviation"),
    ).set_pos(col=1)


@enum.unique
class ShapeTypes(enum.Enum):
    """Shape types for image metadata"""

    # Reimplement enum.Enum method as suggested by Python documentation:
    # https://docs.python.org/3/library/enum.html#enum.Enum._generate_next_value_
    # pylint: disable=unused-argument,no-self-argument,no-member
    def _generate_next_value_(name, start, count, last_values):
        return f"_{name.lower()[:3]}_"

    #: Rectangle shape
    RECTANGLE = enum.auto()
    #: Circle shape
    CIRCLE = enum.auto()
    #: Ellipse shape
    ELLIPSE = enum.auto()
    #: Segment shape
    SEGMENT = enum.auto()
    #: Marker shape
    MARKER = enum.auto()
    #: Point shape
    POINT = enum.auto()
    #: Polygon shape
    POLYGON = enum.auto()


def config_annotated_shape(
    item: AnnotatedShape, fmt: str, lbl: bool, option: str, cmp: bool | None = None
):
    """Configurate annotated shape.

    Args:
        item: Annotated shape item
        fmt: Format string
        lbl: Show label
        option: Shape style option (e.g. "shape/drag")
        cmp: Show computations
    """
    param: AnnotationParam = item.annotationparam
    param.format = fmt
    param.show_label = lbl
    if cmp is not None:
        param.show_computations = cmp

    if isinstance(item, AnnotatedSegment):
        item.label.labelparam.anchor = "T"
        item.label.labelparam.update_item(item.label)

    param.update_item(item)
    item.set_style("plot", option)


# TODO: [P3] Move this function as a method of plot items in PlotPy
def set_plot_item_editable(
    item: AbstractShape | AbstractLabelItem | AnnotatedShape, state
):
    """Set plot item editable state.

    Args:
        item: Plot item
        state: State
    """
    item.set_movable(state)
    item.set_resizable(state and not isinstance(item, AbstractLabelItem))
    item.set_rotatable(state and not isinstance(item, AbstractLabelItem))
    item.set_readonly(not state)
    item.set_selectable(state)


class BaseResult(abc.ABC):
    """Base class for results, i.e. objects returned by computation functions
    used by :py:class`cdl.core.gui.processor.base.BaseProcessor.compute_10` method.

    Args:
        title: result title
        category: result category
        array: result array (one row per ROI, first column is ROI index)
        labels: result labels (one label per column of result array)
    """

    PREFIX = ""  # To be overriden in children classes
    METADATA_ATTRS = ()  # To be overriden in children classes

    def __init__(
        self,
        title: str,
        array: np.ndarray,
        labels: list[str] | None = None,
    ) -> None:
        assert isinstance(title, str)
        self.title = title
        self.array = array
        self.xunit: str = ""
        self.yunit: str = ""
        self.__labels = labels
        self.check_array()

    @property
    @abc.abstractmethod
    def category(self) -> str:
        """Return result category"""

    def check_array(self) -> None:
        """Check if array attribute is valid

        Raises:
            AssertionError: invalid array
        """
        # Allow to pass a list of lists or a NumPy array.
        # For instance, the following are equivalent:
        #   array = [[1, 2], [3, 4]]
        #   array = np.array([[1, 2], [3, 4]])
        # Or, for only one line (one single result), the following are equivalent:
        #   array = [1, 2]
        #   array = [[1, 2]]
        #   array = np.array([[1, 2]])
        if isinstance(self.array, (list, tuple)):
            if isinstance(self.array[0], (list, tuple)):
                self.array = np.array(self.array)
            else:
                self.array = np.array([self.array])
        assert isinstance(self.array, np.ndarray)
        assert len(self.array.shape) == 2

    @property
    def labels(self) -> list[str] | None:
        """Return result labels (one label per column of result array)"""
        return self.__labels

    @property
    def headers(self) -> list[str] | None:
        """Return result headers (one header per column of result array)"""
        # Default implementation: return labels
        return self.__labels

    def to_dataframe(self) -> pd.DataFrame:
        """Return DataFrame from properties array"""
        return pd.DataFrame(self.shown_array, columns=list(self.headers))

    @property
    @abc.abstractmethod
    def shown_array(self) -> np.ndarray:
        """Return array of shown results, i.e. including complementary array (if any)

        Returns:
            Array of shown results
        """

    @property
    def raw_data(self):
        """Return raw data (array without ROI informations)"""
        return self.array[:, 1:]

    @property
    def key(self) -> str:
        """Return metadata key associated to result"""
        return self.PREFIX + self.title

    @classmethod
    def from_metadata_entry(cls, key: str, value: dict[str, Any]) -> BaseResult | None:
        """Create metadata shape object from (key, value) metadata entry"""
        if (
            isinstance(key, str)
            and key.startswith(cls.PREFIX)
            and isinstance(value, dict)
        ):
            try:
                title = key[len(cls.PREFIX) :]
                instance = cls(title, **value)
                return instance
            except (ValueError, TypeError):
                pass
        return None

    @classmethod
    def match(cls, key, value) -> bool:
        """Return True if metadata dict entry (key, value) is a metadata result"""
        return cls.from_metadata_entry(key, value) is not None

    def add_to(self, obj: BaseObj) -> None:
        """Add result to object metadata

        Args:
            obj: object (signal/image)
        """
        self.set_obj_metadata(obj)

    def set_obj_metadata(self, obj: BaseObj) -> None:
        """Set object metadata with properties

        Args:
            obj: object
        """
        obj.metadata[self.key] = {
            key: getattr(self, key) for key in self.METADATA_ATTRS
        }


class ResultProperties(BaseResult):
    """Object representing properties serializable in signal/image metadata.

    Result `array` is a NumPy 2-D array: each row is a list of properties, optionnally
    associated to a ROI (first column value).

    ROI index is starting at 0 (or is simply 0 if there is no ROI).

    Args:
        title: properties title
        array: properties array
        labels: properties labels (one label per column of result array)
        item_json: JSON string of label item associated to this obj

    .. note::

        The `array` argument can be a list of lists or a NumPy array. For instance,
        the following are equivalent:

        - ``array = [[1, 2], [3, 4]]``
        - ``array = np.array([[1, 2], [3, 4]])``

        Or for only one line (one single result), the following are equivalent:

        - ``array = [1, 2]``
        - ``array = [[1, 2]]``
        - ``array = np.array([[1, 2]])``
    """

    PREFIX = "_properties_"
    METADATA_ATTRS = ("array", "labels", "item_json")

    def __init__(
        self,
        title: str,
        array: np.ndarray,
        labels: list[str] | None,
        item_json: str = "",
    ) -> None:
        super().__init__(title, array, labels)
        if labels is not None:
            assert len(labels) == self.array.shape[1] - 1
        self.item_json = item_json  # JSON string of label item associated to this obj

    @property
    def category(self) -> str:
        """Return result category"""
        return _("Properties") + f" | {self.title}"

    @property
    def headers(self) -> list[str] | None:
        """Return result headers (one header per column of result array)"""
        # ResultProperties implementation: return labels without units or "=" sign
        return [label.split("=")[0].strip() for label in self.labels]

    @property
    def shown_array(self) -> np.ndarray:
        """Return array of shown results, i.e. including complementary array (if any)

        Returns:
            Array of shown results
        """
        return self.raw_data

    def add_to(self, obj: BaseObj) -> None:
        """Add result to object metadata

        Args:
            obj: object (signal/image)
        """
        item = self.create_label_item(obj)
        self.update_obj_metadata_from_item(obj, item)

    def update_obj_metadata_from_item(
        self, obj: BaseObj, item: LabelItem | None
    ) -> None:
        """Update object metadata with label item

        Args:
            obj: object
            item: label item
        """
        if item is not None:
            self.item_json = items_to_json([item])
        self.set_obj_metadata(obj)

    @property
    def label_contents(self) -> tuple[tuple[int, str], ...]:
        """Return label contents, i.e. a tuple of couples of (index, text)
        where index is the column of raw_data and text is the associated
        label format string"""
        return tuple(enumerate(self.labels))

    def create_label_item(self, obj: BaseObj) -> LabelItem | None:
        """Create label item

        Returns:
            Label item
        """
        text = ""
        for i_row in range(self.array.shape[0]):
            suffix = f"|ROI{i_row}" if i_row > 0 else ""
            text += f"<u>{self.title}{suffix}</u>:"
            for i_col, label in self.label_contents:
                # "label" may contains "<" and ">" characters which are interpreted
                # as HTML tags by the LabelItem. We must escape them.
                label = label.replace("<", "&lt;").replace(">", "&gt;")
                if "%" not in label:
                    label += " = %g"
                text += (
                    "<br>" + label.strip().format(obj) % self.shown_array[i_row, i_col]
                )
            if i_row < self.shown_array.shape[0] - 1:
                text += "<br><br>"
        item = make.label(text, "TL", (0, 0), "TL", title=self.title)
        font = get_font(PLOTPY_CONF, "plot", "label/properties/font")
        item.set_style("plot", "label/properties")
        item.labelparam.font.update_param(font)
        item.labelparam.update_item(item)
        return item

    def get_label_item(self) -> LabelItem | None:
        """Return label item associated to this result

        Returns:
            Label item
        """
        if self.item_json:
            item = json_to_items(self.item_json)[0]
            assert isinstance(item, LabelItem)
            return item
        return None


class ResultShape(ResultProperties):
    """Object representing a geometrical shape serializable in signal/image metadata.

    Result `array` is a NumPy 2-D array: each row is a result, optionnally associated
    to a ROI (first column value).

    ROI index is starting at 0 (or is simply 0 if there is no ROI).

    Args:
        title: result shape title
        array: shape coordinates (multiple shapes: one shape per row),
         first column is ROI index (0 if there is no ROI)
        shape: shape kind
        item_json: JSON string of label item associated to this obj
        add_label: if True, add a label item (and the geometrical shape) to plot
         (default to False)

    Raises:
        AssertionError: invalid argument

    .. note::

        The `array` argument can be a list of lists or a NumPy array. For instance,
        the following are equivalent:

        - ``array = [[1, 2], [3, 4]]``
        - ``array = np.array([[1, 2], [3, 4]])``

        Or for only one line (one single result), the following are equivalent:

        - ``array = [1, 2]``
        - ``array = [[1, 2]]``
        - ``array = np.array([[1, 2]])``
    """

    PREFIX = "_shapes_"
    METADATA_ATTRS = ("array", "shape", "item_json", "add_label")

    def __init__(
        self,
        title: str,
        array: np.ndarray,
        shape: Literal[
            "rectangle", "circle", "ellipse", "segment", "marker", "point", "polygon"
        ],
        item_json: str = "",
        add_label: bool = False,
    ) -> None:
        self.shape = shape
        try:
            self.shapetype = ShapeTypes[shape.upper()]
        except KeyError as exc:
            raise ValueError(f"Invalid shapetype {shape}") from exc
        self.add_label = add_label
        super().__init__(title, array, labels=None, item_json=item_json)

    @property
    def category(self) -> str:
        """Return result category"""
        return self.shape.upper()

    def check_array(self) -> None:
        """Check if array attribute is valid

        Raises:
            AssertionError: invalid array
        """
        super().check_array()
        if self.shapetype is ShapeTypes.POLYGON:
            # Polygon is a special case: the number of data columns is variable
            # (2 columns per point). So we only check if the number of columns
            # is odd, which means that the first column is the ROI index, followed
            # by an even number of data columns (flattened x, y coordinates).
            assert self.array.shape[1] % 2 == 1
        else:
            data_colnb = len(self.__get_coords_labels())
            # `data_colnb` is the number of data columns depends on the shape type,
            # not counting the ROI index, hence the +1 in the following assertion
            assert self.array.shape[1] == data_colnb + 1

    def __get_coords_labels(self) -> tuple[str]:
        """Return shape coordinates labels

        Returns:
            Shape coordinates labels
        """
        if self.shapetype is ShapeTypes.POLYGON:
            labels = []
            for i in range(0, self.array.shape[1] - 1, 2):
                labels += [f"x{i//2}", f"y{i//2}"]
            return tuple(labels)
        try:
            return {
                ShapeTypes.MARKER: ("x", "y"),
                ShapeTypes.POINT: ("x", "y"),
                ShapeTypes.RECTANGLE: ("x0", "y0", "x1", "y1"),
                ShapeTypes.CIRCLE: ("x", "y", "r"),
                ShapeTypes.SEGMENT: ("x0", "y0", "x1", "y1"),
                ShapeTypes.ELLIPSE: ("x", "y", "a", "b", "θ"),
            }[self.shapetype]
        except KeyError as exc:
            raise NotImplementedError(
                f"Unsupported shapetype {self.shapetype}"
            ) from exc

    def __get_complementary_xlabels(self) -> tuple[str] | None:
        """Return complementary labels for result array columns

        Returns:
            Complementary labels for result array columns, or None if there is no
            complementary labels
        """
        if self.shapetype is ShapeTypes.SEGMENT:
            return ("L", "Xc", "Yc")
        if self.shapetype in (ShapeTypes.CIRCLE, ShapeTypes.ELLIPSE):
            return ("A",)
        return None

    def __get_complementary_array(self) -> np.ndarray | None:
        """Return the complementary array of results, e.g. the array of lengths
        for a segment result shape, or the array of areas for a circle result shape

        Returns:
            Complementary array of results, or None if there is no complementary array
        """
        array = self.array
        if self.shapetype is ShapeTypes.SEGMENT:
            dx1, dy1 = array[:, 3] - array[:, 1], array[:, 4] - array[:, 2]
            length = np.linalg.norm(np.vstack([dx1, dy1]).T, axis=1)
            xc = (array[:, 1] + array[:, 3]) / 2
            yc = (array[:, 2] + array[:, 4]) / 2
            return np.vstack([length, xc, yc]).T
        if self.shapetype is ShapeTypes.CIRCLE:
            area = np.pi * array[:, 3] ** 2
            return area.reshape(-1, 1)
        if self.shapetype is ShapeTypes.ELLIPSE:
            area = np.pi * array[:, 3] * array[:, 4]
            return area.reshape(-1, 1)
        return None

    @property
    def headers(self) -> list[str] | None:
        """Return result headers (one header per column of result array)"""
        labels = self.__get_coords_labels() + (self.__get_complementary_xlabels() or ())
        return labels[-self.shown_array.shape[1] :]

    @property
    def shown_array(self) -> np.ndarray:
        """Return array of shown results, i.e. including complementary array (if any)

        Returns:
            Array of shown results
        """
        comp_array = self.__get_complementary_array()
        if comp_array is None:
            return self.raw_data
        return np.hstack([self.raw_data, comp_array])

    @property
    def label_contents(self) -> tuple[tuple[int, str], ...]:
        """Return label contents, i.e. a tuple of couples of (index, text)
        where index is the column of raw_data and text is the associated
        label format string"""
        contents = []
        for idx, lbl in enumerate(self.__get_complementary_xlabels()):
            contents.append((idx + self.raw_data.shape[1], lbl))
        return tuple(contents)

    def create_label_item(self, obj: BaseObj) -> LabelItem | None:
        """Create label item

        Returns:
            Label item
        """
        if self.add_label:
            return super().create_label_item(obj)
        return None

    def merge_with(self, obj: BaseObj, other_obj: BaseObj | None = None):
        """Merge object resultshape with another's: obj <-- other_obj
        or simply merge this resultshape with obj if other_obj is None"""
        if other_obj is None:
            other_obj = obj
        other_value = other_obj.metadata.get(self.key)
        if other_value is not None:
            other = ResultShape.from_metadata_entry(self.key, other_value)
            assert other is not None
            other_array = np.array(other.array, copy=True)
            other_array[:, 0] += self.array[-1, 0] + 1  # Adding ROI index offset
            if other_array.shape[1] != self.array.shape[1]:
                # This can only happen if the shape is a polygon
                assert self.shapetype is ShapeTypes.POLYGON
                # We must padd the array with NaNs
                max_colnb = max(self.array.shape[1], other_array.shape[1])
                new_array = np.full(
                    (self.array.shape[0] + other_array.shape[0], max_colnb), np.nan
                )
                new_array[: self.array.shape[0], : self.array.shape[1]] = self.array
                new_array[self.array.shape[0] :, : other_array.shape[1]] = other_array
                self.array = new_array
            else:
                self.array = np.vstack([self.array, other_array])
        self.add_to(obj)

    def transform_coordinates(self, func: Callable[[np.ndarray], None]) -> None:
        """Transform shape coordinates.

        Args:
            func: function to transform coordinates
        """
        if self.shapetype in (
            ShapeTypes.MARKER,
            ShapeTypes.POINT,
            ShapeTypes.POLYGON,
            ShapeTypes.RECTANGLE,
            ShapeTypes.SEGMENT,
        ):
            func(self.raw_data)
        elif self.shapetype is ShapeTypes.CIRCLE:
            coords = coordinates.array_circle_to_diameter(self.raw_data)
            func(coords)
            self.raw_data[:] = coordinates.array_circle_to_center_radius(coords)
        elif self.shapetype is ShapeTypes.ELLIPSE:
            coords = coordinates.array_ellipse_to_diameters(self.raw_data)
            func(coords)
            self.raw_data[:] = coordinates.array_ellipse_to_center_axes_angle(coords)
        else:
            raise NotImplementedError(f"Unsupported shapetype {self.shapetype}")

    def iterate_plot_items(self, fmt: str, lbl: bool, option: str) -> Iterable:
        """Iterate over metadata shape plot items.

        Args:
            fmt: numeric format (e.g. "%.3f")
            lbl: if True, show shape labels
            option: shape style option (e.g. "shape/drag")

        Yields:
            Plot item
        """
        for coords in self.raw_data:
            yield self.create_shape_item(coords, fmt, lbl, option)

    def create_shape_item(
        self, coords: np.ndarray, fmt: str, lbl: bool, option: str
    ) -> (
        AnnotatedPoint
        | Marker
        | AnnotatedRectangle
        | AnnotatedCircle
        | AnnotatedSegment
        | AnnotatedEllipse
        | PolygonShape
        | None
    ):
        """Make geometrical shape plot item adapted to the shape type.

        Args:
            coords: shape data
            fmt: numeric format (e.g. "%.3f")
            lbl: if True, show shape labels
            option: shape style option (e.g. "shape/drag")

        Returns:
            Plot item
        """
        if self.shapetype is ShapeTypes.MARKER:
            x0, y0 = coords
            item = self.__make_marker_item(x0, y0, fmt)
        elif self.shapetype is ShapeTypes.POINT:
            x0, y0 = coords
            item = AnnotatedPoint(x0, y0)
            sparam: ShapeParam = item.shape.shapeparam
            sparam.symbol.marker = "Ellipse"
            sparam.symbol.size = 6
            sparam.sel_symbol.marker = "Ellipse"
            sparam.sel_symbol.size = 6
            aparam = item.annotationparam
            aparam.title = self.title
            sparam.update_item(item.shape)
            aparam.update_item(item)
        elif self.shapetype is ShapeTypes.RECTANGLE:
            x0, y0, x1, y1 = coords
            item = make.annotated_rectangle(x0, y0, x1, y1, title=self.title)
        elif self.shapetype is ShapeTypes.CIRCLE:
            xc, yc, r = coords
            x0, y0, x1, y1 = coordinates.circle_to_diameter(xc, yc, r)
            item = make.annotated_circle(x0, y0, x1, y1, title=self.title)
        elif self.shapetype is ShapeTypes.SEGMENT:
            x0, y0, x1, y1 = coords
            item = make.annotated_segment(x0, y0, x1, y1, title=self.title)
        elif self.shapetype is ShapeTypes.ELLIPSE:
            xc, yc, a, b, t = coords
            coords = coordinates.ellipse_to_diameters(xc, yc, a, b, t)
            x0, y0, x1, y1, x2, y2, x3, y3 = coords
            item = make.annotated_ellipse(
                x0, y0, x1, y1, x2, y2, x3, y3, title=self.title
            )
        elif self.shapetype is ShapeTypes.POLYGON:
            x, y = coords[::2], coords[1::2]
            item = make.polygon(x, y, title=self.title, closed=False)
        else:
            print(f"Warning: unsupported item {self.shapetype}", file=sys.stderr)
            return None
        if isinstance(item, AnnotatedShape):
            config_annotated_shape(item, fmt, lbl, option)
        set_plot_item_editable(item, False)
        return item

    def __make_marker_item(self, x0: float, y0: float, fmt: str) -> Marker:
        """Make marker item

        Args:
            x0: x coordinate
            y0: y coordinate
            fmt: numeric format (e.g. '%.3f')
        """
        if np.isnan(x0):
            mstyle = "-"

            def label(x, y):  # pylint: disable=unused-argument
                return (self.title + ": " + fmt) % y

        elif np.isnan(y0):
            mstyle = "|"

            def label(x, y):  # pylint: disable=unused-argument
                return (self.title + ": " + fmt) % x

        else:
            mstyle = "+"
            txt = self.title + ": (" + fmt + ", " + fmt + ")"

            def label(x, y):
                return txt % (x, y)

        return make.marker(
            position=(x0, y0),
            markerstyle=mstyle,
            label_cb=label,
            linestyle="DashLine",
            color="yellow",
        )


def make_roi_item(
    func, coords: list, title: str, fmt: str, lbl: bool, editable: bool, option: str
):
    """Make ROI item shape.

    Args:
        func: function to create ROI item
        coords: coordinates
        title: title
        fmt: numeric format (e.g. "%.3f")
        lbl: if True, show shape labels
        editable: if True, make shape editable
        option: shape style option (e.g. "shape/drag")

    Returns:
        Plot item
    """
    item = func(*coords, title)
    if not editable:
        if isinstance(item, AnnotatedShape):
            config_annotated_shape(item, fmt, lbl, option, cmp=editable)
            item.set_style("plot", "shape/mask")
        item.set_movable(False)
        item.set_resizable(False)
        item.set_readonly(True)
    return item


def items_to_json(items: list) -> str | None:
    """Convert plot items to JSON string.

    Args:
        items: list of plot items

    Returns:
        JSON string or None if items is empty
    """
    if items:
        writer = JSONWriter(None)
        save_items(writer, items)
        return writer.get_json(indent=4)
    return None


def json_to_items(json_str: str | None) -> list:
    """Convert JSON string to plot items.

    Args:
        json_str: JSON string or None

    Returns:
        List of plot items
    """
    items = []
    if json_str:
        try:
            for item in load_items(JSONReader(json_str)):
                items.append(item)
        except json.decoder.JSONDecodeError:
            pass
    return items


class BaseObjMeta(abc.ABCMeta, gds.DataSetMeta):
    """Mixed metaclass to avoid conflicts"""


class BaseObj(metaclass=BaseObjMeta):
    """Object (signal/image) interface"""

    PREFIX = ""  # This is overriden in children classes

    DEFAULT_FMT = "s"  # This is overriden in children classes
    CONF_FMT = Conf.view.sig_format  # This is overriden in children classes

    # This is overriden in children classes with a gds.DictItem instance:
    metadata: dict[str, Any] = {}

    VALID_DTYPES = ()

    def __init__(self):
        self.__onb = 0
        self.__roi_changed: bool | None = None
        self.__metadata_options: dict[str, Any] | None = None
        self.reset_metadata_to_defaults()

    @property
    def number(self) -> int:
        """Return object number (used for short ID)"""
        return self.__onb

    @number.setter
    def number(self, onb: int):
        """Set object number (used for short ID).

        Args:
            onb: object number
        """
        self.__onb = onb

    @property
    def short_id(self):
        """Short object ID"""
        return f"{self.PREFIX}{self.__onb:03d}"

    @property
    @abc.abstractmethod
    def data(self):
        """Data"""

    @classmethod
    def get_valid_dtypenames(cls) -> list[str]:
        """Get valid data type names

        Returns:
            Valid data type names supported by this class
        """
        return [
            dtname
            for dtname in np.sctypeDict
            if dtname in (dtype.__name__ for dtype in cls.VALID_DTYPES)
        ]

    def check_data(self):
        """Check if data is valid, raise an exception if that's not the case

        Raises:
            TypeError: if data type is not supported
        """
        if self.data is not None:
            if self.data.dtype not in self.VALID_DTYPES:
                raise TypeError(f"Unsupported data type: {self.data.dtype}")

    def iterate_roi_indexes(self):
        """Iterate over object ROI indexes ([0] if there is no ROI)"""
        if self.roi is None:
            yield 0
        else:
            yield from range(len(self.roi))

    @abc.abstractmethod
    def get_data(self, roi_index: int | None = None) -> np.ndarray:
        """
        Return original data (if ROI is not defined or `roi_index` is None),
        or ROI data (if both ROI and `roi_index` are defined).

        Args:
            roi_index: ROI index

        Returns:
            Data
        """

    @abc.abstractmethod
    def copy(self, title: str | None = None, dtype: np.dtype | None = None) -> BaseObj:
        """Copy object.

        Args:
            title: title
            dtype: data type

        Returns:
            Copied object
        """

    @abc.abstractmethod
    def set_data_type(self, dtype):
        """Change data type.

        Args:
            dtype: data type
        """

    @abc.abstractmethod
    def make_item(self, update_from=None):
        """Make plot item from data.

        Args:
            update_from: update

        Returns:
            Plot item
        """

    @abc.abstractmethod
    def update_item(self, item, data_changed: bool = True) -> None:
        """Update plot item from data.

        Args:
            item: plot item
            data_changed: if True, data has changed
        """

    @abc.abstractmethod
    def roi_coords_to_indexes(self, coords: list) -> np.ndarray:
        """Convert ROI coordinates to indexes.

        Args:
            coords: coordinates

        Returns:
            Indexes
        """

    @abc.abstractmethod
    def get_roi_param(self, title, *defaults: int) -> gds.DataSet:
        """Return ROI parameters dataset.

        Args:
            title: title
            *defaults: default values
        """

    def roidata_to_params(
        self, roidata: np.ndarray | list[list[int]]
    ) -> gds.DataSetGroup:
        """Convert ROI array data to ROI dataset group.

        Args:
            roidata: ROI array data (array or list of lists, floating point values
             are accepted and will be converted to integers)

        Returns:
            ROI dataset group
        """
        roi_params = []
        try:
            data = np.array(roidata, int)
        except (ValueError, TypeError) as exc:
            raise TypeError(f"Invalid ROI data: {roidata}") from exc
        if len(data.shape) != 2 and data.size != 0:
            raise ValueError(f"Invalid ROI data shape: {data.shape}")
        for index, parameters in enumerate(data):
            roi_param = self.get_roi_param(f"ROI{index:02d}", *parameters)
            roi_params.append(roi_param)
        group = gds.DataSetGroup(roi_params, title=_("Regions of interest"))
        return group

    @abc.abstractmethod
    def params_to_roidata(self, params: gds.DataSetGroup) -> np.ndarray:
        """Convert ROI dataset group to ROI array data.

        Args:
            params: ROI dataset group

        Returns:
            ROI array data
        """

    def roi_has_changed(self) -> bool:
        """Return True if ROI has changed since last call to this method.

        The first call to this method will return True if ROI has not yet been set,
        or if ROI has been set and has changed since the last call to this method.
        The next call to this method will always return False if ROI has not changed
        in the meantime.

        Returns:
            True if ROI has changed
        """
        if self.__roi_changed is None:
            self.__roi_changed = True
        returned_value = self.__roi_changed
        self.__roi_changed = False
        return returned_value

    @property
    def roi(self) -> np.ndarray | None:
        """Return object regions of interest array (one ROI per line).

        Returns:
            Regions of interest array
        """
        roidata = self.metadata.get(ROI_KEY)
        assert roidata is None or isinstance(roidata, np.ndarray)
        return roidata

    @roi.setter
    def roi(self, roidata: np.ndarray):
        """Set object regions of interest array, using a list or ROI dataset params.

        Args:
            roidata: regions of interest array
        """
        if roidata is None:
            if ROI_KEY in self.metadata:
                self.metadata.pop(ROI_KEY)
        else:
            self.metadata[ROI_KEY] = np.array(roidata, int)
        self.__roi_changed = True

    def iterate_resultshapes(self) -> Iterable[ResultShape]:
        """Iterate over object result shapes.

        Yields:
            Result shape
        """
        for key, value in self.metadata.items():
            if ResultShape.match(key, value):
                yield ResultShape.from_metadata_entry(key, value)

    def iterate_resultproperties(self) -> Iterable[ResultProperties]:
        """Iterate over object result properties.

        Yields:
            Result properties
        """
        for key, value in self.metadata.items():
            if ResultProperties.match(key, value):
                yield ResultProperties.from_metadata_entry(key, value)

    def delete_results(self) -> None:
        """Delete all object results (shapes and properties)"""
        for key in list(self.metadata.keys()):
            if ResultShape.match(key, self.metadata[key]) or ResultProperties.match(
                key, self.metadata[key]
            ):
                self.metadata.pop(key)

    def update_resultshapes_from(self, other: BaseObj) -> None:
        """Update geometric shape from another object (merge metadata).

        Args:
            other: other object, from which to update this object
        """
        # The following code is merging the result shapes of the `other` object
        # with the result shapes of this object, but it is merging only the result
        # shapes of the same type (`mshape.key`). Thus, if the `other` object has
        # a result shape that is not present in this object, it will not be merged,
        # and we will have to add it to this object manually.
        for mshape in self.iterate_resultshapes():
            assert mshape is not None
            mshape.merge_with(self, other)
        # Iterating on `other` object result shapes to find result shapes that are
        # not present in this object, and add them to this object.
        for mshape in other.iterate_resultshapes():
            assert mshape is not None
            if mshape.key not in self.metadata:
                mshape.add_to(self)

    def transform_shapes(self, orig, func, param=None):
        """Apply transform function to result shape / annotations coordinates.

        Args:
            orig: original object
            func: transform function
            param: transform function parameter
        """

        def transform(coords: np.ndarray):
            """Transform coordinates"""
            if param is None:
                func(self, orig, coords)
            else:
                func(self, orig, coords, param)

        for mshape in self.iterate_resultshapes():
            assert mshape is not None
            mshape.transform_coordinates(transform)
        items = []
        for item in json_to_items(self.annotations):
            if isinstance(item, AnnotatedShape):
                transform(item.shape.points)
                item.set_label_position()
            elif isinstance(item, LabelItem):
                x, y = item.G
                points = np.array([[x, y]], float)
                transform(points)
                x, y = points[0]
                item.set_pos(x, y)
            items.append(item)
        if items:
            self.annotations = items_to_json(items)

    @abc.abstractmethod
    def iterate_roi_items(self, fmt: str, lbl: bool, editable: bool = True):
        """Make plot item representing a Region of Interest.

        Args:
            fmt: format string
            lbl: if True, add label
            editable: if True, ROI is editable

        Yields:
            Plot item
        """

    def __set_annotations(self, annotations: str | None) -> None:
        """Set object annotations (JSON string describing annotation plot items)

        Args:
            annotations: JSON string describing annotation plot items,
             or None to remove annotations
        """
        if annotations is None:
            if ANN_KEY in self.metadata:
                self.metadata.pop(ANN_KEY)
        else:
            self.metadata[ANN_KEY] = annotations

    def __get_annotations(self) -> str:
        """Get object annotations (JSON string describing annotation plot items)"""
        return self.metadata.get(ANN_KEY, "")

    annotations = property(__get_annotations, __set_annotations)

    def add_annotations_from_items(self, items: list) -> None:
        """Add object annotations (annotation plot items).

        Args:
            items: annotation plot items
        """
        ann_items = json_to_items(self.annotations)
        ann_items.extend(items)
        if ann_items:
            self.annotations = items_to_json(ann_items)

    def add_annotations_from_file(self, filename: str) -> None:
        """Add object annotations from file (JSON).

        Args:
            filename: filename
        """
        with open(filename, "r", encoding="utf-8") as file:
            json_str = file.read()
        if self.annotations:
            json_str = self.annotations[:-1] + "," + json_str[1:]
        self.annotations = json_str

    @abc.abstractmethod
    def add_label_with_title(self, title: str | None = None) -> None:
        """Add label with title annotation

        Args:
            title: title (if None, use object title)
        """

    def iterate_shape_items(self, editable: bool = False):
        """Iterate over computing items encoded in metadata (if any).

        Args:
            editable: if True, annotations are editable

        Yields:
            Plot item
        """
        fmt = self.get_metadata_option("format")
        lbl = self.get_metadata_option("showlabel")
        for key, value in self.metadata.items():
            if key == ROI_KEY:
                yield from self.iterate_roi_items(fmt=fmt, lbl=lbl, editable=False)
            elif ResultShape.match(key, value):
                mshape: ResultShape = ResultShape.from_metadata_entry(key, value)
                option = f"shape/result/{self.PREFIX}"
                yield from mshape.iterate_plot_items(fmt, lbl, option)
        if self.annotations:
            try:
                for item in json_to_items(self.annotations):
                    if isinstance(item, AnnotatedShape):
                        config_annotated_shape(item, fmt, lbl, "shape/annotation")
                    set_plot_item_editable(item, editable)
                    yield item
            except json.decoder.JSONDecodeError:
                pass

    def remove_all_shapes(self) -> None:
        """Remove metadata shapes and ROIs"""
        for key, value in list(self.metadata.items()):
            resultshape = ResultShape.from_metadata_entry(key, value)
            if resultshape is not None or key == ROI_KEY:
                # Metadata entry is a metadata shape or a ROI
                self.metadata.pop(key)
        self.annotations = None

    def get_metadata_option(self, name: str) -> Any:
        """Return metadata option value

        A metadata option is a metadata entry starting with an underscore.
        It is a way to store application-specific options in object metadata.

        Args:
            name: option name

        Returns:
            Option value

        Valid option names:
            'format': format string
            'showlabel': show label
        """
        if name not in self.__metadata_options:
            raise ValueError(f"Invalid metadata option name `{name}`")
        default = self.__metadata_options[name]
        return self.metadata.get(f"__{name}", default)

    def set_metadata_option(self, name: str, value: Any) -> None:
        """Set metadata option value

        A metadata option is a metadata entry starting with an underscore.
        It is a way to store application-specific options in object metadata.

        Args:
            name: option name
            value: option value

        Valid option names:
            'format': format string
            'showlabel': show label
        """
        if name not in self.__metadata_options:
            raise ValueError(f"Invalid metadata option name `{name}`")
        self.metadata[f"__{name}"] = value

    def save_attr_to_metadata(self, attrname: str, new_value: Any) -> None:
        """Save attribute to metadata

        Args:
            attrname: attribute name
            new_value: new value
        """
        value = getattr(self, attrname)
        if value:
            self.metadata[f"orig_{attrname}"] = value
        setattr(self, attrname, new_value)

    def restore_attr_from_metadata(self, attrname: str, default: Any) -> None:
        """Restore attribute from metadata

        Args:
            attrname: attribute name
            default: default value
        """
        value = self.metadata.pop(f"orig_{attrname}", default)
        setattr(self, attrname, value)

    def reset_metadata_to_defaults(self) -> None:
        """Reset metadata to default values"""
        self.__metadata_options = {
            "format": "%" + self.CONF_FMT.get(self.DEFAULT_FMT),
            "showlabel": Conf.view.show_label.get(False),
        }
        self.metadata = {}
        for name, value in self.__metadata_options.items():
            self.set_metadata_option(name, value)
        self.update_metadata_view_settings()

    def __get_def_dict(self) -> dict[str, Any]:
        """Return default visualization settings dictionary"""
        return Conf.view.get_def_dict(self.__class__.__name__[:3].lower())

    def update_metadata_view_settings(self) -> None:
        """Update metadata view settings from Conf.view"""
        self.metadata.update(self.__get_def_dict())

    def update_plot_item_parameters(self, item: CurveItem | MaskedImageItem) -> None:
        """Update plot item parameters from object data/metadata

        Takes into account a subset of plot item parameters. Those parameters may
        have been overriden by object metadata entries or other object data. The goal
        is to update the plot item accordingly.

        This is *almost* the inverse operation of `update_metadata_from_plot_item`.

        Args:
            item: plot item
        """
        # Subclasses have to override this method to update plot item parameters,
        # then call this implementation of the method to update plot item.
        update_dataset(item.param, self.metadata)
        item.param.update_item(item)
        if item.selected:
            item.select()

    def update_metadata_from_plot_item(self, item: CurveItem | MaskedImageItem) -> None:
        """Update metadata from plot item.

        Takes into account a subset of plot item parameters. Those parameters may
        have been modified by the user through the plot item GUI. The goal is to
        update the metadata accordingly.

        This is *almost* the inverse operation of `update_plot_item_parameters`.

        Args:
            item: plot item
        """
        for key in self.__get_def_dict():
            if hasattr(item.param, key):  # In case the PlotPy version is not up-to-date
                self.metadata[key] = getattr(item.param, key)
        # Subclasses may override this method to update metadata from plot item,
        # then call this implementation of the method to update metadata standard
        # entries.
