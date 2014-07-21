"""
Clump finding helper classes



"""

#-----------------------------------------------------------------------------
# Copyright (c) 2013, yt Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------

import copy
import numpy as np

from .clump_info_items import \
     clump_info_registry

from .contour_finder import \
     identify_contours

class Clump(object):
    children = None
    def __init__(self, data, parent, field, cached_fields = None, 
                 function=None, clump_info=None):
        self.parent = parent
        self.data = data
        self.quantities = data.quantities
        self.field = field
        self.min_val = self.data[field].min()
        self.max_val = self.data[field].max()
        self.cached_fields = cached_fields

        # List containing characteristics about clumps that are to be written 
        # out by the write routines.
        if clump_info is None:
            self.set_default_clump_info()
        else:
            # Clump info will act the same if add_info_item is called before or after clump finding.
            self.clump_info = copy.deepcopy(clump_info)

        # Function determining whether a clump is valid and should be kept.
        self.default_function = 'self.data.quantities["IsBound"](truncate=True,include_thermal_energy=True) > 1.0'
        if function is None:
            self.function = self.default_function
        else:
            self.function = function

        # Return value of validity function, saved so it does not have to be calculated again.
        self.function_value = None

    def add_info_item(self, info_item, *args, **kwargs):
        "Adds an entry to clump_info list and tells children to do the same."

        callback = clump_info_registry.find(info_item, *args, **kwargs)
        self.clump_info.append(callback)
        if self.children is None: return
        for child in self.children:
            child.add_info_item(info_item)

    def set_default_clump_info(self):
        "Defines default entries in the clump_info array."

        # add_info_item is recursive so this function does not need to be.
        self.clump_info = []

        self.add_info_item("total_cells")
        self.add_info_item("cell_mass")
        self.add_info_item("mass_weighted_jeans_mass")
        self.add_info_item("volume_weighted_jeans_mass")
        self.add_info_item("max_grid_level")
        self.add_info_item("min_number_density")
        self.add_info_item("max_number_density")

    def clear_clump_info(self):
        "Clears the clump_info array and passes the instruction to its children."

        self.clump_info = []
        if self.children is None: return
        for child in self.children:
            child.clear_clump_info()

    def write_info(self, level, f_ptr):
        "Writes information for clump using the list of items in clump_info."

        for item in self.clump_info:
            value = item(self)
            f_ptr.write("%s%s\n" % ('\t'*level, value))

    def find_children(self, min_val, max_val = None):
        if self.children is not None:
            print "Wiping out existing children clumps.", len(self.children)
        self.children = []
        if max_val is None: max_val = self.max_val
        nj, cids = identify_contours(self.data, self.field, min_val, max_val)
        # Here, cids is the set of slices and values, keyed by the
        # parent_grid_id, that defines the contours.  So we can figure out all
        # the unique values of the contours by examining the list here.
        unique_contours = set([])
        for sl_list in cids.values():
            for sl, ff in sl_list:
                unique_contours.update(np.unique(ff))
        for cid in sorted(unique_contours):
            if cid == -1: continue
            new_clump = self.data.cut_region(
                    ["obj['contours'] == %s" % (cid)],
                    {'contour_slices': cids})
            if new_clump["ones"].size == 0:
                # This is to skip possibly duplicate clumps.  Using "ones" here
                # will speed things up.
                continue
            self.children.append(Clump(new_clump, self, self.field,
                                       self.cached_fields,function=self.function,
                                       clump_info=self.clump_info))

    def pass_down(self,operation):
        "Performs an operation on a clump with an exec and passes the instruction down to clump children."

        # Call if callable, otherwise do an exec.
        if callable(operation):
            operation()
        else:
            exec(operation)

        if self.children is None: return
        for child in self.children:
            child.pass_down(operation)

    def _isValid(self):
        "Perform user specified function to determine if child clumps should be kept."

        # Only call function if it has not been already.
        if self.function_value is None:
            self.function_value = eval(self.function)

        return self.function_value

    def __reduce__(self):
        return (_reconstruct_clump, 
                (self.parent, self.field, self.min_val, self.max_val,
                 self.function_value, self.children, self.data, self.clump_info, self.function))

    def __getitem__(self,request):
        return self.data[request]

def _reconstruct_clump(parent, field, mi, ma, function_value, children, data, clump_info, 
        function=None):
    obj = object.__new__(Clump)
    if iterable(parent):
        try:
            parent = parent[1]
        except KeyError:
            parent = parent
    if children is None: children = []
    obj.parent, obj.field, obj.min_val, obj.max_val, obj.function_value, obj.children, obj.clump_info, obj.function = \
        parent, field, mi, ma, function_value, children, clump_info, function
    # Now we override, because the parent/child relationship seems a bit
    # unreliable in the unpickling
    for child in children: child.parent = obj
    obj.data = data[1] # Strip out the PF
    obj.quantities = obj.data.quantities
    if obj.parent is None: return (data[0], obj)
    return obj

def find_clumps(clump, min_val, max_val, d_clump):
    print "Finding clumps: min: %e, max: %e, step: %f" % (min_val, max_val, d_clump)
    if min_val >= max_val: return
    clump.find_children(min_val)

    if (len(clump.children) == 1):
        find_clumps(clump, min_val*d_clump, max_val, d_clump)

    elif (len(clump.children) > 0):
        these_children = []
        print "Investigating %d children." % len(clump.children)
        for child in clump.children:
            find_clumps(child, min_val*d_clump, max_val, d_clump)
            if ((child.children is not None) and (len(child.children) > 0)):
                these_children.append(child)
            elif (child._isValid()):
                these_children.append(child)
            else:
                print "Eliminating invalid, childless clump with %d cells." % len(child.data["ones"])
        if (len(these_children) > 1):
            print "%d of %d children survived." % (len(these_children),len(clump.children))            
            clump.children = these_children
        elif (len(these_children) == 1):
            print "%d of %d children survived, linking its children to parent." % (len(these_children),len(clump.children))
            clump.children = these_children[0].children
        else:
            print "%d of %d children survived, erasing children." % (len(these_children),len(clump.children))
            clump.children = []

def get_lowest_clumps(clump, clump_list=None):
    "Return a list of all clumps at the bottom of the index."

    if clump_list is None: clump_list = []
    if clump.children is None or len(clump.children) == 0:
        clump_list.append(clump)
    if clump.children is not None and len(clump.children) > 0:
        for child in clump.children:
            get_lowest_clumps(child, clump_list=clump_list)

    return clump_list

def write_clump_index(clump, level, fh):
    top = False
    if not isinstance(fh, file):
        fh = open(fh, "w")
        top = True
    for q in range(level):
        fh.write("\t")
    fh.write("Clump at level %d:\n" % level)
    clump.write_info(level, fh)
    fh.write("\n")
    fh.flush()
    if ((clump.children is not None) and (len(clump.children) > 0)):
        for child in clump.children:
            write_clump_index(child, (level+1), fh)
    if top:
        fh.close()

def write_clumps(clump, level, fh):
    top = False
    if not isinstance(fh, file):
        fh = open(fh, "w")
        top = True
    if ((clump.children is None) or (len(clump.children) == 0)):
        fh.write("%sClump:\n" % ("\t"*level))
        clump.write_info(level, fh)
        fh.write("\n")
        fh.flush()
    if ((clump.children is not None) and (len(clump.children) > 0)):
        for child in clump.children:
            write_clumps(child, 0, fh)
    if top:
        fh.close()
