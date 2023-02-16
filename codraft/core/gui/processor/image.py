# -*- coding: utf-8 -*-
#
# Licensed under the terms of the BSD 3-Clause or the CeCILL-B License
# (see codraft/__init__.py for details)

"""
CodraFT Image Processor GUI module
"""

# pylint: disable=invalid-name  # Allows short reference names like x, y, ...


import numpy as np
import pywt
import scipy.ndimage as spi
import scipy.signal as sps
from guidata.dataset.dataitems import BoolItem, ChoiceItem, FloatItem, IntItem
from guidata.dataset.datatypes import (
    DataSet,
    DataSetGroup,
    FuncProp,
    GetAttrProp,
    ValueProp,
)
from guiqwt.geometry import vector_rotation
from guiqwt.widgets.resizedialog import ResizeDialog
from numpy import ma
from qtpy import QtWidgets as QW
from skimage import exposure, feature, morphology
from skimage.restoration import denoise_bilateral, denoise_tv_chambolle, denoise_wavelet
from skimage.util.dtype import dtype_range

from codraft.config import APP_NAME, _
from codraft.core.computation.image import (
    BINNING_OPERATIONS,
    binning,
    distance_matrix,
    find_blobs_doh,
    find_blobs_opencv,
    flatfield,
    get_2d_peaks_coords,
    get_centroid_fourier,
    get_contour_shapes,
    get_enclosing_circle,
    get_hough_circle_peaks,
)
from codraft.core.gui.processor.base import BaseProcessor, ClipParam, ThresholdParam
from codraft.core.model.base import BaseProcParam, ShapeTypes
from codraft.core.model.image import ImageParam, RoiDataGeometries, RoiDataItem
from codraft.utils.qthelpers import create_progress_bar, qt_try_except

VALID_DTYPES_STRLIST = [
    dtype.__name__ for dtype in dtype_range if dtype in ImageParam.VALID_DTYPES
]


class RescaleIntensityParam(DataSet):
    """Intensity rescaling parameters"""

    _dtype_list = ["image", "dtype"] + VALID_DTYPES_STRLIST
    in_range = ChoiceItem(
        _("Input range"),
        list(zip(_dtype_list, _dtype_list)),
        default="image",
        help=_(
            "Min and max intensity values of input image ('image' refers to input "
            "image min/max levels, 'dtype' refers to input image data type range)."
        ),
    )
    out_range = ChoiceItem(
        _("Output range"),
        list(zip(_dtype_list, _dtype_list)),
        default="dtype",
        help=_(
            "Min and max intensity values of output image  ('image' refers to input "
            "image min/max levels, 'dtype' refers to input image data type range).."
        ),
    )


class EqualizeHistParam(DataSet):
    """Histogram equalization parameters"""

    nbins = IntItem(
        _("Number of bins"),
        min=1,
        default=256,
        help=_("Number of bins for image histogram."),
    )


class EqualizeAdaptHistParam(EqualizeHistParam):
    """Adaptive histogram equalization parameters"""

    clip_limit = FloatItem(
        _("Clipping limit"),
        default=0.01,
        min=0.0,
        max=1.0,
        help=_("Clipping limit (higher values give more contrast)."),
    )


class LogP1Param(DataSet):
    """Log10 parameters"""

    n = FloatItem("n")


class RotateParam(DataSet):
    """Rotate parameters"""

    boundaries = ("constant", "nearest", "reflect", "wrap")
    prop = ValueProp(False)

    angle = FloatItem(f"{_('Angle')} (°)")
    mode = ChoiceItem(
        _("Mode"), list(zip(boundaries, boundaries)), default=boundaries[0]
    )
    cval = FloatItem(
        _("cval"),
        default=0.0,
        help=_(
            "Value used for points outside the "
            "boundaries of the input if mode is "
            "'constant'"
        ),
    )
    reshape = BoolItem(
        _("Reshape the output array"),
        default=False,
        help=_(
            "Reshape the output array "
            "so that the input array is "
            "contained completely in the output"
        ),
    )
    prefilter = BoolItem(_("Prefilter the input image"), default=True).set_prop(
        "display", store=prop
    )
    order = IntItem(
        _("Order"),
        default=3,
        min=0,
        max=5,
        help=_("Spline interpolation order"),
    ).set_prop("display", active=prop)


def rotate_obj_coords(
    angle: float, obj: ImageParam, orig: ImageParam, coords: np.ndarray
) -> None:
    """Apply rotation to coords associated to image obj"""
    for row in range(coords.shape[0]):
        for col in range(0, coords.shape[1], 2):
            x1, y1 = coords[row, col : col + 2]
            dx1 = x1 - orig.xc
            dy1 = y1 - orig.yc
            dx2, dy2 = vector_rotation(-angle * np.pi / 180.0, dx1, dy1)
            coords[row, col : col + 2] = dx2 + obj.xc, dy2 + obj.yc
    obj.roi = None


class GridParam(DataSet):
    """Grid parameters"""

    _prop = GetAttrProp("direction")
    _directions = (("col", _("columns")), ("row", _("rows")))
    direction = ChoiceItem(_("Distribute over"), _directions, radio=True).set_prop(
        "display", store=_prop
    )
    cols = IntItem(_("Columns"), default=1, nonzero=True).set_prop(
        "display", active=FuncProp(_prop, lambda x: x == "col")
    )
    rows = IntItem(_("Rows"), default=1, nonzero=True).set_prop(
        "display", active=FuncProp(_prop, lambda x: x == "row")
    )
    colspac = FloatItem(_("Column spacing"), default=0.0, min=0.0)
    rowspac = FloatItem(_("Row spacing"), default=0.0, min=0.0)


class ResizeParam(DataSet):
    """Resize parameters"""

    boundaries = ("constant", "nearest", "reflect", "wrap")
    prop = ValueProp(False)

    zoom = FloatItem(_("Zoom"))
    mode = ChoiceItem(
        _("Mode"), list(zip(boundaries, boundaries)), default=boundaries[0]
    )
    cval = FloatItem(
        _("cval"),
        default=0.0,
        help=_(
            "Value used for points outside the "
            "boundaries of the input if mode is "
            "'constant'"
        ),
    )
    prefilter = BoolItem(_("Prefilter the input image"), default=True).set_prop(
        "display", store=prop
    )
    order = IntItem(
        _("Order"),
        default=3,
        min=0,
        max=5,
        help=_("Spline interpolation order"),
    ).set_prop("display", active=prop)


class BinningParam(DataSet):
    """Binning parameters"""

    binning_x = IntItem(
        _("Cluster size (X)"),
        default=2,
        min=2,
        help=_("Number of adjacent pixels to be combined together along X-axis."),
    )
    binning_y = IntItem(
        _("Cluster size (Y)"),
        default=2,
        min=2,
        help=_("Number of adjacent pixels to be combined together along Y-axis."),
    )
    _operations = BINNING_OPERATIONS
    operation = ChoiceItem(
        _("Operation"),
        list(zip(_operations, _operations)),
        default=_operations[0],
    )
    _dtype_list = ["dtype"] + VALID_DTYPES_STRLIST
    dtype_str = ChoiceItem(
        _("Data type"),
        list(zip(_dtype_list, _dtype_list)),
        help=_("Output image data type."),
    )
    change_pixel_size = BoolItem(
        _("Change pixel size"),
        default=False,
        help=_("Change pixel size so that overall image size remains the same."),
    )


class FlatFieldParam(BaseProcParam):
    """Flat-field parameters"""

    threshold = FloatItem(_("Threshold"), default=0.0)


class ZCalibrateParam(DataSet):
    """Image linear calibration parameters"""

    a = FloatItem("a", default=1.0)
    b = FloatItem("b", default=0.0)


class DenoiseTVParam(DataSet):
    """Total Variation denoising parameters"""

    weight = FloatItem(
        _("Denoising weight"),
        default=0.1,
        min=0,
        nonzero=True,
        help=_(
            "The greater weight, the more denoising "
            "(at the expense of fidelity to input)."
        ),
    )
    eps = FloatItem(
        "Epsilon",
        default=0.0002,
        min=0,
        nonzero=True,
        help=_(
            "Relative difference of the value of the cost function that "
            "determines the stop criterion. The algorithm stops when: "
            "(E_(n-1) - E_n) < eps * E_0"
        ),
    )
    max_num_iter = IntItem(
        _("Max. iterations"),
        default=200,
        min=0,
        nonzero=True,
        help=_("Maximal number of iterations used for the optimization"),
    )


class DenoiseBilateralParam(DataSet):
    """Bilateral filter denoising parameters"""

    sigma_spatial = FloatItem(
        "σ<sub>spatial</sub>",
        default=1.0,
        min=0,
        nonzero=True,
        unit="pixels",
        help=_(
            "Standard deviation for range distance. "
            "A larger value results in averaging of pixels "
            "with larger spatial differences."
        ),
    )
    _modelist = ("constant", "edge", "symmetric", "reflect", "wrap")
    mode = ChoiceItem(_("Mode"), list(zip(_modelist, _modelist)), default="constant")
    cval = FloatItem(
        "cval",
        default=0,
        help=_(
            "Used in conjunction with mode 'constant', "
            "the value outside the image boundaries."
        ),
    )


class DenoiseWaveletParam(DataSet):
    """Wavelet denoising parameters"""

    _wavelist = pywt.wavelist()
    wavelet = ChoiceItem(_("Wavelet"), list(zip(_wavelist, _wavelist)), default="sym9")
    _modelist = ("soft", "hard")
    mode = ChoiceItem(_("Mode"), list(zip(_modelist, _modelist)), default="soft")
    _methlist = ("BayesShrink", "VisuShrink")
    method = ChoiceItem(
        _("Method"), list(zip(_methlist, _methlist)), default="VisuShrink"
    )


class MorphologyParam(DataSet):
    """White Top-Hat parameters"""

    radius = IntItem(_("Radius"), default=1, min=1, help=_("Footprint (disk) radius."))


class CannyParam(DataSet):
    """Canny filter parameters"""

    sigma = FloatItem(
        "Sigma",
        default=1.0,
        unit="pixels",
        min=0,
        nonzero=True,
        help=_("Standard deviation of the Gaussian filter."),
    )
    low_threshold = FloatItem(
        _("Low threshold"),
        default=0.1,
        min=0,
        help=_("Lower bound for hysteresis thresholding (linking edges)."),
    )
    high_threshold = FloatItem(
        _("High threshold"),
        default=0.9,
        min=0,
        help=_("Upper bound for hysteresis thresholding (linking edges)."),
    )
    use_quantiles = BoolItem(
        _("Use quantiles"),
        default=True,
        help=_(
            "If True then treat low_threshold and high_threshold as quantiles "
            "of the edge magnitude image, rather than absolute edge magnitude "
            "values. If True then the thresholds must be in the range [0, 1]."
        ),
    )
    _modelist = ("reflect", "constant", "nearest", "mirror", "wrap")
    mode = ChoiceItem(_("Mode"), list(zip(_modelist, _modelist)), default="constant")
    cval = FloatItem(
        "cval",
        default=0.0,
        help=_("Value to fill past edges of input if mode is constant."),
    )


class GenericDetectionParam(DataSet):
    """Generic detection parameters"""

    threshold = FloatItem(
        _("Relative threshold"),
        default=0.5,
        min=0.1,
        max=0.9,
        help=_(
            "Detection threshold, relative to difference between "
            "data maximum and minimum"
        ),
    )


class PeakDetectionParam(GenericDetectionParam):
    """Peak detection parameters"""

    size = IntItem(
        _("Neighborhoods size"),
        default=10,
        min=1,
        unit="pixels",
        help=_(
            "Size of the sliding window used in maximum/minimum filtering algorithm"
        ),
    )
    create_rois = BoolItem(_("Create regions of interest"), default=True)


class ContourShapeParam(GenericDetectionParam):
    """Contour shape parameters"""

    shapes = (
        ("ellipse", _("Ellipse")),
        ("circle", _("Circle")),
    )
    shape = ChoiceItem(_("Shape"), shapes, default="ellipse")


class HoughCircleParam(DataSet):
    """Circle Hough transform parameters"""

    min_radius = IntItem(_("Radius<sub>min</sub>"), unit="pixels", min=0, nonzero=True)
    max_radius = IntItem(_("Radius<sub>max</sub>"), unit="pixels", min=0, nonzero=True)
    min_distance = IntItem(_("Minimal distance"), min=0)


class BlobDOHParam(DataSet):
    """Blob detection using Determinant of Hessian method"""

    min_sigma = FloatItem(
        "σ<sub>min</sub>",
        default=1.0,
        unit="pixels",
        min=0,
        nonzero=True,
        help=_(
            "The minimum standard deviation for Gaussian Kernel used to compute "
            "Hessian matrix. Keep this low to detect smaller blobs."
        ),
    )
    max_sigma = FloatItem(
        "σ<sub>max</sub>",
        default=30.0,
        unit="pixels",
        min=0,
        nonzero=True,
        help=_(
            "The maximum standard deviation for Gaussian Kernel used to compute "
            "Hessian matrix. Keep this high to detect larger blobs."
        ),
    )
    threshold_rel = FloatItem(
        _("Relative threshold"),
        default=0.2,
        min=0.0,
        max=1.0,
        help=_(
            "Minimum intensity of peaks, calculated as "
            "max(doh_space) * threshold_rel, where doh_space refers to the stack "
            "of Determinant-of-Hessian (DoH) images computed internally."
        ),
    )
    overlap = FloatItem(
        _("Overlap"),
        default=0.5,
        min=0.0,
        max=1.0,
        help=_(
            "If the area of two blobs overlaps by a fraction greater "
            "than threshold, the smaller blob is eliminated."
        ),
    )
    log_scale = BoolItem(
        _("Log scale"),
        default=False,
        help=_(
            "If set intermediate values of standard deviations are interpolated "
            "using a logarithmic scale to the base 10. "
            "If not, linear interpolation is used."
        ),
    )


class BlobOpenCVParam(DataSet):
    """Blob detection using OpenCV"""

    min_threshold = FloatItem(
        _("Min. threshold"),
        default=10.0,
        min=0.0,
        help=_(
            "The minimum threshold between local maxima and minima. "
            "This parameter does not affect the quality of the blobs, "
            "only the quantity. Lower thresholds result in larger "
            "numbers of blobs."
        ),
    )
    max_threshold = FloatItem(
        _("Max. threshold"),
        default=200.0,
        min=0.0,
        help=_(
            "The maximum threshold between local maxima and minima. "
            "This parameter does not affect the quality of the blobs, "
            "only the quantity. Lower thresholds result in larger "
            "numbers of blobs."
        ),
    )
    min_repeatability = IntItem(
        _("Min. repeatability"),
        default=2,
        min=1,
        help=_(
            "The minimum number of times a blob needs to be detected "
            "in a sequence of images to be considered valid."
        ),
    )
    min_dist_between_blobs = FloatItem(
        _("Min. distance between blobs"),
        default=10.0,
        min=0.0,
        help=_(
            "The minimum distance between two blobs. If blobs are found "
            "closer together than this distance, the smaller blob is removed."
        ),
    )
    _prop_col = ValueProp(False)
    filter_by_color = BoolItem(
        _("Filter by color"),
        default=True,
        help=_("If true, the image is filtered by color instead of intensity."),
    ).set_prop("display", store=_prop_col)
    blob_color = IntItem(
        _("Blob color"),
        default=0,
        help=_(
            "The color of the blobs to detect (0 for dark blobs, 255 for light blobs)."
        ),
    ).set_prop("display", active=_prop_col)
    _prop_area = ValueProp(False)
    filter_by_area = BoolItem(
        _("Filter by area"),
        default=True,
        help=_("If true, the image is filtered by blob area."),
    ).set_prop("display", store=_prop_area)
    min_area = FloatItem(
        _("Min. area"),
        default=25.0,
        min=0.0,
        help=_("The minimum blob area."),
    ).set_prop("display", active=_prop_area)
    max_area = FloatItem(
        _("Max. area"),
        default=500.0,
        min=0.0,
        help=_("The maximum blob area."),
    ).set_prop("display", active=_prop_area)
    _prop_circ = ValueProp(False)
    filter_by_circularity = BoolItem(
        _("Filter by circularity"),
        default=False,
        help=_("If true, the image is filtered by blob circularity."),
    ).set_prop("display", store=_prop_circ)
    min_circularity = FloatItem(
        _("Min. circularity"),
        default=0.8,
        min=0.0,
        max=1.0,
        help=_("The minimum circularity of the blobs."),
    ).set_prop("display", active=_prop_circ)
    max_circularity = FloatItem(
        _("Max. circularity"),
        default=1.0,
        min=0.0,
        max=1.0,
        help=_("The maximum circularity of the blobs."),
    ).set_prop("display", active=_prop_circ)
    _prop_iner = ValueProp(False)
    filter_by_inertia = BoolItem(
        _("Filter by inertia"),
        default=False,
        help=_("If true, the image is filtered by blob inertia."),
    ).set_prop("display", store=_prop_iner)
    min_inertia_ratio = FloatItem(
        _("Min. inertia ratio"),
        default=0.6,
        min=0.0,
        max=1.0,
        help=_("The minimum inertia ratio of the blobs."),
    ).set_prop("display", active=_prop_iner)
    max_inertia_ratio = FloatItem(
        _("Max. inertia ratio"),
        default=1.0,
        min=0.0,
        max=1.0,
        help=_("The maximum inertia ratio of the blobs."),
    ).set_prop("display", active=_prop_iner)
    _prop_conv = ValueProp(False)
    filter_by_convexity = BoolItem(
        _("Filter by convexity"),
        default=False,
        help=_("If true, the image is filtered by blob convexity."),
    ).set_prop("display", store=_prop_conv)
    min_convexity = FloatItem(
        _("Min. convexity"),
        default=0.8,
        min=0.0,
        max=1.0,
        help=_("The minimum convexity of the blobs."),
    ).set_prop("display", active=_prop_conv)
    max_convexity = FloatItem(
        _("Max. convexity"),
        default=1.0,
        min=0.0,
        max=1.0,
        help=_("The maximum convexity of the blobs."),
    ).set_prop("display", active=_prop_conv)


class ImageProcessor(BaseProcessor):
    """Object handling image processing: operations, processing, computing"""

    # pylint: disable=duplicate-code

    EDIT_ROI_PARAMS = True

    def compute_logp1(self, param: LogP1Param = None) -> None:
        """Compute base 10 logarithm"""
        edit = param is None
        if edit:
            param = LogP1Param("Log10(z+n)")
        self.compute_11(
            "Log10(z+n)",
            lambda z, p: np.log10(z + p.n),
            param,
            suffix=lambda p: f"n={p.n}",
            edit=edit,
        )

    def rotate_arbitrarily(self, param: RotateParam = None) -> None:
        """Rotate data arbitrarily"""
        edit = param is None
        if edit:
            param = RotateParam(_("Rotation"))

        def rotate_xy(
            obj: ImageParam, orig: ImageParam, coords: np.ndarray, p: RotateParam
        ) -> None:
            """Apply rotation to coords"""
            rotate_obj_coords(p.angle, obj, orig, coords)

        self.compute_11(
            "Rotate",
            lambda x, p: spi.rotate(
                x,
                p.angle,
                reshape=p.reshape,
                order=p.order,
                mode=p.mode,
                cval=p.cval,
                prefilter=p.prefilter,
            ),
            param,
            suffix=lambda p: f"α={p.angle:.3f}°, mode='{p.mode}'",
            func_obj=lambda obj, orig, p: obj.transform_shapes(orig, rotate_xy, p),
            edit=edit,
        )

    def rotate_90(self):
        """Rotate data 90°"""

        def rotate_xy(obj: ImageParam, orig: ImageParam, coords: np.ndarray) -> None:
            """Apply rotation to coords"""
            rotate_obj_coords(90.0, obj, orig, coords)

        self.compute_11(
            "Rotate90",
            np.rot90,
            func_obj=lambda obj, orig: obj.transform_shapes(orig, rotate_xy),
        )

    def rotate_270(self):
        """Rotate data 270°"""

        def rotate_xy(obj: ImageParam, orig: ImageParam, coords: np.ndarray) -> None:
            """Apply rotation to coords"""
            rotate_obj_coords(270.0, obj, orig, coords)

        self.compute_11(
            "Rotate270",
            lambda x: np.rot90(x, 3),
            func_obj=lambda obj, orig: obj.transform_shapes(orig, rotate_xy),
        )

    def flip_horizontally(self):
        """Flip data horizontally"""

        # pylint: disable=unused-argument
        def hflip_coords(obj: ImageParam, orig: ImageParam, coords: np.ndarray) -> None:
            """Apply HFlip to coords"""
            coords[:, ::2] = obj.x0 + obj.dx * obj.data.shape[1] - coords[:, ::2]
            obj.roi = None

        self.compute_11(
            "HFlip",
            np.fliplr,
            func_obj=lambda obj, orig: obj.transform_shapes(orig, hflip_coords),
        )

    def flip_vertically(self):
        """Flip data vertically"""

        # pylint: disable=unused-argument
        def vflip_coords(obj: ImageParam, orig: ImageParam, coords: np.ndarray) -> None:
            """Apply VFlip to coords"""
            coords[:, 1::2] = obj.y0 + obj.dy * obj.data.shape[0] - coords[:, 1::2]
            obj.roi = None

        self.compute_11(
            "VFlip",
            np.flipud,
            func_obj=lambda obj, orig: obj.transform_shapes(orig, vflip_coords),
        )

    def distribute_on_grid(self, param: GridParam = None) -> None:
        """Distribute images on a grid"""
        title = _("Distribute on grid")
        edit = param is None
        if edit:
            param = GridParam(title)
            if not param.edit(parent=self.panel.parent()):
                return
        rows = self.objlist.get_selected_rows()
        g_row, g_col, x0, y0, x0_0, y0_0 = 0, 0, 0.0, 0.0, 0.0, 0.0
        with create_progress_bar(self.panel, title, max_=len(rows)) as progress:
            for i_row, row in enumerate(rows):
                progress.setValue(i_row)
                QW.QApplication.processEvents()
                if progress.wasCanceled():
                    break
                obj = self.objlist[row]
                if i_row == 0:
                    x0_0, y0_0 = x0, y0 = obj.x0, obj.y0
                else:
                    delta_x0, delta_y0 = x0 - obj.x0, y0 - obj.y0
                    obj.x0 += delta_x0
                    obj.y0 += delta_y0

                    # pylint: disable=unused-argument
                    def translate_coords(obj, orig, coords):
                        """Apply translation to coords"""
                        coords[:, ::2] += delta_x0
                        coords[:, 1::2] += delta_y0

                    obj.transform_shapes(None, translate_coords)
                if param.direction == "row":
                    # Distributing images over rows
                    sign = np.sign(param.rows)
                    g_row = (g_row + sign) % param.rows
                    y0 += (obj.dy * obj.data.shape[0] + param.rowspac) * sign
                    if g_row == 0:
                        g_col += 1
                        x0 += obj.dx * obj.data.shape[1] + param.colspac
                        y0 = y0_0
                else:
                    # Distributing images over columns
                    sign = np.sign(param.cols)
                    g_col = (g_col + sign) % param.cols
                    x0 += (obj.dx * obj.data.shape[1] + param.colspac) * sign
                    if g_col == 0:
                        g_row += 1
                        x0 = x0_0
                        y0 += obj.dy * obj.data.shape[0] + param.rowspac
        self.panel.SIG_UPDATE_PLOT_ITEMS.emit()

    def reset_positions(self) -> None:
        """Reset image positions"""
        x0_0, y0_0 = 0.0, 0.0
        for i_row, row in enumerate(self.objlist.get_selected_rows()):
            obj = self.objlist[row]
            if i_row == 0:
                x0_0, y0_0 = obj.x0, obj.y0
            else:
                delta_x0, delta_y0 = x0_0 - obj.x0, y0_0 - obj.y0
                obj.x0 += delta_x0
                obj.y0 += delta_y0

                # pylint: disable=unused-argument
                def translate_coords(obj, orig, coords):
                    """Apply translation to coords"""
                    coords[:, ::2] += delta_x0
                    coords[:, 1::2] += delta_y0

                obj.transform_shapes(None, translate_coords)
        self.panel.SIG_UPDATE_PLOT_ITEMS.emit()

    def resize(self, param: ResizeParam = None) -> None:
        """Resize image"""
        obj0 = self.objlist.get_sel_object(0)
        for obj in self.objlist.get_sel_objects():
            if obj.size != obj0.size:
                QW.QMessageBox.warning(
                    self.panel.parent(),
                    APP_NAME,
                    _("Warning:")
                    + "\n"
                    + _("Selected images do not have the same size"),
                )

        edit = param is None
        if edit:
            original_size = obj0.size
            dlg = ResizeDialog(
                self.plotwidget,
                new_size=original_size,
                old_size=original_size,
                text=_("Destination size:"),
            )
            if not dlg.exec():
                return
            param = ResizeParam(_("Resize"))
            param.zoom = dlg.get_zoom()

        def func_obj(obj, orig, param):  # pylint: disable=unused-argument
            """Zooming function"""
            if obj.dx is not None and obj.dy is not None:
                obj.dx, obj.dy = obj.dx / param.zoom, obj.dy / param.zoom
            # TODO: [P2] Instead of removing geometric shapes, apply zoom
            obj.remove_all_shapes()

        self.compute_11(
            "Zoom",
            lambda x, p: spi.interpolation.zoom(
                x,
                p.zoom,
                order=p.order,
                mode=p.mode,
                cval=p.cval,
                prefilter=p.prefilter,
            ),
            param,
            suffix=lambda p: f"zoom={p.zoom:.3f}",
            func_obj=func_obj,
            edit=edit,
        )

    def rebin(self, param: BinningParam = None) -> None:
        """Binning image"""
        edit = param is None
        input_dtype_str = str(self.objlist.get_sel_object(0).data.dtype)
        if edit:
            param = BinningParam(_("Binning"))
            param.dtype_str = input_dtype_str
        if param.dtype_str is None:
            param.dtype_str = input_dtype_str

        # pylint: disable=unused-argument
        def func_obj(obj: ImageParam, orig: ImageParam, param: BinningParam):
            """Binning function"""
            if param.change_pixel_size:
                if obj.dx is not None and obj.dy is not None:
                    obj.dx *= param.binning_x
                    obj.dy *= param.binning_y
                # TODO: [P2] Instead of removing geometric shapes, apply zoom
                obj.remove_all_shapes()

        self.compute_11(
            "PixelBinning",
            lambda x, p: binning(
                x,
                binning_x=p.binning_x,
                binning_y=p.binning_y,
                operation=p.operation,
                dtype=p.dtype_str,
            ),
            param,
            suffix=lambda p: f"{p.binning_x}x{p.binning_y},{p.operation},"
            f"change_pixel_size={p.change_pixel_size}",
            func_obj=func_obj,
            edit=edit,
        )

    def extract_roi(self, roidata: np.ndarray = None, singleobj: bool = None) -> None:
        """Extract Region Of Interest (ROI) from data"""
        roieditordata = self._get_roieditordata(roidata, singleobj)
        if roieditordata is None or roieditordata.is_empty:
            return
        obj = self.objlist.get_sel_object()
        group = obj.roidata_to_params(roieditordata.roidata)

        if roieditordata.singleobj:

            def suffix_func(group: DataSetGroup):
                if len(group.datasets) == 1:
                    p = group.datasets[0]
                    return p.get_suffix()
                return ""

            def extract_roi_func(data: np.ndarray, group: DataSetGroup):
                """Extract ROI function on data"""
                if len(group.datasets) == 1:
                    p = group.datasets[0]
                    return data.copy()[p.y0 : p.y1, p.x0 : p.x1]
                out = np.zeros_like(data)
                for p in group.datasets:
                    slice1, slice2 = slice(p.y0, p.y1 + 1), slice(p.x0, p.x1 + 1)
                    out[slice1, slice2] = data[slice1, slice2]
                x0 = min([p.x0 for p in group.datasets])
                y0 = min([p.y0 for p in group.datasets])
                x1 = max([p.x1 for p in group.datasets])
                y1 = max([p.y1 for p in group.datasets])
                return out[y0:y1, x0:x1]

            def extract_roi_func_obj(
                image: ImageParam, orig: ImageParam, group: DataSetGroup
            ):  # pylint: disable=unused-argument
                """Extract ROI function on object"""
                image.x0 += min([p.x0 for p in group.datasets])
                image.y0 += min([p.y0 for p in group.datasets])
                image.roi = None

            self.compute_11(
                "ROI",
                extract_roi_func,
                group,
                suffix=suffix_func,
                func_obj=extract_roi_func_obj,
                edit=False,
            )

        else:

            # pylint: disable=unused-argument
            def extract_roi_func_obj(image: ImageParam, orig: ImageParam, p: DataSet):
                """Extract ROI function on object"""
                image.x0 += p.x0
                image.y0 += p.y0
                image.roi = None
                if p.geometry is RoiDataGeometries.CIRCLE:
                    # Circular ROI
                    image.roi = p.get_single_roi()

            self.compute_1n(
                [f"ROI{iroi}" for iroi in range(len(group.datasets))],
                lambda z, p: z.copy()[p.y0 : p.y1, p.x0 : p.x1],
                group.datasets,
                suffix=lambda p: p.get_suffix(),
                func_obj=extract_roi_func_obj,
                edit=False,
            )

    def swap_axes(self):
        """Swap data axes"""
        self.compute_11(
            "SwapAxes",
            lambda z: z.T,
            func_obj=lambda obj, _orig: obj.remove_all_shapes(),
        )

    def compute_abs(self):
        """Compute absolute value"""
        self.compute_11("Abs", np.abs)

    def compute_log10(self):
        """Compute Log10"""
        self.compute_11("Log10", np.log10)

    @qt_try_except()
    def flat_field_correction(self, param: FlatFieldParam = None) -> None:
        """Compute flat field correction"""
        edit = param is None
        rawdata = self.objlist.get_sel_object().data
        flatdata = self.objlist.get_sel_object(1).data
        if edit:
            param = FlatFieldParam(_("Flat field"))
            param.set_from_datatype(rawdata.dtype)
        if not edit or param.edit(self.panel.parent()):
            rows = self.objlist.get_selected_rows()
            robj = self.panel.create_object()
            robj.title = (
                "FlatField("
                + (",".join([f"{self.prefix}{row:03d}" for row in rows]))
                + f",threshold={param.threshold})"
            )
            robj.data = flatfield(rawdata, flatdata, param.threshold)
            self.panel.add_object(robj)

    # ------Image Processing
    def apply_11_func(self, obj, orig, func, param, message):
        """Apply 11 function: 1 object in --> 1 object out"""

        # (self is used by @qt_try_except)
        # pylint: disable=unused-argument
        @qt_try_except(message)
        def apply_11_func_callback(self, obj, orig, func, param):
            """Apply 11 function callback: 1 object in --> 1 object out"""
            if param is None:
                obj.data = func(orig.data)
            else:
                obj.data = func(orig.data, param)

        return apply_11_func_callback(self, obj, orig, func, param)

    @qt_try_except()
    def calibrate(self, param: ZCalibrateParam = None) -> None:
        """Compute data linear calibration"""
        edit = param is None
        if edit:
            param = ZCalibrateParam(_("Linear calibration"), "y = a.x + b")
        self.compute_11(
            "LinearCal",
            lambda x, p: p.a * x + p.b,
            param,
            suffix=lambda p: "z={p.a}*z+{p.b}",
            edit=edit,
        )

    @qt_try_except()
    def compute_threshold(self, param: ThresholdParam = None) -> None:
        """Compute threshold clipping"""
        edit = param is None
        if edit:
            param = ThresholdParam(_("Thresholding"))
        self.compute_11(
            "Threshold",
            lambda x, p: np.clip(x, p.value, x.max()),
            param,
            suffix=lambda p: f"min={p.value} lsb",
            edit=edit,
        )

    @qt_try_except()
    def compute_clip(self, param: ClipParam = None) -> None:
        """Compute maximum data clipping"""
        edit = param is None
        if edit:
            param = ClipParam(_("Clipping"))
        self.compute_11(
            "Clip",
            lambda x, p: np.clip(x, x.min(), p.value),
            param,
            suffix=lambda p: f"max={p.value} lsb",
            edit=edit,
        )

    @qt_try_except()
    def rescale_intensity(self, param: RescaleIntensityParam = None) -> None:
        """Rescale image intensity levels"""
        edit = param is None
        if edit:
            param = RescaleIntensityParam(_("Rescale intensity"))
        self.compute_11(
            "RescaleIntensity",
            lambda x, p: exposure.rescale_intensity(
                x, in_range=p.in_range, out_range=p.out_range
            ),
            param,
            suffix=lambda p: f"in_range={p.in_range},out_range={p.out_range}",
            edit=edit,
        )

    @qt_try_except()
    def equalize_hist(self, param: EqualizeHistParam = None) -> None:
        """Histogram equalization"""
        edit = param is None
        if edit:
            param = EqualizeHistParam(_("Histogram equalization"))
        self.compute_11(
            "EqualizeHist",
            lambda x, p: exposure.equalize_hist(x, nbins=p.nbins),
            param,
            suffix=lambda p: f"nbins={p.nbins}",
            edit=edit,
        )

    @qt_try_except()
    def equalize_adapthist(self, param: EqualizeAdaptHistParam = None) -> None:
        """Adaptive histogram equalization"""
        edit = param is None
        if edit:
            param = EqualizeAdaptHistParam(_("Adaptive histogram equalization"))
        self.compute_11(
            "EqualizeAdaptHist",
            lambda x, p: exposure.equalize_adapthist(
                x, clip_limit=p.clip_limit, nbins=p.nbins
            ),
            param,
            suffix=lambda p: f"clip_limit={p.clip_limit},nbins={p.nbins}",
            edit=edit,
        )

    @staticmethod
    def func_gaussian_filter(x, p):  # pylint: disable=arguments-differ
        """Compute gaussian filter"""
        return spi.gaussian_filter(x, p.sigma)

    @qt_try_except()
    def compute_fft(self):
        """Compute FFT"""
        self.compute_11("FFT", np.fft.fft2)

    @qt_try_except()
    def compute_ifft(self):
        "Compute iFFT" ""
        self.compute_11("iFFT", np.fft.ifft2)

    @staticmethod
    def func_moving_average(x, p):  # pylint: disable=arguments-differ
        """Moving average computing function"""
        return spi.uniform_filter(x, size=p.n, mode="constant")

    @staticmethod
    def func_moving_median(x, p):  # pylint: disable=arguments-differ
        """Moving median computing function"""
        return sps.medfilt(x, kernel_size=p.n)

    @qt_try_except()
    def compute_wiener(self):
        """Compute Wiener filter"""
        self.compute_11("WienerFilter", sps.wiener)

    @qt_try_except()
    def compute_denoise_tv(self, param: DenoiseTVParam = None) -> None:
        """Compute Total Variation denoising"""
        edit = param is None
        if edit:
            param = DenoiseTVParam(_("Total variation denoising"))
        self.compute_11(
            "TV_Chambolle",
            lambda x, p: denoise_tv_chambolle(
                x, weight=p.weight, eps=p.eps, max_num_iter=p.max_num_iter
            ),
            param,
            suffix=lambda p: f"weight={p.weight},eps={p.eps},maxn={p.max_num_iter}",
            edit=edit,
        )

    @qt_try_except()
    def compute_denoise_bilateral(self, param: DenoiseBilateralParam = None) -> None:
        """Compute bilateral filter denoising"""
        edit = param is None
        if edit:
            param = DenoiseBilateralParam(_("Bilateral filtering"))
        self.compute_11(
            "DenoiseBilateral",
            lambda x, p: denoise_bilateral(
                x, sigma_spatial=p.sigma_spatial, mode=p.mode, cval=p.cval
            ),
            param,
            suffix=lambda p: f"σspatial={p.sigma_spatial},mode={p.mode},cval={p.cval}",
            edit=edit,
        )

    @qt_try_except()
    def compute_denoise_wavelet(self, param: DenoiseWaveletParam = None) -> None:
        """Compute Wavelet denoising"""
        edit = param is None
        if edit:
            param = DenoiseWaveletParam(_("Wavelet denoising"))
        self.compute_11(
            "DenoiseWavelet",
            lambda x, p: denoise_wavelet(
                x,
                wavelet=p.wavelet,
                mode=p.mode,
                method=p.method,
            ),
            param,
            suffix=lambda p: f"wavelet={p.wavelet},mode={p.mode},method={p.method}",
            edit=edit,
        )

    @qt_try_except()
    def compute_denoise_tophat(self, param: MorphologyParam = None) -> None:
        """Denoise using White Top-Hat"""
        edit = param is None
        if edit:
            param = MorphologyParam(_("Denoise / Top-Hat"))

        self.compute_11(
            "DenoiseWhiteTopHat",
            lambda x, p: x - morphology.white_tophat(x, morphology.disk(p.radius)),
            param,
            suffix=lambda p: f"radius={p.radius}",
            edit=edit,
        )

    def _morph(self, param, func, title, name):
        """Compute morphological transform"""
        edit = param is None
        if edit:
            param = MorphologyParam(title)

        self.compute_11(
            name,
            lambda x, p: func(x, morphology.disk(p.radius)),
            param,
            suffix=lambda p: f"radius={p.radius}",
            edit=edit,
        )

    @qt_try_except()
    def compute_white_tophat(self, param: MorphologyParam = None) -> None:
        """Compute White Top-Hat"""
        self._morph(
            param, morphology.white_tophat, _("White Top-Hat"), "WhiteTopHatDisk"
        )

    @qt_try_except()
    def compute_black_tophat(self, param: MorphologyParam = None) -> None:
        """Compute Black Top-Hat"""
        self._morph(
            param, morphology.black_tophat, _("Black Top-Hat"), "BlackTopHatDisk"
        )

    @qt_try_except()
    def compute_erosion(self, param: MorphologyParam = None) -> None:
        """Compute Erosion"""
        self._morph(param, morphology.erosion, _("Erosion"), "ErosionDisk")

    @qt_try_except()
    def compute_dilation(self, param: MorphologyParam = None) -> None:
        """Compute Dilation"""
        self._morph(param, morphology.dilation, _("Dilation"), "DilationDisk")

    @qt_try_except()
    def compute_opening(self, param: MorphologyParam = None) -> None:
        """Compute morphological opening"""
        self._morph(param, morphology.opening, _("Opening"), "OpeningDisk")

    @qt_try_except()
    def compute_closing(self, param: MorphologyParam = None) -> None:
        """Compute morphological closing"""
        self._morph(param, morphology.closing, _("Closing"), "ClosingDisk")

    @qt_try_except()
    def compute_canny(self, param: CannyParam = None) -> None:
        """Denoise using White Top-Hat"""
        edit = param is None
        if edit:
            param = CannyParam(_("Canny filter"))

        self.compute_11(
            "Canny",
            lambda x, p: np.array(
                feature.canny(
                    x,
                    sigma=p.sigma,
                    low_threshold=p.low_threshold,
                    high_threshold=p.high_threshold,
                    use_quantiles=p.use_quantiles,
                    mode=p.mode,
                    cval=p.cval,
                ),
                dtype=np.uint8,
            ),
            param,
            suffix=lambda p: f"sigma={p.sigma},low_threshold={p.low_threshold},"
            f"high_threshold={p.high_threshold},use_quantiles={p.use_quantiles},"
            f"mode={p.mode},cval={p.cval}",
            edit=edit,
        )

    # ------Image Computing
    @staticmethod
    def __apply_origin_size_roi(image, func, *args) -> np.ndarray:
        """Exec computation taking into account image x0, y0, dx, dy and ROIs"""
        res = []
        for i_roi in image.iterate_roi_indexes():
            coords = func(image.get_data(i_roi), *args)
            if coords.size:
                if image.roi is not None:
                    x0, y0, _x1, _y1 = RoiDataItem(image.roi[i_roi]).get_rect()
                    coords[:, ::2] += x0
                    coords[:, 1::2] += y0
                coords[:, ::2] = image.dx * coords[:, ::2] + image.x0
                coords[:, 1::2] = image.dy * coords[:, 1::2] + image.y0
                idx = np.ones((coords.shape[0], 1)) * i_roi
                coords = np.hstack([idx, coords])
                res.append(coords)
        if res:
            return np.vstack(res)
        return None

    @qt_try_except()
    def compute_centroid(self):
        """Compute image centroid"""

        def get_centroid_coords(data: np.ndarray):
            """Return centroid coordinates"""
            y, x = get_centroid_fourier(data)
            return np.array([(x, y)])

        def centroid(image: ImageParam):
            """Compute centroid"""
            res = self.__apply_origin_size_roi(image, get_centroid_coords)
            if res is not None:
                return image.add_resultshape("Centroid", ShapeTypes.MARKER, res)
            return None

        self.compute_10(_("Centroid"), centroid)

    @qt_try_except()
    def compute_enclosing_circle(self):
        """Compute minimum enclosing circle"""

        def get_enclosing_circle_coords(data: np.ndarray):
            """Return diameter coords for the circle contour enclosing image
            values above threshold (FWHM)"""
            x, y, r = get_enclosing_circle(data)
            return np.array([[x - r, y, x + r, y]])

        def enclosing_circle(image: ImageParam):
            """Compute minimum enclosing circle"""
            res = self.__apply_origin_size_roi(image, get_enclosing_circle_coords)
            if res is not None:
                return image.add_resultshape("MinEnclosCircle", ShapeTypes.CIRCLE, res)
            return None

        # TODO: [P2] Find a way to add the circle to the computing results
        #  as in "enclosingcircle_test.py"
        self.compute_10(_("MinEnclosingCircle"), enclosing_circle)

    @qt_try_except()
    def compute_peak_detection(self, param: PeakDetectionParam = None) -> None:
        """Compute 2D peak detection"""

        def peak_detection(image: ImageParam, p: PeakDetectionParam):
            """Compute centroid"""
            res = self.__apply_origin_size_roi(
                image, get_2d_peaks_coords, p.size, p.threshold
            )
            if res is not None:
                return image.add_resultshape("Peaks", ShapeTypes.POINT, res)
            return None

        edit = param is None
        if edit:
            data = self.objlist.get_sel_object().data
            param = PeakDetectionParam()
            param.size = max(min(data.shape) // 40, 50)

        results = self.compute_10(_("Peaks"), peak_detection, param, edit=edit)
        if results is not None and param.create_rois:
            with create_progress_bar(
                self.panel, _("Create regions of interest"), max_=len(results)
            ) as progress:
                for idx, (row, result) in enumerate(results.items()):
                    progress.setValue(idx)
                    QW.QApplication.processEvents()
                    if progress.wasCanceled():
                        break
                    obj = self.objlist[row]
                    dist = distance_matrix(result.data)
                    dist_min = dist[dist != 0].min()
                    assert dist_min > 0
                    radius = int(0.5 * dist_min / np.sqrt(2) - 1)
                    assert radius >= 1
                    roicoords = []
                    ymax, xmax = obj.data.shape
                    for x, y in result.data:
                        coords = [
                            max(x - radius, 0),
                            max(y - radius, 0),
                            min(x + radius, xmax),
                            min(y + radius, ymax),
                        ]
                        roicoords.append(coords)
                    obj.roi = np.array(roicoords, int)
                    self.SIG_ADD_SHAPE.emit(row)
                    self.panel.selection_changed()
                    self.panel.SIG_UPDATE_PLOT_ITEM.emit(row)

    @qt_try_except()
    def compute_contour_shape(self, param: ContourShapeParam = None) -> None:
        """Compute contour shape fit"""

        def contour_shape(image: ImageParam, p: ContourShapeParam):
            """Compute contour shape fit"""
            res = self.__apply_origin_size_roi(
                image, get_contour_shapes, p.shape, p.threshold
            )
            if res is not None:
                shape = ShapeTypes.CIRCLE if p.shape == "circle" else ShapeTypes.ELLIPSE
                return image.add_resultshape("Contour", shape, res)
            return None

        edit = param is None
        if edit:
            param = ContourShapeParam()
        self.compute_10(_("Contour"), contour_shape, param, edit=edit)

    @qt_try_except()
    def compute_hough_circle_peaks(self, param: HoughCircleParam = None) -> None:
        """Compute peak detection based on a circle Hough transform"""

        def hough_circles(image: ImageParam, p: HoughCircleParam):
            """Compute Hough circles"""
            res = self.__apply_origin_size_roi(
                image,
                get_hough_circle_peaks,
                p.min_radius,
                p.max_radius,
                None,
                p.min_distance,
            )
            if res is not None:
                return image.add_resultshape("Circles", ShapeTypes.CIRCLE, res)
            return None

        edit = param is None
        if edit:
            param = HoughCircleParam()
        self.compute_10(_("Circles"), hough_circles, param, edit=edit)

    @qt_try_except()
    def compute_blob_doh(self, param: BlobDOHParam = None) -> None:
        """Compute blob detection using Determinant of Hessian method"""

        def blobs(image: ImageParam, p: BlobDOHParam):
            """Compute blobs"""
            res = self.__apply_origin_size_roi(
                image,
                find_blobs_doh,
                p.min_sigma,
                p.max_sigma,
                p.overlap,
                p.log_scale,
            )
            if res is not None:
                return image.add_resultshape("Blobs", ShapeTypes.CIRCLE, res)
            return None

        edit = param is None
        if edit:
            param = BlobDOHParam()
        self.compute_10(_("Blobs"), blobs, param, edit=edit)

    @qt_try_except()
    def compute_blob_opencv(self, param: BlobOpenCVParam = None) -> None:
        """Compute blob detection using OpenCV"""

        def blobs(image: ImageParam, p: BlobOpenCVParam):
            """Compute blobs"""
            res = self.__apply_origin_size_roi(
                image,
                find_blobs_opencv,
                p.min_threshold,
                p.max_threshold,
                p.min_repeatability,
                p.min_dist_between_blobs,
                p.filter_by_color,
                p.blob_color,
                p.filter_by_area,
                p.min_area,
                p.max_area,
                p.filter_by_circularity,
                p.min_circularity,
                p.max_circularity,
                p.filter_by_inertia,
                p.min_inertia_ratio,
                p.max_inertia_ratio,
                p.filter_by_convexity,
                p.min_convexity,
                p.max_convexity,
            )
            if res is not None:
                return image.add_resultshape("Blobs", ShapeTypes.CIRCLE, res)
            return None

        edit = param is None
        if edit:
            param = BlobOpenCVParam()
        self.compute_10(_("Blobs"), blobs, param, edit=edit)

    def _get_stat_funcs(self):
        """Return statistics functions list"""
        # Be careful to use systematically functions adapted to masked arrays
        # (e.g. numpy.ma median, and *not* numpy.median)
        return [
            ("min(z)", lambda z: z.min()),
            ("max(z)", lambda z: z.max()),
            ("<z>", lambda z: z.mean()),
            ("Median(z)", ma.median),
            ("σ(z)", lambda z: z.std()),
            ("Σ(z)", lambda z: z.sum()),
            ("<z>/σ(z)", lambda z: z.mean() / z.std()),
        ]
