from ctapipe.utils import get_dataset_path
import numpy as np
import pytest
import os
import shutil
import pandas as pd
from tables import open_file
from lstchain.io.io import (
    dl1_params_lstcam_key,
    dl1_images_lstcam_key,
    dl2_params_lstcam_key,
    dl1_params_src_dep_lstcam_key
    )
from lstchain.io import (
    write_dl2_dataframe,
    get_dataset_keys
)
from lstchain.reco.utils import filter_events
import astropy.units as u

test_dir = 'testfiles'

os.makedirs(test_dir, exist_ok=True)

mc_gamma_testfile = get_dataset_path('gamma_test_large.simtel.gz')
dl1_file = os.path.join(test_dir, 'dl1_gamma_test_large.h5')
dl2_file = os.path.join(test_dir, 'dl2_gamma_test_large.h5')
fake_dl2_proton_file = os.path.join(test_dir, 'dl2_fake_proton.simtel.h5')
fake_dl1_proton_file = os.path.join(test_dir, 'dl1_fake_proton.simtel.h5')
file_model_energy = os.path.join(test_dir, 'reg_energy.sav')
file_model_disp = os.path.join(test_dir, 'reg_disp_vector.sav')
file_model_gh_sep = os.path.join(test_dir, 'cls_gh.sav')

custom_config = {
    "events_filters": {
        "intensity": [0.3, np.inf],
        "width": [0, 10],
        "length": [0, 10],
        "wl": [0, 1],
        "r": [0, 1],
        "leakage_intensity_width_2": [0, 1],
    },
    "tailcut": {
        "picture_thresh":6,
        "boundary_thresh":2,
        "keep_isolated_pixels": True,
        "min_number_picture_neighbors": 1
    },

    "random_forest_regressor_args": {
        "max_depth": 5,
        "min_samples_leaf": 2,
        "n_jobs": 4,
        "n_estimators": 15,
    },
    "random_forest_classifier_args": {
        "max_depth": 5,
        "min_samples_leaf": 2,
        "n_jobs": 4,
        "n_estimators": 10,
    },
    "regression_features": [
        "intensity",
        "width",
        "length",
        "x",
        "y",
        "wl",
        "skewness",
        "kurtosis",
    ],
    "classification_features": [
        "intensity",
        "width",
        "length",
        "x",
        "y",
        "log_reco_energy",
        "reco_disp_dx",
        "reco_disp_dy"
    ],

  "allowed_tels": [1, 2, 3, 4],
  "image_extractor": "GlobalPeakWindowSum",
  "image_extractor_config": {},
  "gain_selector": "ThresholdGainSelector",
  "gain_selector_config": {
    "threshold":  4094
  },
  "mc_nominal_source_x_deg": 0.,
  "mc_nominal_source_y_deg": 0.,
}

def test_import_calib():
    from lstchain import calib

def test_import_reco():
    from lstchain import reco

def test_import_visualization():
    from lstchain import visualization

def test_import_lstio():
    from lstchain import io

@pytest.mark.run(order=1)
def test_r0_to_dl1():
    from lstchain.reco.r0_to_dl1 import r0_to_dl1
    infile = mc_gamma_testfile
    r0_to_dl1(infile, custom_config=custom_config, output_filename=dl1_file)

def test_get_source_dependent_parameters():
    from lstchain.reco.dl1_to_dl2 import get_source_dependent_parameters

    dl1_params = pd.read_hdf(dl1_file, key=dl1_params_lstcam_key)
    src_dep_df = get_source_dependent_parameters(dl1_params, custom_config)

@pytest.mark.run(order=2)
def test_build_models():
    from lstchain.reco.dl1_to_dl2 import build_models
    infile = dl1_file

    reg_energy, reg_disp, cls_gh = build_models(infile, infile, custom_config=custom_config, save_models=False)

    import joblib
    joblib.dump(reg_energy, file_model_energy)
    joblib.dump(reg_disp, file_model_disp)
    joblib.dump(cls_gh, file_model_gh_sep)


@pytest.mark.run(order=3)
def test_apply_models():
    from lstchain.reco.dl1_to_dl2 import apply_models
    import joblib

    dl1 = pd.read_hdf(dl1_file, key=dl1_params_lstcam_key)
    dl1 = filter_events(dl1,
                        filters=custom_config["events_filters"],
                        finite_params=custom_config['regression_features'] + custom_config['classification_features'],
                        )

    reg_energy = joblib.load(file_model_energy)
    reg_disp = joblib.load(file_model_disp)
    reg_cls_gh = joblib.load(file_model_gh_sep)


    dl2 = apply_models(dl1, reg_cls_gh, reg_energy, reg_disp, custom_config=custom_config)

    dl1_keys = get_dataset_keys(dl1_file)
    if dl1_images_lstcam_key in dl1_keys:
        dl1_keys.remove(dl1_images_lstcam_key)
    if dl1_params_lstcam_key in dl1_keys:
        dl1_keys.remove(dl1_params_lstcam_key)

    if dl1_params_src_dep_lstcam_key in dl1_keys:
        dl1_keys.remove(dl1_params_src_dep_lstcam_key)

    with open_file(dl1_file, 'r') as h5in:
        with open_file(dl2_file, 'a') as h5out:

            # Write the selected DL1 info
            for k in dl1_keys:
                if not k.startswith('/'):
                    k = '/' + k

                path, name = k.rsplit('/', 1)
                if path not in h5out:
                    grouppath, groupname = path.rsplit('/', 1)
                    g = h5out.create_group(
                        grouppath, groupname, createparents=True
                        )
                else:
                    g = h5out.get_node(path)

                h5in.copy_node(k, g, overwrite=True)

    write_dl2_dataframe(dl2, dl2_file)
    #dl2.to_hdf(dl2_file, key=dl2_params_lstcam_key)

def produce_fake_dl1_proton_file(dl1_file):
    """
    Produce a fake dl1 proton file by copying the dl2 gamma test file
    and changing mc_type
    """
    events = pd.read_hdf(dl1_file, key=dl1_params_lstcam_key)
    events.mc_type = 101
    events.to_hdf(fake_dl1_proton_file, key=dl1_params_lstcam_key)

def produce_fake_dl2_proton_file(dl1_file, dl2_file):
    """
    Produce a fake dl2 proton file by copying the dl2 gamma test file
    and changing mc_type
    """
    events = pd.read_hdf(dl2_file, key=dl2_params_lstcam_key)
    events.mc_type = 101
    #events.to_hdf(fake_dl2_proton_file, key=dl2_params_lstcam_key)

    dl1_keys = get_dataset_keys(dl1_file)
    if dl1_images_lstcam_key in dl1_keys:
        dl1_keys.remove(dl1_images_lstcam_key)
    if dl1_params_lstcam_key in dl1_keys:
        dl1_keys.remove(dl1_params_lstcam_key)

    if dl1_params_src_dep_lstcam_key in dl1_keys:
        dl1_keys.remove(dl1_params_src_dep_lstcam_key)

    with open_file(dl1_file, 'r') as h5in:
        with open_file(fake_dl2_proton_file, 'a') as h5out:

            # Write the selected DL1 info
            for k in dl1_keys:
                if not k.startswith('/'):
                    k = '/' + k

                path, name = k.rsplit('/', 1)
                if path not in h5out:
                    grouppath, groupname = path.rsplit('/', 1)
                    g = h5out.create_group(
                        grouppath, groupname, createparents=True
                        )
                else:
                    g = h5out.get_node(path)

                h5in.copy_node(k, g, overwrite=True)

    write_dl2_dataframe(events, fake_dl2_proton_file)
    
@pytest.mark.run(after='produce_fake_dl2_proton_file')
def test_sensitivity():
    from lstchain.mc.sensitivity import sensitivity_gamma_efficiency

    produce_fake_dl2_proton_file(dl1_file, dl2_file)
    geff_gammaness = 0.9
    geff_theta2 = 0.8
    eb = 10  # Number of energy bins
    obstime = 50 * 3600 * u.s
    noff = 2

    sensitivity_gamma_efficiency(dl2_file,
                                 fake_dl2_proton_file,
                                 1, 1,
                                 eb,
                                 geff_gammaness,
                                 geff_theta2,
                                 noff,
                                 obstime)
@pytest.mark.last
def test_clean_test_files():
    """
    Function to clean the test files created by the previous test
    """
    import shutil
    shutil.rmtree(test_dir)


def test_disp_vector():
    from lstchain.reco.disp import disp_vector
    dx = np.cos(np.pi/3 * np.ones(3))
    dy = np.sin(np.pi/3 * np.ones(3))
    disp_angle = np.pi/3 * np.ones(3)
    disp_norm = np.ones(3)
    disp_sign = np.ones(3)
    disp_dx, disp_dy = disp_vector(disp_norm, disp_angle, disp_sign)
    np.testing.assert_array_equal([dx, dy], [disp_dx, disp_dy])


def test_disp_to_pos():
    from lstchain.reco.disp import disp_to_pos
    x = np.random.rand(3)
    y = np.random.rand(3)
    cog_x = np.random.rand(3)
    cog_y = np.random.rand(3)
    X, Y = disp_to_pos(x, y, cog_x, cog_y)
    np.testing.assert_array_equal([X, Y], [x+cog_x, y+cog_y])


def test_change_frame_camera_sky():
    from lstchain.reco.utils import sky_to_camera, camera_to_altaz
    import astropy.units as u
    x = np.random.rand(1) * u.m
    y = np.random.rand(1) * u.m
    focal_length = 5 * u.m
    pointing_alt = np.pi/3. * u.rad
    pointing_az = 0. * u.rad

    sky_pos = camera_to_altaz(x, y, focal_length, pointing_alt, pointing_az)
    cam_pos = sky_to_camera(sky_pos.alt, sky_pos.az, focal_length, pointing_alt, pointing_az)
    np.testing.assert_almost_equal([x, y], [cam_pos.x, cam_pos.y], decimal=4)


def test_polar_cartesian():
    from lstchain.reco.utils import polar_to_cartesian, cartesian_to_polar
    X = [-0.5, 0.5]
    Y = [-0.5, 0.5]
    for x in X:
        for y in Y:
            p = cartesian_to_polar(x, y)
            np.testing.assert_almost_equal((x, y), polar_to_cartesian(*p))


def test_version_not_unkown():
    """
    Test that lstchain.__version__ is not unkown
    """
    import lstchain
    assert lstchain.__version__ != 'unknown'
