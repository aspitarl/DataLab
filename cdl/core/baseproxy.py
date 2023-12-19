# -*- coding: utf-8 -*-
#
# Licensed under the terms of the BSD 3-Clause
# (see cdl/LICENSE for details)

"""
DataLab base proxy module
-------------------------
"""

# How to add a new method to the proxy:
# -------------------------------------
#
# 1.  Add the method to the AbstractCDLControl class, as an abstract method
#
# 2a. If the method requires any data conversion to get through the XML-RPC layer,
#     implement the method in both LocalProxy and RemoteClient classes
#
# 2b. If the method does not require any data conversion, implement the method
#     directly in the BaseProxy class, so that it is available to both LocalProxy
#     and RemoteClient classes without any code duplication
#
# 3.  Implement the method in the CDLMainWindow class
#
# 4.  Implement the method in the RemoteServer class (it will be automatically
#     registered as an XML-RPC method, like all methods of AbstractCDLControl)

from __future__ import annotations

import abc
from collections.abc import Callable
from typing import TYPE_CHECKING

import guidata.dataset as gds
import numpy as np

from cdl.obj import ImageObj, SignalObj

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterator

    from cdl.core.gui.main import CDLMainWindow
    from cdl.core.remote import ServerProxy


class AbstractCDLControl(abc.ABC):
    """Abstract base class for controlling DataLab (main window or remote server)"""

    def __len__(self) -> int:
        """Return number of objects"""
        return len(self.get_object_uuids())

    def __getitem__(
        self,
        nb_id_title: int | str | None = None,
    ) -> SignalObj | ImageObj:
        """Return object"""
        return self.get_object(nb_id_title)

    def __iter__(self) -> Iterator[SignalObj | ImageObj]:
        """Iterate over objects"""
        uuids = self.get_object_uuids()
        for uuid in uuids:
            yield self.get_object(uuid)

    def __str__(self) -> str:
        """Return object string representation"""
        return super().__repr__()

    def __repr__(self) -> str:
        """Return object representation"""
        titles = self.get_object_titles()
        uuids = self.get_object_uuids()
        text = f"{str(self)} (DataLab, {len(titles)} items):\n"
        for uuid, title in zip(uuids, titles):
            text += f"  {uuid}: {title}\n"
        return text

    def __bool__(self) -> bool:
        """Return True if model is not empty"""
        return bool(self.get_object_uuids())

    def __contains__(self, id_title: str) -> bool:
        """Return True if object (UUID or title) is in model"""
        return id_title in (self.get_object_titles() + self.get_object_uuids())

    @classmethod
    def get_public_methods(cls) -> list[str]:
        """Return all public methods of the class, except itself.

        Returns:
            list[str]: List of public methods
        """
        return [
            method
            for method in dir(cls)
            if not method.startswith("_") and method != "get_public_methods"
        ]

    @abc.abstractmethod
    def get_version(self) -> str:
        """Return DataLab version.

        Returns:
            str: DataLab version
        """

    @abc.abstractmethod
    def close_application(self) -> None:
        """Close DataLab application"""

    @abc.abstractmethod
    def raise_window(self) -> None:
        """Raise DataLab window"""

    @abc.abstractmethod
    def get_current_panel(self) -> str:
        """Return current panel name.

        Returns:
            str: Panel name (valid values: "signal", "image", "macro"))
        """

    @abc.abstractmethod
    def set_current_panel(self, panel: str) -> None:
        """Switch to panel.

        Args:
            panel (str): Panel name (valid values: "signal", "image", "macro"))
        """

    @abc.abstractmethod
    def reset_all(self) -> None:
        """Reset all application data"""

    @abc.abstractmethod
    def toggle_auto_refresh(self, state: bool) -> None:
        """Toggle auto refresh state.

        Args:
            state (bool): Auto refresh state
        """

    @abc.abstractmethod
    def toggle_show_titles(self, state: bool) -> None:
        """Toggle show titles state.

        Args:
            state (bool): Show titles state
        """

    @abc.abstractmethod
    def save_to_h5_file(self, filename: str) -> None:
        """Save to a DataLab HDF5 file.

        Args:
            filename (str): HDF5 file name
        """

    @abc.abstractmethod
    def open_h5_files(
        self,
        h5files: list[str] | None = None,
        import_all: bool | None = None,
        reset_all: bool | None = None,
    ) -> None:
        """Open a DataLab HDF5 file or import from any other HDF5 file.

        Args:
            h5files (list[str] | None): List of HDF5 files to open. Defaults to None.
            import_all (bool | None): Import all objects from HDF5 files.
                Defaults to None.
            reset_all (bool | None): Reset all application data. Defaults to None.
        """

    @abc.abstractmethod
    def import_h5_file(self, filename: str, reset_all: bool | None = None) -> None:
        """Open DataLab HDF5 browser to Import HDF5 file.

        Args:
            filename (str): HDF5 file name
            reset_all (bool | None): Reset all application data. Defaults to None.
        """

    @abc.abstractmethod
    def open_object(self, filename: str) -> None:
        """Open object from file in current panel (signal/image).

        Args:
            filename (str): File name
        """

    @abc.abstractmethod
    def add_signal(
        self,
        title: str,
        xdata: np.ndarray,
        ydata: np.ndarray,
        xunit: str | None = None,
        yunit: str | None = None,
        xlabel: str | None = None,
        ylabel: str | None = None,
    ) -> bool:  # pylint: disable=too-many-arguments
        """Add signal data to DataLab.

        Args:
            title (str): Signal title
            xdata (numpy.ndarray): X data
            ydata (numpy.ndarray): Y data
            xunit (str | None): X unit. Defaults to None.
            yunit (str | None): Y unit. Defaults to None.
            xlabel (str | None): X label. Defaults to None.
            ylabel (str | None): Y label. Defaults to None.

        Returns:
            bool: True if signal was added successfully, False otherwise

        Raises:
            ValueError: Invalid xdata dtype
            ValueError: Invalid ydata dtype
        """

    @abc.abstractmethod
    def add_image(
        self,
        title: str,
        data: np.ndarray,
        xunit: str | None = None,
        yunit: str | None = None,
        zunit: str | None = None,
        xlabel: str | None = None,
        ylabel: str | None = None,
        zlabel: str | None = None,
    ) -> bool:  # pylint: disable=too-many-arguments
        """Add image data to DataLab.

        Args:
            title (str): Image title
            data (numpy.ndarray): Image data
            xunit (str | None): X unit. Defaults to None.
            yunit (str | None): Y unit. Defaults to None.
            zunit (str | None): Z unit. Defaults to None.
            xlabel (str | None): X label. Defaults to None.
            ylabel (str | None): Y label. Defaults to None.
            zlabel (str | None): Z label. Defaults to None.

        Returns:
            bool: True if image was added successfully, False otherwise

        Raises:
            ValueError: Invalid data dtype
        """

    @abc.abstractmethod
    def get_sel_object_uuids(self, include_groups: bool = False) -> list[str]:
        """Return selected objects uuids.

        Args:
            include_groups: If True, also return objects from selected groups.

        Returns:
            List of selected objects uuids.
        """

    @abc.abstractmethod
    def select_objects(
        self,
        selection: list[int | str],
        panel: str | None = None,
    ) -> None:
        """Select objects in current panel.

        Args:
            selection: List of object numbers (1 to N) or uuids to select
            panel: panel name (valid values: "signal", "image").
             If None, current panel is used. Defaults to None.
        """

    @abc.abstractmethod
    def select_groups(
        self, selection: list[int | str] | None = None, panel: str | None = None
    ) -> None:
        """Select groups in current panel.

        Args:
            selection: List of group numbers (1 to N), or list of group uuids,
             or None to select all groups. Defaults to None.
            panel (str | None): panel name (valid values: "signal", "image").
                If None, current panel is used. Defaults to None.
        """

    @abc.abstractmethod
    def delete_metadata(self, refresh_plot: bool = True) -> None:
        """Delete metadata of selected objects

        Args:
            refresh_plot (bool | None): Refresh plot. Defaults to True.
        """

    @abc.abstractmethod
    def get_group_titles_with_object_infos(
        self,
    ) -> tuple[list[str], list[list[str]], list[list[str]]]:
        """Return groups titles and lists of inner objects uuids and titles.

        Returns:
            Tuple: groups titles, lists of inner objects uuids and titles
        """

    @abc.abstractmethod
    def get_object_titles(self, panel: str | None = None) -> list[str]:
        """Get object (signal/image) list for current panel.
        Objects are sorted by group number and object index in group.

        Args:
            panel (str | None): panel name (valid values: "signal", "image").
                If None, current panel is used.

        Returns:
            list[str]: list of object titles

        Raises:
            ValueError: if panel not found
        """

    @abc.abstractmethod
    def get_object(
        self,
        nb_id_title: int | str | None = None,
        panel: str | None = None,
    ) -> SignalObj | ImageObj:
        """Get object (signal/image) from index.

        Args:
            nb_id_title: Object number, or object id, or object title.
             Defaults to None (current object).
            panel: Panel name. Defaults to None (current panel).

        Returns:
            Object

        Raises:
            KeyError: if object not found
        """

    @abc.abstractmethod
    def get_object_uuids(self, panel: str | None = None) -> list[str]:
        """Get object (signal/image) uuid list for current panel.
        Objects are sorted by group number and object index in group.

        Args:
            panel (str | None): panel name (valid values: "signal", "image").
                If None, current panel is used.

        Returns:
            list[str]: list of object uuids

        Raises:
            ValueError: if panel not found
        """

    @abc.abstractmethod
    def get_object_shapes(
        self,
        nb_id_title: int | str | None = None,
        panel: str | None = None,
    ) -> list:
        """Get plot item shapes associated to object (signal/image).

        Args:
            nb_id_title: Object number, or object id, or object title.
             Defaults to None (current object).
            panel: Panel name. Defaults to None (current panel).

        Returns:
            List of plot item shapes
        """

    @abc.abstractmethod
    def add_annotations_from_items(
        self, items: list, refresh_plot: bool = True, panel: str | None = None
    ) -> None:
        """Add object annotations (annotation plot items).

        Args:
            items (list): annotation plot items
            refresh_plot (bool | None): refresh plot. Defaults to True.
            panel (str | None): panel name (valid values: "signal", "image").
                If None, current panel is used.
        """

    @abc.abstractmethod
    def add_label_with_title(
        self, title: str | None = None, panel: str | None = None
    ) -> None:
        """Add a label with object title on the associated plot

        Args:
            title (str | None): Label title. Defaults to None.
                If None, the title is the object title.
            panel (str | None): panel name (valid values: "signal", "image").
                If None, current panel is used.
        """

    @abc.abstractmethod
    def calc(self, name: str, param: gds.DataSet | None = None) -> gds.DataSet:
        """Call compute function ``name`` in current panel's processor.

        Args:
            name (str): Compute function name
            param (guidata.dataset.DataSet | None): Compute function
            parameter. Defaults to None.

        Returns:
            guidata.dataset.DataSet: Compute function result
        """

    def __getattr__(self, name: str) -> Callable:
        """Return compute function ``name`` in current panel's processor.

        Args:
            name (str): Compute function name

        Returns:
            Callable: Compute function

        Raises:
            AttributeError: If compute function ``name`` does not exist
        """

        def compute_func(param: gds.DataSet | None = None) -> gds.DataSet:
            """Compute function.

            Args:
                param (guidata.dataset.DataSet | None): Compute function
                 parameter. Defaults to None.

            Returns:
                guidata.dataset.DataSet: Compute function result
            """
            return self.calc(name, param)

        if name.startswith("compute_"):
            return compute_func
        raise AttributeError(f"DataLab has no compute function '{name}'")


class BaseProxy(AbstractCDLControl, metaclass=abc.ABCMeta):
    """Common base class for DataLab proxies

    Args:
        cdl (CDLMainWindow | ServerProxy | None): CDLMainWindow instance or
            ServerProxy instance. If None, then the proxy implementation will
            have to set it later (e.g. see RemoteClient).
    """

    def __init__(self, cdl: CDLMainWindow | ServerProxy | None = None) -> None:
        self._cdl = cdl

    def get_version(self) -> str:
        """Return DataLab version.

        Returns:
            str: DataLab version
        """
        return self._cdl.get_version()

    def close_application(self) -> None:
        """Close DataLab application"""
        self._cdl.close_application()

    def raise_window(self) -> None:
        """Raise DataLab window"""
        self._cdl.raise_window()

    def get_current_panel(self) -> str:
        """Return current panel name.

        Returns:
            str: Panel name (valid values: "signal", "image", "macro"))
        """
        return self._cdl.get_current_panel()

    def set_current_panel(self, panel: str) -> None:
        """Switch to panel.

        Args:
            panel (str): Panel name (valid values: "signal", "image", "macro"))
        """
        self._cdl.set_current_panel(panel)

    def reset_all(self) -> None:
        """Reset all application data"""
        self._cdl.reset_all()

    def toggle_auto_refresh(self, state: bool) -> None:
        """Toggle auto refresh state.

        Args:
            state (bool): Auto refresh state
        """
        self._cdl.toggle_auto_refresh(state)

    # Returns a context manager to temporarily disable autorefresh
    def context_no_refresh(self) -> Callable:
        """Return a context manager to temporarily disable auto refresh.

        Returns:
            Context manager

        Example:

            >>> with proxy.context_no_refresh():
            ...     proxy.add_image("image1", data1)
            ...     proxy.compute_fft()
            ...     proxy.compute_wiener()
            ...     proxy.compute_ifft()
            ...     # Auto refresh is disabled during the above operations
        """

        class NoRefreshContextManager:
            """Context manager to temporarily disable auto refresh"""

            def __init__(self, cdl: AbstractCDLControl) -> None:
                self._cdl = cdl

            def __enter__(self) -> None:
                self._cdl.toggle_auto_refresh(False)

            def __exit__(self, exc_type, exc_value, traceback) -> None:
                self._cdl.toggle_auto_refresh(True)

        return NoRefreshContextManager(self)

    def toggle_show_titles(self, state: bool) -> None:
        """Toggle show titles state.

        Args:
            state (bool): Show titles state
        """
        self._cdl.toggle_show_titles(state)

    def save_to_h5_file(self, filename: str) -> None:
        """Save to a DataLab HDF5 file.

        Args:
            filename (str): HDF5 file name
        """
        self._cdl.save_to_h5_file(filename)

    def open_h5_files(
        self,
        h5files: list[str] | None = None,
        import_all: bool | None = None,
        reset_all: bool | None = None,
    ) -> None:
        """Open a DataLab HDF5 file or import from any other HDF5 file.

        Args:
            h5files (list[str] | None): List of HDF5 files to open. Defaults to None.
            import_all (bool | None): Import all objects from HDF5 files.
                Defaults to None.
            reset_all (bool | None): Reset all application data. Defaults to None.
        """
        self._cdl.open_h5_files(h5files, import_all, reset_all)

    def import_h5_file(self, filename: str, reset_all: bool | None = None) -> None:
        """Open DataLab HDF5 browser to Import HDF5 file.

        Args:
            filename (str): HDF5 file name
            reset_all (bool | None): Reset all application data. Defaults to None.
        """
        self._cdl.import_h5_file(filename, reset_all)

    def open_object(self, filename: str) -> None:
        """Open object from file in current panel (signal/image).

        Args:
            filename (str): File name
        """
        self._cdl.open_object(filename)

    def get_sel_object_uuids(self, include_groups: bool = False) -> list[str]:
        """Return selected objects uuids.

        Args:
            include_groups: If True, also return objects from selected groups.

        Returns:
            List of selected objects uuids.
        """
        return self._cdl.get_sel_object_uuids(include_groups)

    def select_objects(
        self,
        selection: list[int | str],
        panel: str | None = None,
    ) -> None:
        """Select objects in current panel.

        Args:
            selection: List of object numbers (1 to N) or uuids to select
            panel: panel name (valid values: "signal", "image").
             If None, current panel is used. Defaults to None.
        """
        self._cdl.select_objects(selection, panel)

    def select_groups(
        self, selection: list[int | str] | None = None, panel: str | None = None
    ) -> None:
        """Select groups in current panel.

        Args:
            selection: List of group numbers (1 to N), or list of group uuids,
             or None to select all groups. Defaults to None.
            panel (str | None): panel name (valid values: "signal", "image").
                If None, current panel is used. Defaults to None.
        """
        self._cdl.select_groups(selection, panel)

    def delete_metadata(self, refresh_plot: bool = True) -> None:
        """Delete metadata of selected objects

        Args:
            refresh_plot (bool | None): Refresh plot. Defaults to True.
        """
        self._cdl.delete_metadata(refresh_plot)

    def get_group_titles_with_object_infos(
        self,
    ) -> tuple[list[str], list[list[str]], list[list[str]]]:
        """Return groups titles and lists of inner objects uuids and titles.

        Returns:
            Tuple: groups titles, lists of inner objects uuids and titles
        """
        return self._cdl.get_group_titles_with_object_infos()

    def get_object_titles(self, panel: str | None = None) -> list[str]:
        """Get object (signal/image) list for current panel.
        Objects are sorted by group number and object index in group.

        Args:
            panel (str | None): panel name (valid values: "signal", "image").
                If None, current panel is used.

        Returns:
            list[str]: list of object titles

        Raises:
            ValueError: if panel not found
        """
        return self._cdl.get_object_titles(panel)

    def get_object_uuids(self, panel: str | None = None) -> list[str]:
        """Get object (signal/image) uuid list for current panel.
        Objects are sorted by group number and object index in group.

        Args:
            panel (str | None): panel name (valid values: "signal", "image").
                If None, current panel is used.

        Returns:
            list[str]: list of object uuids

        Raises:
            ValueError: if panel not found
        """
        return self._cdl.get_object_uuids(panel)

    def add_label_with_title(
        self, title: str | None = None, panel: str | None = None
    ) -> None:
        """Add a label with object title on the associated plot

        Args:
            title (str | None): Label title. Defaults to None.
                If None, the title is the object title.
            panel (str | None): panel name (valid values: "signal", "image").
                If None, current panel is used.
        """
        self._cdl.add_label_with_title(title, panel)

    # ----- Proxy specific methods ------------------------------------------------
    # (not available symetrically in AbstractCDLControl)

    @abc.abstractmethod
    def add_object(self, obj: SignalObj | ImageObj) -> None:
        """Add object to DataLab.

        Args:
            obj (SignalObj | ImageObj): Signal or image object
        """
