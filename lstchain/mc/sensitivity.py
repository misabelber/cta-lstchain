import numpy as np
import pandas as pd
import astropy.units as u
from .plot_utils import sensitivity_minimization_plot, plot_positions_survived_events
from .mc import rate, weight
from lstchain.spectra.crab import crab_hegra 
from lstchain.spectra.proton import proton_bess
from gammapy.stats import WStatCountsStatistic
from lstchain.reco.utils import reco_source_position_sky
from astropy.coordinates.angle_utilities import angular_separation
from lstchain.io import read_simu_info_merged_hdf5
from lstchain.io.io import dl2_params_lstcam_key

from ctapipe.instrument import OpticsDescription

__all__ = [
    'read_sim_par',
    'process_mc',
    'calculate_sensitivity',
    'calculate_sensitivity_lima',
    'calculate_sensitivity_lima_ebin',
    'bin_definition',
    'ring_containment',
    'sensitivity_fraction_of_gammas',
    'sensitivity',
    ]


def read_sim_par(file):
    """
    Read MC simulated parameters

    Parameters
    ---------
    file: `hdf5 file` 

    Returns
    ---------
    par: `dict` with simulated parameters

    """
    simu_info = read_simu_info_merged_hdf5(file)
    emin = simu_info.energy_range_min
    emax = simu_info.energy_range_max
    sp_idx = simu_info.spectral_index
    sim_ev = simu_info.num_showers * simu_info.shower_reuse
    area_sim = (simu_info.max_scatter_range - simu_info.min_scatter_range) ** 2 * np.pi
    cone = simu_info.max_viewcone_radius

    par_var = [emin, emax, sp_idx, sim_ev, area_sim, cone]
    par_dic = ['emin', 'emax', 'sp_idx', 'sim_ev', 'area_sim', 'cone']
    par = dict(zip(par_dic, par_var))

    return par


def process_mc(dl2_file, events, mc_type):
    """
    Process the MC simulated and reconstructed to extract the relevant
    parameters to compute the sensitivity

    Paramenters
    ---------
    dl2_file:  dl2 file with mc parameters
    events: `pandas DataFrame' dl2 events
    mc_type: 'string' type of particle
    
    Returns
    ---------
    gammaness: `numpy.ndarray`
    angdist2:  `numpy.ndarray` angular distance squared
    e_reco:    `numpy.ndarray` reconstructed energies
    n_reco:    `int` number of reconstructed events
    mc_par:    `dict` with simulated parameters

    """
    sim_par = read_sim_par(dl2_file)
    
    #events = pd.read_hdf(dl2_file, key = dl2_params_lstcam_key)

    # Filters:
    # TO DO: These cuts must be given in a configuration file
    # By now: only cut in leakage and intensity
    # we use all telescopes (number of events needs to be multiplied 
    # by the number of LSTs in the simulation)

    filter_good_events = (
        (events.leakage_intensity_width_2 < 0.2)
        & (events.intensity > 200)
    )
    events = events[filter_good_events]

    e_reco = events.reco_energy.to_numpy() * u.TeV
    e_true = events.mc_energy.to_numpy() * u.TeV

    gammaness = events.gammaness
    
    focal_length = OpticsDescription.from_name("LST").equivalent_focal_length

    # If the particle is a gamma ray, it returns the squared angular distance
    # from the reconstructed gamma-ray position and the simulated incoming position
    if mc_type == 'gamma':
        events = events[events.mc_type == 0]
        alt2 = events.mc_alt
        az2 = events.mc_az

    # If the particle is not a gamma-ray (diffuse protons/electrons), it returns
    # the squared angular distance of the reconstructed position w.r.t. the
    # center of the camera
    else:
        events = events[events.mc_type != 0]
        alt2 = events.mc_alt_tel
        az2 = events.mc_az_tel

    alt1=events.reco_alt
    az1=events.reco_az
    
    angdist2 = (angular_separation(az1, alt1, az2, alt2).to_numpy() * u.rad) ** 2
    events['theta2'] = angdist2.to(u.deg**2)

    return gammaness, angdist2.to(u.deg**2), e_reco, e_true, sim_par, events

def diff_events_after_cut(events, rates, obstime, feature, cut, percent_of_gammas):
    total_events=np.sum(rates) * obstime
    
    if feature=="gammaness":
        events_after_cut=np.sum(rates[events[feature]>cut]) * obstime
    else:
        events_after_cut=np.sum(rates[events[feature]<cut]) * obstime
        
    return events_after_cut-percent_of_gammas*total_events

def samesign(a,b):
    return a * b > 0

def find_cut(events, rates, obstime, feature, low_cut, high_cut, percent_of_gammas):

    for i in range(54):
        midpoint = (low_cut + high_cut) / 2.0
        if samesign(diff_events_after_cut(events, rates, obstime, feature, low_cut, percent_of_gammas),
                    diff_events_after_cut(events, rates, obstime, feature, midpoint, percent_of_gammas)):
            low_cut = midpoint
        else:
            high_cut = midpoint

    return midpoint
    

def calculate_sensitivity(n_excesses, n_background, alpha):
    """
    Sensitivity calculation using n_excesses/sqrt(n_background)

    Parameters
    ---------
    n_excesses:   `numpy.ndarray` number of excess events in the signal region
    n_background:   `numpy.ndarray` number of events in the background region
    alpha: `numpy.ndarray` inverse of the number of off positions

    Returns
    ---------
    sensitivity: `numpy.ndarray` in percentage of Crab units
    """
    significance = n_excesses / np.sqrt(n_background * alpha)
    sensitivity = 5 / significance * 100  # percentage of Crab

    return sensitivity

def calculate_sensitivity_lima(n_on_events, n_background, alpha):
    """
    Sensitivity calculation using the Li & Ma formula
    eq. 17 of Li & Ma (1983).
    https://ui.adsabs.harvard.edu/abs/1983ApJ...272..317L/abstract

    We calculate the sensitivity in bins of energy and
    theta2

    Parameters
    ---------
    n_on_events:   `numpy.ndarray` number of ON events in the signal region
    n_background:   `numpy.ndarray` number of events in the background region
    alpha: `float` inverse of the number of off positions
    n_bins_energy: `int` number of bins in energy
    n_bins_theta2: `int` number of bins in theta2

    Returns
    ---------
    sensitivity: `numpy.ndarray` sensitivity in percentage of Crab units
    n_excesses_5sigma: `numpy.ndarray` number of excesses corresponding to 
                a 5 sigma significance

    """

    
    stat = WStatCountsStatistic(
        n_on=n_on_events,  
        n_off=n_background,
        alpha=alpha
        )


    n_excesses_5sigma = stat.excess_matching_significance(5)
    for value_excesses, value_bkg, value_on in np.nditer([n_excesses_5sigma, n_background, n_on_events], op_flags=['readwrite']):
        if value_excesses < 10:
            value_excesses[...] = 10
        if value_excesses < 0.05 * value_bkg/5:
            value_excesses[...]=0.05 * value_bkg/5
        print(value_excesses, value_on, value_bkg)
    sensitivity = n_excesses_5sigma / n_on_events * 100  # percentage of Crab
    
    return n_excesses_5sigma, sensitivity


def calculate_sensitivity_lima_ebin(n_on_events, n_background, alpha, n_bins_energy):
    """
    Sensitivity calculation using the Li & Ma formula
    eq. 17 of Li & Ma (1983).
    https://ui.adsabs.harvard.edu/abs/1983ApJ...272..317L/abstract

    Parameters
    ---------
    n_on_events:   `numpy.ndarray` number of ON events in the signal region
    n_background: `numpy.ndarray` number of events in the background region
    alpha:        `float` inverse of the number of off positions
    n_bins_energy:`int` number of bins in energy

    Returns
    ---------
    sensitivity: `numpy.ndarray` sensitivity in percentage of Crab units
    n_excesses_5sigma: `numpy.ndarray` number of excesses corresponding to 
                a 5 sigma significance

    """
    #if any(len(a) != n_bins_energy for a in (n_on_events, n_background, alpha)):
    #    raise ValueError(
     #       'Excess, background and alpha arrays must have the same length')

    stat = WStatCountsStatistic(
        n_on=n_on_events,
        n_off=n_background,
        alpha=alpha 
        )
    
    n_excesses_5sigma = stat.excess_matching_significance(5)

    for i in range(0, n_bins_energy):
        # If the excess needed to get 5 sigma is less than 10,
        # we force it to be at least 10
        if n_excesses_5sigma[i] < 10:
            n_excesses_5sigma[i] = 10
        # If the excess needed to get 5 sigma is less than 5%
        # of the background, we force it to be at least 5% of
        # the background
        if n_excesses_5sigma[i] < 0.05 * n_background[i] * alpha[i]:
            n_excesses_5sigma[i] = 0.05 * n_background[i] * alpha[i]

    sensitivity = n_excesses_5sigma / n_on_events * 100  # percentage of Crab

    return n_excesses_5sigma, sensitivity

def bin_definition(n_bins_gammaness, n_bins_theta2):
    """
    Define binning in gammaness and theta2 for the
    optimization of the sensitivity

    Parameters
    ---------
    n_bins_gammaness:   `int` number of bins in gammaness
    n_bins_theta2:   `int` number of bins in theta2

    Returns
    ---------
    gammaness_bins, theta2_bins: `numpy.ndarray` binning of gammaness and theta2

    """
    max_gam = 0.9
    max_th2 = 0.02 * u.deg * u.deg
    min_th2 = 0.001 * u.deg * u.deg

    gammaness_bins = np.linspace(0, max_gam, n_bins_gammaness)
    theta2_bins = np.linspace(min_th2, max_th2, n_bins_theta2)

    return gammaness_bins, theta2_bins


def ring_containment(angdist2, ring_radius, ring_halfwidth):
    """
    Calculate containment of cosmic ray particles with reconstructed positions
    within a ring of radius=ring_radius and half width=ring_halfwidth
    Parameters
    ---------
    angdist2:       `numpy.ndarray` angular distance squared w.r.t.
                    the center of the camera
    ring_radius:    `float` ring radius
    ring_halfwidth: `float` halfwidth of the ring

    Returns
    ---------
    contained: `numpy.ndarray` bool array
    area: angular area of the ring

    """
    ring_lower_limit = ring_radius - ring_halfwidth
    ring_upper_limit = np.sqrt(2 * (ring_radius ** 2) - (ring_lower_limit) ** 2)

    area = np.pi * (ring_upper_limit ** 2 - ring_lower_limit ** 2)
    # For the two halfwidths to cover the same area, compute the area of
    # the internal and external rings:
    # A_internal = pi * ((ring_radius**2) - (ring_lower_limit)**2)
    # A_external = pi * ((ring_upper_limit**2) - (ring_radius)**2)
    # The areas should be equal, so we can extract the ring_upper_limit
    # ring_upper_limit = math.sqrt(2 * (ring_radius**2) - (ring_lower_limit)**2)

    contained = np.where((np.sqrt(angdist2) < ring_upper_limit) & (np.sqrt(angdist2) > ring_lower_limit), True, False)

    return contained, area

def sensitivity_find_best_cuts(dl2_file_g, dl2_file_p,
                               events_g, events_p,
                               ntelescopes_gammas, ntelescopes_protons,
                               n_bins_energy,
                               fraction_of_gammas_gammaness,
                               fraction_of_gammas_theta2,
                               noff,
                               obstime = 50 * 3600 * u.s
                               ):

    """
    Main function to find the best cuts to calculate the sensitivity
    based on a given a MC data subset

    Parameters
    ---------
    dl2_file_g: `string` path to h5 file of reconstructed gammas
    dl2_file_p: `string' path to h5 file of reconstructed protons
    ntelescopes_gammas: `int` number of telescopes used
    ntelescopes_protons: `int` number of telescopes used
    n_bins_energy: `int` number of bins in energy
    fraction_of_gammas_gammaness: `float` between 0 and 1 %/100 
    of gammas to be left after cut in gammaness    
    fraction_of_gammas_theta2: `float` between 0 and 1 %/100 
    of gammas to be left after cut in theta2    
    noff: `float` ratio between the background and the signal region
    obstime: `Quantity` Observation time in seconds

    Returns
    ---------
    energy: `array` center of energy bins
    sensitivity: `array` sensitivity per energy bin

    """

    # Read simulated and reconstructed values

    gammaness_g, theta2_g, e_reco_g, e_true_g, mc_par_g, events_g = process_mc(dl2_file_g, events_g,  'gamma')
    gammaness_p, angdist2_p, e_reco_p, e_true_p, mc_par_p, events_p = process_mc(dl2_file_p, events_p, 'proton')

    mc_par_g['sim_ev'] = mc_par_g['sim_ev'] * ntelescopes_gammas * (1-fraction_of_events_for_cuts)
    mc_par_p['sim_ev'] = mc_par_p['sim_ev'] * ntelescopes_protons * (1-fraction_of_events_for_cuts)

    # Pass units to TeV and cm2
    mc_par_g['emin'] = mc_par_g['emin'].to(u.TeV)
    mc_par_g['emax'] = mc_par_g['emax'].to(u.TeV)

    mc_par_p['emin'] = mc_par_p['emin'].to(u.TeV)
    mc_par_p['emax'] = mc_par_p['emax'].to(u.TeV)

    mc_par_g['area_sim'] = mc_par_g['area_sim'].to(u.cm ** 2)
    mc_par_p['area_sim'] = mc_par_p['area_sim'].to(u.cm ** 2)

    # Set binning for sensitivity calculation
    emin_sensitivity =  mc_par_p['emin']
    emax_sensitivity =  mc_par_p['emax']

    #Energy bins
    e_bins = np.logspace(np.log10(emin_sensitivity.to_value()),
                         np.log10(emax_sensitivity.to_value()), n_bins_energy + 1)
    energy = e_bins * u.TeV
    
    # Extract spectral parameters
    dFdE, crab_par = crab_hegra(energy)
    dFdEd0, proton_par = proton_bess(energy)

    
                       
    y0 = mc_par_g['sim_ev'] / (mc_par_g['emax'].to_value()**(mc_par_g['sp_idx'] + 1) \
                               - mc_par_g['emin'].to_value()**(mc_par_g['sp_idx'] + 1)) \
        * (mc_par_g['sp_idx'] + 1)
    y = y0 * (e_bins[1:]**(crab_par['alpha'] + 1) - e_bins[:-1]**(crab_par['alpha'] + 1)) / (crab_par['alpha'] + 1)

    n_sim_bin = y

    # Rates and weights
    rate_g = rate("PowerLaw", mc_par_g['emin'], mc_par_g['emax'], crab_par, mc_par_g['cone'], mc_par_g['area_sim'])

    rate_p = rate("PowerLaw", mc_par_p['emin'], mc_par_p['emax'], proton_par, mc_par_p['cone'], mc_par_p['area_sim'])

    w_g = weight("PowerLaw", mc_par_g['emin'], mc_par_g['emax'], mc_par_g['sp_idx'], rate_g,
                 mc_par_g['sim_ev'], crab_par)

    w_p = weight("PowerLaw", mc_par_p['emin'], mc_par_p['emax'], mc_par_p['sp_idx'], rate_p,
                 mc_par_p['sim_ev'], proton_par)

    if (w_g.unit ==  u.Unit("sr / s")):
        print("You are using diffuse gammas to estimate point-like sensitivity")
        print("These results will make no sense")
        w_g = w_g / u.sr  # Fix to make tests pass

    rate_weighted_g = ((e_true_g / crab_par['e0']) ** (crab_par['alpha'] - mc_par_g['sp_idx'])) \
                      * w_g
    rate_weighted_p = ((e_true_p / proton_par['e0']) ** (proton_par['alpha'] - mc_par_p['sp_idx'])) \
                      * w_p
                      
    p_contained, ang_area_p = ring_containment(angdist2_p, 0.4 * u.deg, 0.3 * u.deg)

    # FIX: ring_radius and ring_halfwidth should have units of deg
    # FIX: hardcoded at the moment, but ring_radius should be read from
    # the gamma file (point-like) or given as input (diffuse).
    # FIX: ring_halfwidth should be given as input
    

    # Arrays to contain the number of gammas and protons for different cuts
    
    final_gammas = np.ndarray(shape=(n_bins_energy))
    final_protons = np.ndarray(shape=(n_bins_energy))
    pre_gammas = np.ndarray(shape=(n_bins_energy))
    pre_protons = np.ndarray(shape=(n_bins_energy))
    
    ngamma_per_ebin = np.ndarray(n_bins_energy)
    nproton_per_ebin = np.ndarray(n_bins_energy)

    total_rate_proton = np.sum(rate_weighted_p)
    total_rate_gamma = np.sum(rate_weighted_g)
    print("Total rate triggered proton {:.3f} Hz".format(total_rate_proton))
    print("Total rate triggered gamma  {:.3f} Hz".format(total_rate_gamma))

    # Quantities to show in the results
    sensitivity = np.ndarray(shape = n_bins_energy)
    n_excesses_min = np.ndarray(shape = n_bins_energy)
    eff_g = np.ndarray(shape = n_bins_energy)
    eff_p = np.ndarray(shape = n_bins_energy)
    gcut = np.ndarray(shape = n_bins_energy)
    tcut = np.ndarray(shape = n_bins_energy)
    ngammas = np.ndarray(shape = n_bins_energy)
    nprotons = np.ndarray(shape = n_bins_energy)
    gammarate = np.ndarray(shape = n_bins_energy)
    protonrate = np.ndarray(shape = n_bins_energy)
    eff_area = np.ndarray(shape = n_bins_energy)
    nevents_gamma = np.ndarray(shape = n_bins_energy)
    nevents_proton = np.ndarray(shape = n_bins_energy)

    #Dataframe to store the events which survive the cuts
    dl2 = pd.DataFrame(columns=events_g.keys()) 

    # Weight events and count number of events per bin:
    for i in range(0, n_bins_energy):  # binning in energy
        total_rate_proton_ebin = np.sum(rate_weighted_p[(e_reco_p < energy[i + 1]) & (e_reco_p > energy[i])])

        print("\n******** Energy bin: {:.3f} - {:.3f} TeV ********".format(energy[i].value, energy[i + 1].value))
        total_rate_proton_ebin = np.sum(rate_weighted_p[(e_reco_p < energy[i+1]) & (e_reco_p > energy[i])])
        total_rate_gamma_ebin = np.sum(rate_weighted_g[(e_reco_g < energy[i+1]) & (e_reco_g > energy[i])])

        #print("**************")
        print("Total rate triggered proton in this bin {:.5f} Hz".format(total_rate_proton_ebin.value))
        print("Total rate triggered gamma in this bin {:.5f} Hz".format(total_rate_gamma_ebin.value))
        
        events_bin_g = events_g[(e_reco_g < energy[i+1]) & (e_reco_g > energy[i])]
        events_bin_p = events_p[(e_reco_p < energy[i+1]) & (e_reco_p > energy[i])]
        
        rate_g_ebin = np.sum(rate_weighted_g[(e_reco_g < energy[i+1]) & (e_reco_g > energy[i])])

        rates_g = rate_weighted_g[(e_reco_g < energy[i+1]) & (e_reco_g > energy[i])]
                                     
        events_bin_g = events_g[(e_reco_g < energy[i+1]) & (e_reco_g > energy[i])]
        events_bin_p = events_p[(e_reco_p < energy[i+1]) & (e_reco_p > energy[i])]

        best_g_cut = find_cut(events_bin_g, rates_g, obstime,  "gammaness", 0, 0.9, fraction_of_gammas_gammaness)
        best_theta2_cut = find_cut(events_bin_g, rates_g, obstime, "theta2", 0.0, 10.0, fraction_of_gammas_theta2) * u.deg**2
            
        print(best_g_cut, best_theta2_cut)
        
        
        events_bin_after_cuts_g = events_bin_g[(events_bin_g.gammaness > best_g_cut) &(events_bin_g.theta2 < best_theta2_cut)]
        events_bin_after_cuts_p = events_bin_p[(events_bin_p.gammaness > best_g_cut) &(events_bin_p.theta2 < best_theta2_cut)]

        
        
        dl2 = pd.concat((dl2, events_bin_after_cuts_g))
        dl2 = pd.concat((dl2, events_bin_after_cuts_p))

        
        # ratio between the area where we search for protons ang_area_p
        # and the area where we search for gammas math.pi * t
        area_ratio_p = np.pi * best_theta2_cut / ang_area_p
        
        rate_g_ebin = np.sum(rate_weighted_g[(e_reco_g < energy[i+1]) & (e_reco_g > energy[i]) \
                                             & (gammaness_g > best_g_cut) & (theta2_g < best_theta2_cut)])

        rate_p_ebin = np.sum(rate_weighted_p[(e_reco_p < energy[i+1]) & (e_reco_p > energy[i]) \
                                             & (gammaness_p > best_g_cut) & p_contained])
        final_gammas[i] = rate_g_ebin * obstime
        final_protons[i] = rate_p_ebin * obstime * area_ratio_p

        pre_gammas[i] = e_reco_g[(e_reco_g < energy[i+1]) & (e_reco_g > energy[i]) \
                                   & (gammaness_g > best_g_cut) & (theta2_g < best_theta2_cut)].shape[0]
        pre_protons[i] = e_reco_p[(e_reco_p < energy[i+1]) & (e_reco_p > energy[i]) \
                                     & (gammaness_p > best_g_cut) & p_contained].shape[0]
        ngamma_per_ebin[i] = np.sum(rate_weighted_g[(e_reco_g < energy[i+1]) & (e_reco_g > energy[i])]) * obstime
        nproton_per_ebin[i] = np.sum(rate_weighted_p[(e_reco_p < energy[i+1]) & (e_reco_p > energy[i])]) * obstime

        gcut[i] = best_g_cut
        tcut[i] = best_theta2_cut.to_value()
        ngammas[i] = final_gammas[i]
        nprotons[i] = final_protons[i]
        gammarate[i] = final_gammas[i] / (obstime.to(u.min)).to_value()
        protonrate[i] = final_protons[i] / (obstime.to(u.min)).to_value()
        
        eff_g[i] = final_gammas[i] / ngamma_per_ebin[i]
        eff_p[i] = final_protons[i] / nproton_per_ebin[i]

        e_aftercuts = e_true_g[(e_reco_g < energy[i + 1]) & (e_reco_g > energy[i]) \
                               & (gammaness_g > gcut[i]) & (theta2_g < best_theta2_cut)]


        e_aftercuts_p = e_true_p[(e_reco_p < energy[i + 1]) & (e_reco_p > energy[i]) \
                                 & p_contained]
        e_aftercuts_w = np.sum(np.power(e_aftercuts, crab_par['alpha'] - mc_par_g['sp_idx']))

        eff_area[i] = e_aftercuts_w.to_value() / n_sim_bin[i] * mc_par_g['area_sim'].to(u.m**2).to_value()

        nevents_gamma[i] = e_aftercuts.shape[0]
        nevents_proton[i] = e_aftercuts_p.shape[0]

        
    print(e_reco_p.shape, e_reco_p[p_contained].shape[0])
    n_excesses_min, sensitivity = calculate_sensitivity_lima(final_gammas, final_protons*noff, 1/noff * np.ones_like(final_gammas))

        
    # Avoid bins which are empty or have too few events:
    min_num_events = 10
    min_pre_events = 10

    # Set conditions for calculating sensitivity
    for sens_value, \
        final_protons_value, \
        pre_gamma_value, \
        pre_protons_value, \
        final_gammas_value in np.nditer([sensitivity, \
                                         final_protons, nevents_gamma, \
                                         nevents_proton, final_gammas], op_flags=['readwrite']):
        
        conditions = (not np.isfinite(sens_value)) or (sens_value<=0) \
                     or (final_gammas_value < min_num_events) \
                     or (pre_gamma_value < min_pre_events) \
                     or (pre_protons_value < min_pre_events)
        if conditions:
            sens_value[...] = np.inf
    
        #print(final_protons_value, final_gammas_value, pre_gamma_value, pre_protons_value)
    # Compute sensitivity in flux units
    egeom = np.sqrt(energy[1:] * energy[:-1])
    dFdE, par = crab_hegra(egeom)
    sensitivity_flux = sensitivity / 100 * (dFdE * egeom * egeom).to(u.erg / (u.cm**2 * u.s))

    print("\n******** Energy [TeV] *********\n")
    print(egeom)
    print("\nsensitivity flux:\n", sensitivity_flux)
    print("\nsensitivity[%]:\n", sensitivity)
    print("\n**************\n")
    
    list_of_tuples = list(zip(energy[:energy.shape[0]-1].to_value(), energy[1:].to_value(), gcut, tcut,
                            ngammas, nprotons,
                            gammarate, protonrate,
                            n_excesses_min, sensitivity_flux.to_value(), eff_area,
                              eff_g, eff_p, nevents_gamma, nevents_proton))
    result = pd.DataFrame(list_of_tuples,
                           columns=['ebin_low', 'ebin_up', 'gammaness_cut', 'theta2_cut',
                                    'n_gammas', 'n_protons',
                                    'gamma_rate', 'proton_rate',
                                    'n_excesses_min', 'sensitivity','eff_area',
                                    'eff_gamma', 'eff_proton',
                                    'nevents_g', 'nevents_p'])

    units = [energy.unit, energy.unit,"", best_theta2_cut.unit,"", "",
             u.min**-1, u.min**-1, "",
             sensitivity_flux.unit, mc_par_g['area_sim'].to(u.cm**2).unit, "", "", "", ""]
    
    return energy, sensitivity, result, units, dl2, gcut, tcut



def sensitivity_fraction_of_gammas(dl2_file_g, dl2_file_p,
                               events_g, events_p,
                               ntelescopes_gammas, ntelescopes_protons,
                               n_bins_energy,
                               fraction_of_gammas_gammaness,
                               fraction_of_gammas_theta2,
                               noff,
                               obstime = 50 * 3600 * u.s
                               ):

    """
    Main function to calculate the sensitivity for cuts based
    on gamma efficiency

    Parameters
    ---------
    dl2_file_g: `string` path to h5 file of reconstructed gammas
    dl2_file_p: `string' path to h5 file of reconstructed protons
    ntelescopes_gammas: `int` number of telescopes used
    ntelescopes_protons: `int` number of telescopes used
    n_bins_energy: `int` number of bins in energy
    fraction_of_gammas_gammaness: `float` between 0 and 1 %/100 
    of gammas to be left after cut in gammaness    
    fraction_of_gammas_theta2: `float` between 0 and 1 %/100 
    of gammas to be left after cut in theta2    
    noff: `float` ratio between the background and the signal region
    obstime: `Quantity` Observation time in seconds

    Returns
    ---------
    energy: `array` center of energy bins
    sensitivity: `array` sensitivity per energy bin

    """

    # Read simulated and reconstructed values

    gammaness_g, theta2_g, e_reco_g, e_true_g, mc_par_g, events_g = process_mc(dl2_file_g, events_g,  'gamma')
    gammaness_p, angdist2_p, e_reco_p, e_true_p, mc_par_p, events_p = process_mc(dl2_file_p, events_p, 'proton')

    mc_par_g['sim_ev'] = mc_par_g['sim_ev'] * ntelescopes_gammas
    mc_par_p['sim_ev'] = mc_par_p['sim_ev'] * ntelescopes_protons

    # Pass units to TeV and cm2
    mc_par_g['emin'] = mc_par_g['emin'].to(u.TeV)
    mc_par_g['emax'] = mc_par_g['emax'].to(u.TeV)

    mc_par_p['emin'] = mc_par_p['emin'].to(u.TeV)
    mc_par_p['emax'] = mc_par_p['emax'].to(u.TeV)

    mc_par_g['area_sim'] = mc_par_g['area_sim'].to(u.cm ** 2)
    mc_par_p['area_sim'] = mc_par_p['area_sim'].to(u.cm ** 2)

    # Set binning for sensitivity calculation
    emin_sensitivity =  mc_par_p['emin']
    emax_sensitivity =  mc_par_p['emax']

    #Energy bins
    e_bins = np.logspace(np.log10(emin_sensitivity.to_value()),
                         np.log10(emax_sensitivity.to_value()), n_bins_energy + 1)
    energy = e_bins * u.TeV
    
    # Extract spectral parameters
    dFdE, crab_par = crab_hegra(energy)
    dFdEd0, proton_par = proton_bess(energy)

                           
    y0 = mc_par_g['sim_ev'] / (mc_par_g['emax'].to_value()**(mc_par_g['sp_idx'] + 1) \
                               - mc_par_g['emin'].to_value()**(mc_par_g['sp_idx'] + 1)) \
                               * (mc_par_g['sp_idx'] + 1)
    
    y = y0 * (e_bins[1:]**(crab_par['alpha'] + 1) - \
              e_bins[:-1]**(crab_par['alpha'] + 1)) / (crab_par['alpha'] + 1)

    n_sim_bin = y

    # Rates and weights
    rate_g = rate("PowerLaw",
                  mc_par_g['emin'], mc_par_g['emax'],
                  crab_par, mc_par_g['cone'], mc_par_g['area_sim'])

    rate_p = rate("PowerLaw",
                  mc_par_p['emin'], mc_par_p['emax'],
                  proton_par, mc_par_p['cone'], mc_par_p['area_sim'])

    w_g = weight("PowerLaw",
                 mc_par_g['emin'], mc_par_g['emax'],
                 mc_par_g['sp_idx'], rate_g,
                 mc_par_g['sim_ev'], crab_par)

    w_p = weight("PowerLaw",
                 mc_par_p['emin'], mc_par_p['emax'],
                 mc_par_p['sp_idx'], rate_p,
                 mc_par_p['sim_ev'], proton_par)

    if (w_g.unit ==  u.Unit("sr / s")):
        print("You are using diffuse gammas to estimate point-like sensitivity")
        print("These results will make no sense")
        w_g = w_g / u.sr  # Fix to make tests pass

    rate_weighted_g = ((e_true_g / crab_par['e0']) ** (crab_par['alpha'] - mc_par_g['sp_idx'])) \
                      * w_g
    rate_weighted_p = ((e_true_p / proton_par['e0']) ** (proton_par['alpha'] - mc_par_p['sp_idx'])) \
                      * w_p

    #For background, select protons contained in a ring overlapping with the ON region
    p_contained, ang_area_p = ring_containment(angdist2_p, 0.4 * u.deg, 0.3 * u.deg)

    # FIX: ring_radius and ring_halfwidth should have units of deg
    # FIX: hardcoded at the moment, but ring_radius should be read from
    # the gamma file (point-like) or given as input (diffuse).
    # FIX: ring_halfwidth should be given as input
    

    # Initialize arrays
    
    final_gammas = np.ndarray(shape=(n_bins_energy))
    final_protons = np.ndarray(shape=(n_bins_energy))
    pre_gammas = np.ndarray(shape=(n_bins_energy))
    pre_protons = np.ndarray(shape=(n_bins_energy))
    weighted_gamma_per_ebin = np.ndarray(n_bins_energy)
    weighted_proton_per_ebin = np.ndarray(n_bins_energy)
    sensitivity = np.ndarray(shape = n_bins_energy)
    n_excesses_min = np.ndarray(shape = n_bins_energy)
    eff_g = np.ndarray(shape = n_bins_energy)
    eff_p = np.ndarray(shape = n_bins_energy)
    gcut = np.ndarray(shape = n_bins_energy)
    tcut = np.ndarray(shape = n_bins_energy)
    eff_area = np.ndarray(shape = n_bins_energy)
    gamma_rate = np.ndarray(shape = n_bins_energy)
    proton_rate = np.ndarray(shape = n_bins_energy)
    
    #Total rate of gammas and protons
    total_rate_proton = np.sum(rate_weighted_p)
    total_rate_gamma = np.sum(rate_weighted_g)

    print("Total rate triggered proton {:.3f} Hz".format(total_rate_proton))
    print("Total rate triggered gamma  {:.3f} Hz".format(total_rate_gamma))

    #Dataframe to store the events which survive the cuts
    gammalike_events = pd.DataFrame(columns=events_g.keys()) 

    # Weight events and count number of events per bin:
    for i in range(0, n_bins_energy):  # binning in energy
        
        print("\n******** Energy bin: {:.3f} - {:.3f} TeV ********".format(energy[i].value, energy[i + 1].value))
        total_rate_proton_ebin = np.sum(rate_weighted_p[(e_reco_p < energy[i+1]) & (e_reco_p > energy[i])])
        total_rate_gamma_ebin = np.sum(rate_weighted_g[(e_reco_g < energy[i+1]) & (e_reco_g > energy[i])])

        #print("**************")
        print("Total rate triggered proton in this bin {:.5f} Hz".format(total_rate_proton_ebin.value))
        print("Total rate triggered gamma in this bin {:.5f} Hz".format(total_rate_gamma_ebin.value))

        #Calculate the cuts in gammaness and theta2
        
        rates_g = rate_weighted_g[(e_reco_g < energy[i+1]) & (e_reco_g > energy[i])]
        events_bin_g = events_g[(e_reco_g < energy[i+1]) & (e_reco_g > energy[i])]
        events_bin_p = events_p[(e_reco_p < energy[i+1]) & (e_reco_p > energy[i])]

        best_g_cut = find_cut(events_bin_g, rates_g, obstime,  "gammaness", 0, 0.9, fraction_of_gammas_gammaness)
        best_theta2_cut = find_cut(events_bin_g, rates_g, obstime, "theta2", 0.0, 10.0, fraction_of_gammas_theta2) * u.deg**2
         
        events_bin_after_cuts_g = events_bin_g[(events_bin_g.gammaness > best_g_cut) &(events_bin_g.theta2 < best_theta2_cut)]
        events_bin_after_cuts_p = events_bin_p[(events_bin_p.gammaness > best_g_cut) &(events_bin_p.theta2 < best_theta2_cut)]

        #Save the survived events in the dataframe
        gammalike_events = pd.concat((gammalike_events, events_bin_after_cuts_g))
        gammalike_events = pd.concat((gammalike_events, events_bin_after_cuts_p))

        
        # ratio between the area where we search for protons ang_area_p
        # and the area where we search for gammas math.pi * t
        area_ratio_p = np.pi * best_theta2_cut / ang_area_p
        
        rate_g_ebin = np.sum(rate_weighted_g[(e_reco_g < energy[i+1]) & (e_reco_g > energy[i]) \
                                             & (gammaness_g > best_g_cut) & (theta2_g < best_theta2_cut)])

        rate_p_ebin = np.sum(rate_weighted_p[(e_reco_p < energy[i+1]) & (e_reco_p > energy[i]) \
                                             & (gammaness_p > best_g_cut) & p_contained])

        gamma_rate[i] = rate_g_ebin.to(1/u.min).to_value()
        proton_rate[i] = rate_p_ebin.to(1/u.min).to_value()
        
        final_gammas[i] = rate_g_ebin * obstime
        final_protons[i] = rate_p_ebin * obstime * area_ratio_p

        pre_gammas[i] = e_reco_g[(e_reco_g < energy[i+1]) & (e_reco_g > energy[i]) \
                                   & (gammaness_g > best_g_cut) & (theta2_g < best_theta2_cut)].shape[0]
        pre_protons[i] = e_reco_p[(e_reco_p < energy[i+1]) & (e_reco_p > energy[i]) \
                                     & (gammaness_p > best_g_cut) & p_contained].shape[0]

        weighted_gamma_per_ebin[i] = np.sum(rate_weighted_g[(e_reco_g < energy[i+1]) & \
                                                    (e_reco_g > energy[i])]) * obstime
        weighted_proton_per_ebin[i] = np.sum(rate_weighted_p[(e_reco_p < energy[i+1]) & \
                                                     (e_reco_p > energy[i])]) * obstime

        gcut[i] = best_g_cut
        tcut[i] = best_theta2_cut.to_value()
        
                
        eff_g[i] = final_gammas[i] / weighted_gamma_per_ebin[i]
        eff_p[i] = final_protons[i] / weighted_proton_per_ebin[i]

        e_aftercuts = e_true_g[(e_reco_g < energy[i + 1]) & (e_reco_g > energy[i]) \
                               & (gammaness_g > gcut[i]) & (theta2_g < best_theta2_cut)]

        e_aftercuts_p = e_true_p[(e_reco_p < energy[i + 1]) & (e_reco_p > energy[i]) \
                                 & p_contained]
        e_aftercuts_w = np.sum(np.power(e_aftercuts, crab_par['alpha'] - mc_par_g['sp_idx']))

        eff_area[i] = e_aftercuts_w.to_value() / n_sim_bin[i] * mc_par_g['area_sim'].to(u.m**2).to_value()

                
    n_excesses_min, sensitivity = calculate_sensitivity_lima(final_gammas, final_protons*noff,
                                                             1/noff * np.ones_like(final_gammas))
        
    # Avoid bins which are empty or have too few events:
    min_num_events = 10
    min_pre_events = 5

    # Set conditions for calculating sensitivity
    for sens_value, \
        final_protons_value, \
        pre_gamma_value, \
        pre_protons_value, \
        final_gammas_value in np.nditer([sensitivity, \
                                        final_protons, pre_gammas, \
                                         pre_protons, final_gammas], op_flags=['readwrite']):
        
        conditions = (not np.isfinite(sens_value)) or (sens_value<=0) \
                     or (final_gammas_value < min_num_events) \
                     or (pre_gamma_value < min_pre_events) \
                     or (pre_protons_value < min_pre_events)
        if conditions:
            sens_value[...] = np.inf
    
    
    # Compute sensitivity in flux units
    egeom = np.sqrt(energy[1:] * energy[:-1])
    dFdE, par = crab_hegra(egeom)
    sensitivity_flux = sensitivity / 100 * (dFdE * egeom * egeom).to(u.TeV / (u.cm**2 * u.s))

    print("\n******** Energy [TeV] *********\n")
    print(egeom)
    print("\nsensitivity flux:\n", sensitivity_flux)
    print("\nsensitivity[%]:\n", sensitivity)
    print("\n**************\n")
    
    list_of_tuples = list(zip(energy[:energy.shape[0]-1].to_value(), energy[1:].to_value(), gcut, tcut,
                            final_gammas, final_protons,
                            gamma_rate, proton_rate,
                            n_excesses_min, sensitivity_flux.to_value(), eff_area,
                            eff_g, eff_p, pre_gammas, pre_protons))
    
    result = pd.DataFrame(list_of_tuples,
                           columns=['ebin_low', 'ebin_up', 'gammaness_cut', 'theta2_cut',
                                    'gammas_reweighted', 'protons_reweighted',
                                    'gamma_rate', 'proton_rate',
                                    'n_excesses_min', 'sensitivity','eff_area',
                                    'eff_gamma', 'eff_proton',
                                    'mc_gammas', 'mc_protons'])

    units = [energy.unit, energy.unit,"", best_theta2_cut.unit,"", "",
             u.min**-1, u.min**-1, "",
             sensitivity_flux.unit,
             mc_par_g['area_sim'].to(u.cm**2).unit, "", "", "", ""]
    
    return energy, sensitivity, result, units, gammalike_events, gcut, tcut

