#!/usr/bin/env python
"""
Produces a csv file mean voxel/vertex time series from a functional file <func>
within a seed mask <seed>.

Usage:
    ciftify_meants [options] <func> <seed>

Arguments:
    <func>          functional data can be (nifti or cifti)
    <seed>          seed mask (nifti, cifti or gifti)

Options:
    --outputcsv PATH     Specify the output filename
    --outputlabels PATH  Specity a file to print the ROI row ids to.
    --mask FILE          brainmask (file format should match seed)
    --roi-label INT      Specify the numeric label of the ROI you want a seedmap for
    --weighted           Compute weighted average timeseries from the seed map
    --hemi HEMI          If the seed is a gifti file, specify the hemisphere (R or L) here
    --debug              Debug logging
    -h, --help           Prints this message

DETAILS:
The default output filename is <func>_<seed>_meants.csv inside the same directory
as the <func> file. This can be changed by specifying the full path after
the '--outputcsv' option. The integer labels for the seeds extracted can be printed
to text using the '--outputlabels' option.

If the seed file contains multiple interger values (i.e. an altas). One row will
be written for each integer value. If you only want a timeseries from one roi in
an atlas, you can specify the integer with the --roi-label option.

A weighted avereage can be calculated from a continuous seed if the --weighted
flag is given.

If a mask is given, the intersection of this mask and the seed mask will be taken.

If a nifti seed if given for a cifti functional file, wb_command -cifti separate will
try extract the subcortical cifti data and try to work with that.

Written by Erin W Dickie, March 17, 2016
"""

import sys
import subprocess
import os
import tempfile
import shutil
import logging
import logging.config

import numpy as np
import scipy as sp
import nibabel as nib
from docopt import docopt

import ciftify

config_path = os.path.join(os.path.dirname(__file__), "logging.conf")
logging.config.fileConfig(config_path, disable_existing_loggers=False)
logger = logging.getLogger(os.path.basename(__file__))

def run_ciftify_meants(tempdir):
    global DRYRUN

    arguments = docopt(__doc__)
    func = arguments['<func>']
    seed = arguments['<seed>']
    mask = arguments['--mask']
    roi_label = arguments['--roi-label']
    outputcsv = arguments['--outputcsv']
    outputlabels = arguments['--outputlabels']
    weighted = arguments['--weighted']
    hemi = arguments['--hemi']
    debug = arguments['--debug']

    if debug:
        logger.setLevel(logging.DEBUG)
        logging.getLogger('ciftify').setLevel(logging.DEBUG)

    logger.debug(arguments)

    func_type, funcbase = ciftify.io.determine_filetype(func)
    logger.debug("func_type is {}".format(func_type))
    seed_type, seedbase = ciftify.io.determine_filetype(seed)
    logger.debug("seed_type is {}".format(seed_type))
    if mask:
        mask_type, maskbase = ciftify.io.determine_filetype(mask)
    else: mask_type = None


    ## determine outbase if it has not been specified
    if not outputcsv:
        outputdir = os.path.dirname(func)
        outputcsv = os.path.join(outputdir,funcbase + '_' + seedbase + '_meants.csv' )

    ## if seed is dlabel - convert to dscalar

    if ".dlabel.nii" in seed:
        longseed=os.path.join(tempdir,'seedmap.dscalar.nii')
        shortseed = os.path.join(tempdir,'seedmapcombined.dscalar.nii')
        ciftify.utils.run(['wb_command', '-cifti-all-labels-to-rois', seed, '1',longseed])
        num_maps = nib.load(longseed).get_data().shape[4]
        ciftify.utils.run(['wb_command', '-cifti-math "((x*1)+(y*2))"', shortseed,
              '-var','x',longseed, '-select','1',str(1),
              '-var','y',longseed, '-select','1',str(2)])
        for roi in range(3,num_maps+1):
            ciftify.utils.run(['wb_command', '-cifti-math "((x)+(y*{}))"'.format(roi), shortseed,
                  '-var','x',shortseed,
                  '-var','y',longseed, '-select','1',str(roi)])
        seed = shortseed

    if seed_type == "cifti":
        seed_info = ciftify.io.cifti_info(seed)
        func_info = ciftify.io.cifti_info(func)
        if not all((seed_info['maps_to_volume'], func_info['maps_to_volume'])):
            seed_data = ciftify.io.load_concat_cifti_surfaces(seed)
            if func_type == "cifti":
                data = ciftify.io.load_concat_cifti_surfaces(func)
            else:
                sys.exit('If <seed> is in cifti, func file needs to match.')
            if mask:
                if mask_type == "cifti":
                    mask_data = ciftify.io.load_concat_cifti_surfaces(mask)
                else:
                    sys.exit('If <seed> is in cifti, func file needs to match.')
        else:
            seed_data = ciftify.io.load_cifti(seed)
            if func_type == "cifti":
                data = ciftify.io.load_cifti(func)
            else:
                sys.exit('If <seed> is in cifti, func file needs to match.')
            if mask:
                if mask_type == "cifti":
                     mask_data = ciftify.io.load_cifti(mask)
                else:
                  sys.exit('If <seed> is in cifti, mask file needs to match.')

    elif seed_type == "gifti":
        seed_data = ciftify.io.load_gii_data(seed)
        if func_type == "gifti":
            data = ciftify.io.load_gii_data(func)
            if mask:
                if mask_type == "gifti":
                    mask_data = ciftify.io.load_gii_data(mask)
                else:
                    sys.exit('If <seed> is in gifti, mask file needs to match.')
        elif func_type == "cifti":
            if hemi == 'L':
                data = ciftify.io.load_hemisphere_data(func, 'CORTEX_LEFT')
            elif hemi == 'R':
                data = ciftify.io.load_hemisphere_data(func, 'CORTEX_RIGHT')
            else:
             sys.exit('ERROR: hemisphere for the gifti seed file needs to be specified with "L" or "R"')
            ## also need to apply this change to the mask if it matters
            if mask_type == "cifti":
                 if hemi == 'L':
                     mask_data = ciftify.io.load_hemisphere_data(mask, 'CORTEX_LEFT')
                 elif hemi == 'R':
                     mask_data = ciftify.io.load_hemisphere_data(mask, 'CORTEX_RIGHT')
        else:
            sys.exit('If <seed> is in gifti, <func> must be gifti or cifti')


    elif seed_type == "nifti":
        seed_data, _, _, _ = ciftify.io.load_nifti(seed)
        if func_type == "nifti":
            data, _, _, _ = ciftify.io.load_nifti(func)
        elif func_type == 'cifti':
            subcort_func = os.path.join(tempdir, 'subcort_func.nii.gz')
            ciftify.utils.run(['wb_command',
              '-cifti-separate', func, 'COLUMN',
              '-volume-all', subcort_func])
            data, _, _, _ = ciftify.io.load_nifti(subcort_func)
        else:
            sys.exit('If <seed> is in nifti, func file needs to match.')
        if mask:
            if mask_type == "nifti":
                mask_data, _, _, _ = ciftify.io.load_nifti(mask)
            elif mask_type == 'cifti':
                subcort_mask = os.path.join(tempdir, 'subcort_mask.nii.gz')
                ciftify.utils.run(['wb_command',
                  '-cifti-separate', mask, 'COLUMN',
                  '-volume-all', subcort_mask])
                mask_data, _, _, _ = ciftify.io.load_nifti(subcort_mask)
            else:
                sys.exit('If <seed> is in nifti, <mask> file needs to match.')


    ## check that dim 0 of both seed and func
    if data.shape[0] != seed_data.shape[0]:
        sys.exit('ERROR: at the func and seed images have difference number of voxels')

    if seed_data.shape[1] != 1:
        logger.WARNING("your seed volume has more than one timepoint")

    ## even if no mask given, mask out all zero elements..
    std_array = np.std(data, axis=1)
    m_array = np.mean(data, axis=1)
    std_nonzero = np.where(std_array > 0)[0]
    m_nonzero = np.where(m_array != 0)[0]
    mask_indices = np.intersect1d(std_nonzero, m_nonzero)

    if mask:
        # attempt to mask out non-brain regions in ROIs
        n_seeds = len(np.unique(seed_data))
        if seed_data.shape[0] != mask_data.shape[0]:
            sys.exit('ERROR: at the mask and seed images have difference number of voxels')
        mask_idx = np.where(mask_data > 0)[0]
        mask_indices = np.intersect1d(mask_indices, mask_idx)
        if len(np.unique(np.multiply(seed_data,mask_data))) != n_seeds:
            sys.exit('ERROR: At least 1 ROI completely outside mask for {}.'.format(outputcsv))

    if weighted:
        out_data = np.average(data[mask_indices,:], axis=0,
                              weights=np.ravel(seed_data[mask_indices]))
    else:
        # init output vector
        if roi_label:
            if float(roi_label) not in np.unique(seed_data)[1:]:
               sys.exit('ROI {}, not in seed map labels: {}'.format(roi_label, np.unique(seed)[1:]))
            else:
               rois = [float(roi_label)]
        else:
            rois = np.unique(seed_data)[1:]
        out_data = np.zeros((len(rois), data.shape[1]))

        # get mean seed dataistic from each, append to output
        for i, roi in enumerate(rois):
            idx = np.where(seed_data == roi)[0]
            idxx = np.intersect1d(mask_indices, idx)
            out_data[i,:] = np.mean(data[idxx, :], axis=0)

    # write out csv
    np.savetxt(outputcsv, out_data, delimiter=",")

    if outputlabels: np.savetxt(outputlabels, rois, delimiter=",")

def main():
    with ciftify.utils.TempDir() as tmpdir:
        logger.info('Creating tempdir:{} on host:{}'.format(tmpdir,
                    os.uname()[1]))
        ret = run_ciftify_meants(tmpdir)
    sys.exit(ret)

if __name__ == '__main__':
    main()