import sys
import pandas as pd

from sifraclasses import _FacilityDataGetter

from modelling.component import Component, ConnectionValues

from modelling.infrastructure_system import IFSystem

from sifra.modelling.elements import (RecoveryState,
                                      DamageAlgorithm,
                                      RecoveryAlgorithm)

from sifra.modelling.responsemodels import (LogNormalCDF,
                                            NormalCDF,
                                            StepFunc)

import copy


def ingest_spreadsheet(config):
    facility_data = _FacilityDataGetter(config)
    component_dict = {}

    damage_algorithm_vals = None
    recovery_algorithm_vals = None
    damage_state_df = pd.read_excel(
        facility_data.sys_config_file, sheetname='damage_state_def',
        index_col=[0, 1], header=0,
        skiprows=3, skipinitialspace=True)

    damage_def_dict = {}
    for index, damage_def in damage_state_df.iterrows():
        damage_def_dict[index] = damage_def

    for index, damage_state in facility_data.fragility_data.iterrows():
        component_type = index[0]
        if component_type not in component_dict:
            damage_algorithm_vals = {}
            recovery_algorithm_vals = {}
            # store the current values in the Algorithms
            component_dict[component_type] = {}
            component_dict[component_type]['component_type'] = component_type
            component_dict[component_type]['frag_func'] = DamageAlgorithm(damage_states=damage_algorithm_vals)
            component_dict[component_type]['recovery_func'] = RecoveryAlgorithm(recovery_states=recovery_algorithm_vals)
        else:
            damage_algorithm_vals = component_dict[component_type]['frag_func'].damage_states
            recovery_algorithm_vals = component_dict[component_type]['recovery_func'].recovery_states

        ds_level = index[1]
        if index in damage_def_dict:
            damage_def_state = damage_def_dict[index]
        else:
            print("Damage definition not found {}".format(index))

        response_params = {}
        response_params['functionality'] = damage_state['functionality']
        response_params['fragility_source'] = damage_state['fragility_source']
        response_params['damage_state_description'] = damage_def_state['damage_state_definition']
        if damage_state['damage_function'] == 'Lognormal':
            # translate the column names
            response_params['median'] = damage_state['damage_median']
            response_params['beta'] = damage_state['damage_logstd']
            response_params['mode'] = damage_state['mode']
            response_model = LogNormalCDF(**response_params)
        elif damage_state['damage_function'] == 'Normal':
            response_model = NormalCDF(damage_state)
        elif damage_state['damage_function'] == 'StepFunc':
            response_model = LogNormalCDF(damage_state)
        else:
            raise ValueError("No response model "
                             "matches {}".format(damage_state['damage_function']))
        # add the response model to damage algorithm
        damage_algorithm_vals[ds_level] = response_model

        # create the recovery_model
        recovery_columns = set(('recovery_std', 'recovery_mean', 'recovery_95percentile'))
        recovery_params = {key: damage_state[key] for key in recovery_columns}
        recovery_algorithm_vals[ds_level] = RecoveryState(**recovery_params)

    # add the other component attributes and make a component dict
    system_components = {}
    for component_id, component_details in facility_data.comp_df.iterrows():
        component_type = component_details['component_type']
        if component_type in component_dict:
            component_values = copy.deepcopy(component_dict[component_type])
        else:
            print("Unknown component {}".format(component_type))
            continue

        component_values['component_id'] = component_id
        component_values['component_type'] = component_details['component_type']
        component_values['component_class'] = component_details['component_class']
        component_values['cost_fraction'] = component_details['cost_fraction']
        component_values['node_type'] = component_details['node_type']
        component_values['node_cluster'] = component_details['node_cluster']
        component_values['op_capacity'] = component_details['op_capacity']

        system_components[component_id] = Component(**component_values)

    # now we add children!
    for index, connection_values in facility_data.node_conn_df.iterrows():
        component_id = connection_values['origin']
        system_component = system_components[component_id]
        destiny = system_component.destination_components
        if not destiny:
            destiny = system_component.destination_components = {}
        edge_values = {}
        edge_values['link_capacity'] = connection_values['link_capacity']
        edge_values['weight'] = connection_values['weight']
        destiny[connection_values['destination']] = ConnectionValues(**edge_values)

    if_system_values = {}
    if_system_values['name'] = 'Coal power station 600MW'
    if_system_values['components'] = system_components

    return IFSystem(**if_system_values)
