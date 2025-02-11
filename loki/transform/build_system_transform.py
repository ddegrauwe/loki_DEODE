# (C) Copyright 2018- ECMWF.
# This software is licensed under the terms of the Apache Licence Version 2.0
# which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.
# In applying this licence, ECMWF does not waive the privileges and immunities
# granted to it by virtue of its status as an intergovernmental organisation
# nor does it submit to any jurisdiction.

"""
Transformations to be used in build-system level tasks
"""

from pathlib import Path

from loki.transform.transformation import Transformation
from loki.bulk.item import SubroutineItem, GlobalVarImportItem

__all__ = ['FileWriteTransformation']


class FileWriteTransformation(Transformation):
    """
    Write out modified source files to a select build directory

    Parameters
    ----------
    builddir : str or path
        Directory for the output to be written to
    mode : str, optional
        "Mode" identifier string to add in front of the file suffix
    suffix : str, optional
        File suffix to determine file type for all written file. If
        omitted, it will preserve the original file type.
    cuf : bool, optional
        Use CUF (CUDA Fortran) backend instead of Fortran backend.
    include_module_var_imports : bool, optional
        Flag to force the :any:`Scheduler` traversal graph to recognise
        module variable imports and write the modified module files.
    """

    # This transformation is applied over the file graph
    traverse_file_graph = True

    def __init__(
            self, builddir=None, mode='loki', suffix=None, cuf=False,
            include_module_var_imports=False
    ):
        self.builddir = Path(builddir)
        self.mode = mode
        self.suffix = suffix
        self.cuf = cuf
        self.include_module_var_imports = include_module_var_imports

    @property
    def item_filter(self):
        """
        Override ``item_filter`` to configure whether module variable
        imports are honoured in the :any:`Scheduler` traversal.
        """
        if self.include_module_var_imports:
            return (SubroutineItem, GlobalVarImportItem)
        return SubroutineItem

    def transform_file(self, sourcefile, **kwargs):
        item = kwargs.get('item', None)
        if not item and 'items' in kwargs:
            if kwargs['items']:
                item = kwargs['items'][0]

        if not item:
            raise ValueError('No Item provided; required to determine file write path')

        path = Path(item.path)
        suffix = self.suffix if self.suffix else path.suffix
        sourcepath = Path(item.path).with_suffix(f'.{self.mode}{suffix}')
        if self.builddir is not None:
            sourcepath = self.builddir/sourcepath.name
        sourcefile.write(path=sourcepath, cuf=self.cuf)
