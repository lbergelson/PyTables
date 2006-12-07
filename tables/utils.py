########################################################################
#
#       License: BSD
#       Created: March 4, 2003
#       Author:  Francesc Altet - faltet@carabos.com
#
#       $Id$
#
########################################################################

"""Utility functions

"""

import re
import warnings
import keyword
import os, os.path
import cPickle
import sys

import numpy

try:
    import Numeric
    Numeric_imported = True
    # A map between Numpy types and Numeric
    NPtype2Numtype = {numpy.int8: Numeric.Int8,
                      numpy.int16: Numeric.Int16,
                      numpy.int32: Numeric.Int32,
                      numpy.uint8: Numeric.UInt8,
                      numpy.uint16: Numeric.UInt16,
                      numpy.uint32: Numeric.UInt32,
                      numpy.float32: Numeric.Float32,
                      numpy.float64: Numeric.Float64,
                      numpy.complex64: Numeric.Complex32,
                      numpy.complex128: Numeric.Complex64,
                      numpy.bool_: Numeric.UInt8,
                      }

except ImportError:
    Numeric_imported = False

try:
    import numarray
    import numarray.strings
    import numarray.records
    numarray_imported = True
except ImportError:
    numarray_imported = False

import tables.utilsExtension
from tables.exceptions import NaturalNameWarning
from tables.constants import CHUNKTIMES
from tables.registry import classNameDict
from tables import nriterators
from tables import nestedrecords


# The map between byteorders in NumPy and PyTables
byteorders = {'>': 'big',
              '<': 'little',
              '=': sys.byteorder,
              '|': 'irrelevant'}


# Python identifier regular expression.
pythonIdRE = re.compile('^[a-zA-Z_][a-zA-Z0-9_]*$')
# PyTables reserved identifier regular expression.
#   c: class variables
#   f: class public methods
#   g: class private methods
#   v: instance variables
reservedIdRE = re.compile('^_[cfgv]_')

# Nodes with a name *matching* this expression are considered hidden.
# For instance::
#
#   name -> visible
#   _i_name -> hidden
#
hiddenNameRE = re.compile('^_[pi]_')

# Nodes with a path *containing* this expression are considered hidden.
# For instance::
#
#   /a/b/c -> visible
#   /a/c/_i_x -> hidden
#   /a/_p_x/y -> hidden
#
hiddenPathRE = re.compile('/_[pi]_')


def getClassByName(className):
    """
    Get the node class matching the `className`.

    If the name is not registered, a ``TypeError`` is raised.  The empty
    string and ``None`` are also accepted, and mean the ``Node`` class.
    """

    # The empty string is accepted for compatibility
    # with old default arguments.
    if className is None or className == '':
        className = 'Node'

    # Get the class object corresponding to `classname`.
    if className not in classNameDict:
        raise TypeError("there is no registered node class named ``%s``"
                        % (className,))

    return classNameDict[className]


def checkNameValidity(name):
    """
    Check the validity of the `name` of an object.

    If the name is not valid, a ``ValueError`` is raised.  If it is
    valid but it can not be used with natural naming, a
    `NaturalNameWarning` is issued.
    """

    warnInfo = """\
you will not be able to use natural naming to access this object \
(but using ``getattr()`` will still work)"""

    if not isinstance(name, basestring):  # Python >= 2.3
        raise TypeError("object name is not a string: %r" % (name,))

    # Check whether `name` is a valid HDF5 name.
    # http://hdf.ncsa.uiuc.edu/HDF5/doc/UG/03_Model.html#Structure
    if name == '':
        raise ValueError("the empty string is not allowed as an object name")
    if name == '.':
        raise ValueError("``.`` is not allowed as an object name")
    if '/' in name:
        raise ValueError(
            "the ``/`` character is not allowed in object names: %r" % (name,))

    # Check whether `name` is a valid Python identifier.
    if not pythonIdRE.match(name):
        warnings.warn("""\
object name is not a valid Python identifier: %r; \
it does not match the pattern ``%s``; %s"""
                      % (name, pythonIdRE.pattern, warnInfo),
                      NaturalNameWarning)
        return

    # However, Python identifiers and keywords have the same form.
    if keyword.iskeyword(name):
        warnings.warn("object name is a Python keyword: %r; %s"
                      % (name, warnInfo), NaturalNameWarning)
        return

    # Still, names starting with reserved prefixes are not allowed.
    if reservedIdRE.match(name):
        raise ValueError("object name starts with a reserved prefix: %r; "
                         "it matches the pattern ``%s``"
                         % (name, reservedIdRE.pattern))

    # ``__members__`` is the only exception to that rule.
    if name == '__members__':
        raise ValueError("``__members__`` is not allowed as an object name")


def is_idx(index):
    """Checks if an object can work as an index or not."""

    if type(index) in (int,long):
        return True
    elif hasattr(index, "__index__"):  # Only works on Python 2.5 on (as per PEP 357)
        try:
            idx = index.__index__()
            return True
        except TypeError:
            return False
    elif isinstance(index, numpy.integer):
        return True

    return False


def idx2long(index):
    """Convert a possible index into a long int"""

    if is_idx(index):
        return long(index)
    else:
        raise TypeError, "not an integer type."


# This function is appropriate for calls to __getitem__ methods
def processRange(nrows, start=None, stop=None, step=1):

    if step and step < 0:
        raise ValueError, "slice step cannot be negative"
    # (start, stop, step) = slice(start, stop, step).indices(nrows)  # Python > 2.3
    # The next function is a substitute for slice().indices in order to
    # support full 64-bit integer for slices (Python 2.4 does not
    # support that yet)
    # F. Altet 2005-05-08
    # In order to convert possible numpy.integer values to long ones
    # F. Altet 2006-05-02
    if start is not None: start = idx2long(start)
    if stop is not None: stop = idx2long(stop)
    if step is not None: step = idx2long(step)
    (start, stop, step) =  tables.utilsExtension.getIndices( \
        slice(start, stop, step), long(nrows))
    # Some protection against empty ranges
    if start > stop:
        start = stop
    return (start, stop, step)


# This function is appropiate for calls to read() methods
def processRangeRead(nrows, start=None, stop=None, step=1):
    if start is not None and stop is None:
        # Protection against start greater than available records
        # nrows == 0 is a special case for empty objects
        #start = idx2long(start)    # XXX to delete
        if nrows > 0 and start >= nrows:
            raise IndexError, "Start of range (%s) is greater than number of rows (%s)." % (start, nrows)
        step = 1
        if start == -1:  # corner case
            stop = nrows
        else:
            stop = start + 1
    # Finally, get the correct values
    start, stop, step = processRange(nrows, start, stop, step)

    return (start, stop, step)


def convToNP(arr):
    "Convert a generic, homogeneous, object into a NumPy contiguous object."

    if (type(arr) == numpy.ndarray and
        arr.dtype.kind not in ['V', 'U']):  # not in void, unicode
        flavor = "numpy"
        nparr = arr
    elif (numarray_imported and
          type(arr) in (numarray.NumArray, numarray.strings.CharArray)):
        flavor = "numarray"
        nparr = numpy.asarray(arr)
    elif Numeric_imported and type(arr) == Numeric.ArrayType:
        flavor = "numeric"
        nparr = numpy.asarray(arr)
    elif (type(arr) in (tuple, list, int, float, complex, str) or
          numpy.isscalar(arr)):  # numpy scalars will be treated as python objects
        flavor = "python"
        # Test if this can be converted into a NumPy object
        try:
            nparr = numpy.array(arr)
        # If not, issue an error
        except Exception, exc:  #XXX
            raise ValueError, \
"""The object '%s' of type <%s> can't be converted into a NumPy array.
Sorry, but this object is not supported. The error was <%s>:""" % \
        (arr, type(arr), exc)
    else:
        raise TypeError, \
"""The object '%s' of type <%s> is not in the list of supported objects:
numpy, numarray, numeric, homogeneous list or tuple, int, float, complex or str.
Sorry, but this object is not supported in this context.""" % (arr, type(arr))

    # Make a copy of the array in case it is not contiguous
    if nparr.flags.contiguous == False:
        nparr = nparr.copy()

    return nparr, flavor


# This is used in VLArray and EArray to produce NumPy object compliant
# with atom from a generic python type.  If copy is stated as True, it
# is assured that it will return a copy of the object and never the same
# object or a new one sharing the same memory.
def convertToNPAtom(arr, atom, copy=False):
    "Convert a generic object into a NumPy object compliant with atom."

    # First, convert the object to a NumPy array
    nparr, flavor = convToNP(arr)

    # Get copies of data if necessary for getting a contiguous buffer,
    # or if dtype is not the correct one.
    if (copy or nparr.dtype <> atom.dtype):
        nparr = numpy.array(nparr, dtype=atom.dtype)

    return nparr


def convertNPToNumeric(arr):
    """Convert a NumPy object into a Numeric one."""

    if not Numeric_imported:
        # Warn the user
        warnings.warn( \
"""You are asking for a Numeric object, but Numeric is not installed locally.
  Returning a NumPy object instead!.""")
        return arr

    # First, convert to a contiguous buffer (.tostring() is very efficient)
    arrstr = arr.tostring()
    shape = list(arr.shape)
    if arr.dtype.kind == "S":
        if arr.itemsize > 1:
            # Numeric does not support arrays with elements with a
            # size > 1. Simulate this by adding an additional dimension
            shape.append(arr.itemsize)
        arr = Numeric.fromstring(arrstr, typecode='c')
        arr = Numeric.reshape(arr, shape)
    else:
        # Try to convert to Numeric and catch possible errors
        try:
            #arr = Numeric.asarray(arr)  # Array protocol
            # It seems that the array protocol in Numeric does leak. See:
            # http://comments.gmane.org/gmane.comp.python.numeric.general/12563
            # for more info on this issue.
            typecode = NPtype2Numtype[arr.dtype.type]
            arr = Numeric.fromstring(arrstr, typecode)
            arr = Numeric.reshape(arr, shape)
        except Exception, exc:
            warnings.warn( \
"""Array cannot be converted into a Numeric object!. The error was: <%s>
""" % (exc))

    return arr


def convertNPToNumArray(arr):
    """Convert a NumPy (homogeneous) object into a NumArray one"""

    if not numarray_imported:
        # Warn the user
        warnings.warn( \
"""You are asking for a numarray object, but numarray is not installed locally.
  Returning a NumPy object instead!.""")
        return arr

    if arr.dtype.kind == "S":
        # We can't use the array protocol to do this conversion
        if arr.shape == ():
            buffer_ = arr.item()
        else:
            buffer_ = arr
        arr = numarray.strings.array(buffer=buffer_)
    else:
        #if not arr.flags.writeable or not arr.flags.aligned:
        #    # These cases are not handled by the array protocol
        #    # (at least in the current implementation)
        #    # A copy will correct this
        #    arr = arr.copy()
        # This works for regular homogeneous arrays and even for rank-0 arrays
        # Using asarray gives problems in some tests (I don't know exactly why)
        #arr = numarray.asarray(arr)  # Array protocol
        arr = numarray.array(arr)  # Array protocol (with copy)
    return arr


def convToFlavor(object, arr, caller = "Array"):
    "Convert the NumPy parameter to the correct flavor"

    if object.flavor == "numarray":
        arr = convertNPToNumArray(arr)
    elif object.flavor == "numeric":
        arr = convertNPToNumeric(arr)
    elif object.flavor == "python":
        if arr.shape <> ():
            # Lists are the default for returning multidimensional objects
            arr = arr.tolist()
        else:
            # 0-dim or scalar case
            arr = arr.item()
    elif object.flavor == "string":
        arr = arr.tostring()
        # Set the shape to () for these objects
        # F. Altet 2006-01-03
        object.shape = ()
    elif object.flavor == "Tuple":
        arr = totuple(object, arr)
    elif object.flavor == "List":
        arr = arr.tolist()
    if caller <> "VLArray":
        # For backward compatibility
        if object.flavor == "Int":
            arr = int(arr)
        elif object.flavor == "Float":
            arr = float(arr)
        elif object.flavor == "String":
            arr = arr.tostring()
            # Set the shape to () for these objects
            # F. Altet 2006-01-03
            object.shape = ()
    else:
        if object.flavor == "String":
            arr = arr.tolist()
        elif object.flavor == "VLString":
            arr = arr.tostring().decode('utf-8')
        elif object.flavor == "Object":
            # We have to check for an empty array because of a
            # possible bug in HDF5 that claims that a dataset
            # has one record when in fact, it is empty
            if arr.size == 0:
                arr = []
            else:
                arr = cPickle.loads(arr.tostring())
    return arr


def tonumarray(array, copy=False):
    """
    Create a new `NestedRecArray` from a numpy object.

    If ``copy`` is True, the a copy of the data is made. The default is
    not doing a copy.

    Example
    =======

    >>> nra = tonumarray(numpy.array([(1,11,'a'),(2,22,'b')], dtype='u1,f4,a1'))

    """

    if not (isinstance(array, numpy.ndarray) or
            type(array) == numpy.rec.recarray or
            type(array) == numpy.rec.record or
            type(array) == numpy.void):    # Check scalar case.
        raise ValueError, \
"You need to pass a numpy object, and you passed a %s." % (type(array))

    # Convert the original description based in the array protocol in
    # something that can be understood by the NestedRecArray
    # constructor.
    descr = [i for i in nestedrecords.convertFromAPDescr(array.dtype.descr)]
    # Flat the description
    flatDescr = [i for i in nriterators.flattenDescr(descr)]
    # Flat the structure descriptors
    flatFormats = [i for i in nriterators.getFormatsFromDescr(flatDescr)]
    flatNames = [i for i in nriterators.getNamesFromDescr(flatDescr)]
    # Create a regular RecArray
    if copy:
        array = array.copy()  # copy the data before creating the object
    if array.shape == ():
        shape = 1     # Scalar case. Shape = 1 will provide an adequate buffer.
    else:
        shape = array.shape
    ra = numarray.records.array(array.data, formats=flatFormats,
                                names=flatNames,
                                shape=shape,
                                byteorder=sys.byteorder,
                                aligned = False)  # aligned RecArrays
                                                  # not supported yet
    # Check whether we need a NestedRecArray as final output
    nested = False
    for name in flatNames:
        if '/' in name:
            nested = True
            break
    if nested:
        # Create the nested recarray itself
        ra = nestedrecords.NestedRecArray(ra, descr)

    return ra



def tonumpy(rna, copy=False):
    """
    Create a new heterogeneous numpy object from a numarray object.

    If ``copy`` is True, then a copy of the data is made. The default is
    not doing a copy.

    Example
    =======

    >>> nrp = fromnumarray(records.array([(1,11,'a'),(2,22,'b')], dtype='u1,f4,a1'))

    """

    if not (isinstance(rna, numarray.records.RecArray) or
            isinstance(rna, numarray.records.Record)):
        raise ValueError, \
"You need to pass a numarray (Nested)RecArray object, and you passed a %s." % \
(type(rna))

    record = False
    if isinstance(rna, numarray.records.Record):
        # Get a RecArray from a record
        row = rna.row
        rna = rna.array[row:row+1]
        record = True
    if copy:
        rna = rna.copy()
    if type(rna) == numarray.records.RecArray:
        # Create a NestedRecArray array from the RecArray to easy the
        # conversion. This is sub-optimal and should be replaced by a
        # faster way to convert a plain RecArray into a numpy recarray.
        # F. Altet 2006-06-19
        rna = nestedrecords.array(rna)
    rnp = numpy.ndarray(buffer=rna._data, shape=rna.shape,
                        dtype=rna.array_descr,
                        offset=rna._byteoffset)
    if record:
        # Get the numpy record
        rnp = rnp[row]
    return rnp


def totuple(object, arr):
    """Returns array as a (nested) tuple of elements."""
    if len(arr._shape) == 1:
        return tuple([ x for x in arr ])
    else:
        return tuple([ totuple(object, ni) for ni in arr ])


def joinPath(parentPath, name):
    """joinPath(parentPath, name) -> path.  Joins a canonical path with a name.

    Joins the given canonical path with the given child node name.
    """

    if parentPath == '/':
        pstr = '%s%s'
    else:
        pstr = '%s/%s'
    return pstr % (parentPath, name)


def splitPath(path):
    """splitPath(path) -> (parentPath, name).  Splits a canonical path.

    Splits the given canonical path into a parent path (without the trailing
    slash) and a node name.
    """

    lastSlash = path.rfind('/')
    ppath = path[:lastSlash]
    name = path[lastSlash+1:]

    if ppath == '':
        ppath = '/'

    return (ppath, name)


def isVisibleName(name):
    """Does this name make the named node a visible one?"""
    return hiddenNameRE.match(name) is None


def isVisiblePath(path):
    """Does this path make the named node a visible one?"""
    return hiddenPathRE.search(path) is None


def checkFileAccess(filename, mode='r'):
    """
    Check for file access in the specified `mode`.

    `mode` is one of the modes supported by `File` objects.  If the file
    indicated by `filename` can be accessed using that `mode`, the
    function ends successfully.  Else, an ``IOError`` is raised
    explaining the reason of the failure.

    All this paraphernalia is used to avoid the lengthy and scaring HDF5
    messages produced when there are problems opening a file.  No
    changes are ever made to the file system.
    """

    if mode == 'r':
        # The file should be readable.
        if not os.access(filename, os.F_OK):
            raise IOError("``%s`` does not exist" % (filename,))
        if not os.path.isfile(filename):
            raise IOError("``%s`` is not a regular file" % (filename,))
        if not os.access(filename, os.R_OK):
            raise IOError("file ``%s`` exists but it can not be read"
                          % (filename,))
    elif mode == 'w':
        if os.access(filename, os.F_OK):
            # Since the file is not removed but replaced,
            # it must already be accessible to read and write operations.
            checkFileAccess(filename, 'r+')
        else:
            # A new file is going to be created,
            # so the directory should be writable.
            parentname = os.path.dirname(filename)
            if not parentname:
                parentname = '.'
            if not os.access(parentname, os.F_OK):
                raise IOError("``%s`` does not exist" % (parentname,))
            if not os.path.isdir(parentname):
                raise IOError("``%s`` is not a directory" % (parentname,))
            if not os.access(parentname, os.W_OK):
                raise IOError("directory ``%s`` exists but it can not be written"
                              % (parentname,))
    elif mode == 'a':
        if os.access(filename, os.F_OK):
            checkFileAccess(filename, 'r+')
        else:
            checkFileAccess(filename, 'w')
    elif mode == 'r+':
        checkFileAccess(filename, 'r')
        if not os.access(filename, os.W_OK):
            raise IOError("file ``%s`` exists but it can not be written"
                          % (filename,))
    else:
        raise ValueError("invalid mode: %r" % (mode,))


# This function really belongs to nriterators.py, but has been moved here
# so as to facilitate its use without having numarray installed
def flattenNames(names):
    """Flatten a names description of a buffer.

    Names of nested fields are returned with its full path, i.e.
    level1/level2/.../levelN.
    """

    for item in names:
        if type(item) == str:
            yield item
        elif ((type(item) == tuple and len(item) == 2) and
              type(item[0]) == str and type(item[1]) == list):
            # Format for a nested name
            for c in flattenNames(item[1]):
                if c == None:
                    yield c
                else:
                    yield '%s/%s' % (item[0], c)
        else:
            raise TypeError, \
                  """elements of the ``names`` list must be strings or 2-tuples"""



if __name__=="__main__":
    import sys
    import getopt

    usage = \
"""usage: %s [-v] format   # '[("f1", [("f1", "u2"),("f2","u4")])]'
  -v means ...\n""" \
    % sys.argv[0]
    try:
        opts, pargs = getopt.getopt(sys.argv[1:], 'v')
    except getopt.GetoptError:
        sys.stderr.write(usage)
        sys.exit(0)
    # if we pass too much parameters, abort
    if len(pargs) <> 1:
        sys.stderr.write(usage)
        sys.exit(0)
    # default options
    verbose = 0
    # Get the options
    for option in opts:
        if option[0] == '-v':
            verbose = 1
    # Catch the format
    try:
        format = eval(pargs[0])
    except:
        format = pargs[0]
    print "format-->", format
    # Create a numpy recarray
    npr = numpy.zeros((3,), dtype=format)
    print "numpy RecArray:", repr(npr)
    # Convert it into a NestedRecArray
    #nra = tonumarray(npr)
    nra = nestedrecords.array(npr)
    print repr(nra)
    # Convert again into numpy
    #nra = nestedrecords.array(npr.data, descr=format, shape=(3,))
    print "nra._formats-->", nra._formats
    print "nra.descr-->", nra.descr
    print "na_descr-->", nra.array_descr
    #npr2 = numpy.array(nra._flatArray, dtype=nra.array_descr)
    npr2 = tonumpy(nra)
    print repr(npr2)


## Local Variables:
## mode: python
## py-indent-offset: 4
## tab-width: 4
## fill-column: 72
## End:
