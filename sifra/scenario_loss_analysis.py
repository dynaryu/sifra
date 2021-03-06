from __future__ import print_function

import numpy as np
import scipy.stats as stats
import pandas as pd
import json
# import igraph

import os
import copy
import itertools
from colorama import Fore, Back, init, Style
init()

import sifraplot as spl

import matplotlib.pyplot as plt
from matplotlib import gridspec
import seaborn as sns
sns.set(style='whitegrid', palette='coolwarm')

import argparse
from sifra.configuration import Configuration
from sifra.scenario import Scenario
from sifra.modelling.hazard import HazardsContainer
from sifra.model_ingest import ingest_model

# **************************************************************************
# Configuration values that can be adjusted for specific scenarios:

RESTORATION_THRESHOLD = 0.98

# Restoration time starts x time units after hazard impact:
# This represents lead up time for damage and safety assessments
RESTORATION_OFFSET = 1

# **************************************************************************

def fill_between_steps(ax, x, y1, y2=0, step_where='pre', **kwargs):
    ''' 
    Fills between a step plot and x-axis

    ********************************************************************
    Source:        https://github.com/matplotlib/matplotlib/issues/643
    From post by:  tacaswell
    Post date:     Nov 20, 2014
    ********************************************************************

    Parameters
    ----------
    ax : Axes
       The axes to draw to

    x : array-like
        Array/vector of index values.

    y1 : array-like or float
        Array/vector of values to be filled under.
    y2 : array-Like or float, optional
        Array/vector or bottom values for filled area. Default is 0.

    step_where : {'pre', 'post', 'mid'}
        where the step happens, same meanings as for `step`

    **kwargs will be passed to the matplotlib fill_between() function.

    Returns
    -------
    ret : PolyCollection
       The added artist

    '''
    if step_where not in {'pre', 'post', 'mid'}:
        raise ValueError("where must be one of {{'pre', 'post', 'mid'}} "
                         "You passed in {wh}".format(wh=step_where))

    # make sure y values are up-converted to arrays 
    if np.isscalar(y1):
        y1 = np.ones_like(x) * y1

    if np.isscalar(y2):
        y2 = np.ones_like(x) * y2

    # temporary array for up-converting the values to step corners
    # 3 x 2N - 1 array 

    vertices = np.vstack((x, y1, y2))

    # this logic is lifted from lines.py
    # this should probably be centralized someplace
    if step_where == 'pre':
        steps = np.zeros((3, 2 * len(x) - 1), np.float)
        steps[0, 0::2], steps[0, 1::2] = vertices[0, :], vertices[0, :-1]
        steps[1:, 0::2], steps[1:, 1:-1:2] = vertices[1:, :], vertices[1:, 1:]

    elif step_where == 'post':
        steps = np.zeros((3, 2 * len(x) - 1), np.float)
        steps[0, ::2], steps[0, 1:-1:2] = vertices[0, :], vertices[0, 1:]
        steps[1:, 0::2], steps[1:, 1::2] = vertices[1:, :], vertices[1:, :-1]

    elif step_where == 'mid':
        steps = np.zeros((3, 2 * len(x)), np.float)
        steps[0, 1:-1:2] = 0.5 * (vertices[0, :-1] + vertices[0, 1:])
        steps[0, 2::2] = 0.5 * (vertices[0, :-1] + vertices[0, 1:])
        steps[0, 0] = vertices[0, 0]
        steps[0, -1] = vertices[0, -1]
        steps[1:, 0::2], steps[1:, 1::2] = vertices[1:, :], vertices[1:, :]
    else:
        raise RuntimeError(
            "should never hit end of if-elif block for validated input"
        )

    # un-pack
    xx, yy1, yy2 = steps

    # now to the plotting part:
    return ax.fill_between(xx, yy1, y2=yy2, **kwargs)

# ============================================================================


def comp_recovery_given_hazard_and_time(component, component_response,
                                        comptype_dmg_states,
                                        scenario_header, hazval, t,
                                        comps_avl_for_int_replacement,
                                        threshold = 0.98):
    """
    Calculates level of recovery of component at time t after impact

    Currently implemented for earthquake only.
    Hazard transfer parameter is INTENSITY_MEASURE.

    TEST PARAMETERS:
    Example from HAZUS MH MR3, Technical Manual, Ch.8, p8-73
    t = 3
    comptype_dmg_states = ['DS0 None', 'DS1 Slight', 'DS2 Moderate',
        'DS3 Extensive', 'DS4 Complete']
    m   = [np.inf, 0.15, 0.25, 0.35, 0.70]
    b   = [   1.0, 0.60, 0.50, 0.40, 0.40]
    rmu = [-np.inf, 1.0, 3.0, 7.0, 30.0]
    rsd = [    1.0, 0.5, 1.5, 3.5, 15.0]
    --------------------------------------------------------------------------
    """

    ct = component.component_type
    damage_functions = [component.damage_states[i].response_function
                        for i, ds in enumerate(comptype_dmg_states)]
    recovery_functions = [component.damage_states[i].recovery_function
                          for i, ds in enumerate(comptype_dmg_states)]


    comp_fn = component_response.loc[(component.component_id, 'func_mean'),
                                     scenario_header]

    num_dmg_states = len(comptype_dmg_states)
    ptmp = []
    pe = np.array(np.zeros(num_dmg_states))
    pb = np.array(np.zeros(num_dmg_states))
    recov = np.array(np.zeros(num_dmg_states))
    reqtime = np.array(np.zeros(num_dmg_states))

    for d in range(0,num_dmg_states,1)[::-1]:
        pe[d] = damage_functions[d](hazval)
        ptmp.append(pe[d])

    for dmg_index in range(0, num_dmg_states, 1):
        if dmg_index == 0:
            pb[dmg_index] = 1.0 - pe[dmg_index+1]
        elif dmg_index >= 1 and dmg_index < num_dmg_states-1:
            pb[dmg_index] = pe[dmg_index] - pe[dmg_index+1]
        elif dmg_index == num_dmg_states-1:
            pb[dmg_index] = pe[dmg_index]

    # **************************************************************************
    # TODO: implement alternate functions for tempotary restoration
    # if comps_avl_for_int_replacement >= 1:
    #     # Parameters for Temporary Restoration:
    #     rmu = [fragdict['tmp_rst_mean'][ct][ds] for ds in comptype_dmg_states]
    #     rsd = [fragdict['tmp_rst_std'][ct][ds] for ds in comptype_dmg_states]
    # else:
    #     # Parameters for Full Restoration:
    #     rmu = [fragdict['recovery_mean'][ct][ds] for ds in comptype_dmg_states]
    #     rsd = [fragdict['recovery_std'][ct][ds] for ds in comptype_dmg_states]
    # **************************************************************************
    for dmg_index, ds in enumerate(comptype_dmg_states):
        if ds == 'DS0 None' or dmg_index == 0:
            recov[dmg_index] = 1.0
            reqtime[dmg_index] = 0.00
        else:
            recov[dmg_index] = recovery_functions[dmg_index](t)
            reqtime[dmg_index] = \
                recovery_functions[dmg_index](threshold, inverse=True) - \
                recovery_functions[dmg_index](comp_fn, inverse=True)

    comp_status_agg = sum(pb*recov)
    restoration_time_agg = sum(pb*reqtime)
    # restoration_time_agg = reqtime[num_dmg_states-1]

    return comp_status_agg, restoration_time_agg

# ============================================================================

def prep_repair_list(infrastructure_obj,
                     component_meanloss,
                     component_fullrst_time,
                     uncosted_comps,
                     weight_criteria,
                     scenario_header):
    """
    Identify the shortest component repair list to restore supply to output

    This is done based on:
       [1] the priority assigned to the output line
       [2] a weighting criterion applied to each node in the system
    """
    G = infrastructure_obj._component_graph.digraph
    input_dict = infrastructure_obj.supply_nodes
    output_dict = infrastructure_obj.output_nodes
    commodity_types = list(
        set([input_dict[i]['commodity_type'] for i in input_dict.keys()])
        )
    nodes_by_commoditytype = {}
    for comm_type in commodity_types:
        nodes_by_commoditytype[comm_type] = \
            [x for x in input_dict.keys()
             if input_dict[x]['commodity_type']== comm_type]

    out_node_list = output_dict.keys()
    dependency_node_list = \
        [node_id for node_id, infodict in infrastructure_obj.components.items()
         if infrastructure_obj.components[node_id].node_type=='dependency']

    w = 'weight'
    for tp in G.get_edgelist():
        eid = G.get_eid(*tp)
        origin = G.vs[tp[0]]['name']
        destin = G.vs[tp[1]]['name']
        if weight_criteria == None:
            wt = 1.0
        elif weight_criteria == 'MIN_TIME':
            wt = component_fullrst_time.ix[origin]['Full Restoration Time']
        elif weight_criteria == 'MIN_COST':
            wt = component_meanloss.loc[origin, scenario_header]
        G.es[eid][w] = wt

    repair_list = {outnode:{sn:0 for sn in nodes_by_commoditytype.keys()}
                   for outnode in out_node_list}
    repair_list_combined = {}
    
    for onode in out_node_list:
        for CK, sup_nodes_by_commtype in nodes_by_commoditytype.items():
            arr_row = []
            for i,inode in enumerate(sup_nodes_by_commtype):
                arr_row.append(input_dict[inode]['capacity_fraction'])
        
            for i,inode in enumerate(sup_nodes_by_commtype):
                thresh = output_dict[onode]['capacity_fraction']
            
                vx = []
                vlist = []
                for L in range(0, len(arr_row)+1):
                    for subset in \
                            itertools.combinations(range(0, len(arr_row)), L):
                        vx.append(subset)
                    for subset in itertools.combinations(arr_row, L):
                        vlist.append(subset)
                vx = vx[1:]
                vlist = [sum(x) for x in vlist[1:]]
                vcrit = np.array(vlist)>=thresh
            
                sp_len = np.zeros(len(vx))
                LEN_CHK = np.inf
                
                sp_dep = []
                for dnode in dependency_node_list:
                    sp_dep.extend(G.get_shortest_paths(
                        G.vs.find(dnode), to=G.vs.find(onode),
                        weights=w, mode='OUT')[0]
                    )
                for cix, criteria in enumerate(vcrit):
                    sp_list = []
                    if not criteria:
                        sp_len[cix] = np.inf
                    else:
                        for inx in vx[cix]:
                            icnode = sup_nodes_by_commtype[inx]
                            sp_list.extend(G.get_shortest_paths(
                                G.vs.find(icnode),
                                to=G.vs.find(onode),
                                weights=w, mode='OUT')[0])
                        sp_list = np.unique(sp_list)
                        RL = [G.vs[x]['name']
                              for x in set([]).union(sp_dep, sp_list)]
                        sp_len[cix] = len(RL)
                    if sp_len[cix] < LEN_CHK:
                        LEN_CHK = sp_len[cix]
                        repair_list[onode][CK] = sorted(RL)

        temp_repair_list = set(*repair_list[onode].values())
        repair_list_combined[onode] = sorted(
            [x for x in temp_repair_list if x not in uncosted_comps]
        )

    return repair_list_combined

# ============================================================================


def calc_restoration_setup(component_meanloss,
                           out_node_list, comps_uncosted,
                           repair_list_combined,
                           rst_stream, RESTORATION_OFFSET,
                           comp_fullrst_time, output_path,
                           scenario_header, scenario_tag,
                           buffer_time_to_commission=0.00):
    """
    Calculates the timeline for full repair of all output lines of the system

    Depends on the given the hazard/restoration scenario specified through
    the parameters
    --------------------------------------------------------------------------
    :param out_node_list:
            list of output nodes
    :param repair_list_combined:
            dict with output nodes as keys, with list of nodes needing repair
            for each output node as values
    :param rst_stream:
            maximum number of components that can be repaired concurrently
    :param RESTORATION_OFFSET:
            time delay from hazard impact to start of repair
    :param scenario_header:
            hazard intensity value for scenario, given as a string
    :param comps_costed:
            list of all system components for which costs are modelled
    :param comp_fullrst_time:
            dataframe with components names as indices, and time required to
            restore those components
    :param output_path:
            directory path for saving output
    :param scenario_tag:
            tag to add to the outputs produced
    :param buffer_time_to_commission:
            buffer time between completion of one repair task and
            commencement of the next repair task
    --------------------------------------------------------------------------
    :return: rst_setup_df: PANDAS DataFrame with:
                - The components to repaired as indices
                - Time required to repair each component
                - Repair start time for each component
                - Repair end time for each component
    --------------------------------------------------------------------------
    """
    cols = ['NodesToRepair', 'OutputNode', 'RestorationTimes', 
            'RstStart', 'RstEnd', 'DeltaTC', 'RstSeq', 'Fin', 'EconLoss']

    repair_path = copy.deepcopy(repair_list_combined)
    fixed_asset_list = []
    restore_time_each_node = {}
    # restore_time_aggregate = {}
    # rst_setup_dict = {col:{n:[] for n in out_node_list} for col in cols}
    
    rst_setup_df = pd.DataFrame(columns=cols)
    # df = pd.DataFrame(columns=cols)
    
    for onode in out_node_list:
    
        repair_list_combined[onode] = \
            list(set(repair_list_combined[onode]).difference(fixed_asset_list))
        fixed_asset_list.extend(repair_list_combined[onode])
    
        restore_time_each_node[onode] = \
            [comp_fullrst_time.ix[i]['Full Restoration Time'] 
             for i in repair_list_combined[onode]]
        # restore_time_aggregate[onode] = \
        #     max(restore_time_each_node[onode]) + \
        #     sum(np.array(restore_time_each_node[onode]) * 0.01)
    
        df = pd.DataFrame(
            {'NodesToRepair': repair_list_combined[onode],
             'OutputNode': [onode]*len(repair_list_combined[onode]),
             'RestorationTimes': restore_time_each_node[onode],
             'Fin': 0
             })
        df = df.sort_values(by=['RestorationTimes'], ascending=[0])
        rst_setup_df = rst_setup_df.append(df)

    comps_to_drop = set(rst_setup_df.index.values.tolist()).\
                        intersection(comps_uncosted)
    
    rst_setup_df = rst_setup_df.drop(comps_to_drop, axis=0)
    rst_setup_df = rst_setup_df[rst_setup_df['RestorationTimes']!=0]
    rst_setup_df = rst_setup_df.set_index('NodesToRepair')[cols[1:]]
    rst_setup_df['DeltaTC'] = pd.Series(
        rst_setup_df['RestorationTimes'].values * buffer_time_to_commission,
        index=rst_setup_df.index
    )

    for k in repair_path.keys():
        oldlist = repair_path[k]
        repair_path[k] = [v for v in oldlist if v not in comps_uncosted]

    rst_seq = []
    num = len(rst_setup_df.index)
    for i in range(1, 1+int(np.ceil(num/float(rst_stream)))):
        rst_seq.extend([i]*rst_stream)
    rst_seq = rst_seq[:num]
    rst_setup_df['RstSeq'] = pd.Series(rst_seq, index=rst_setup_df.index)

    t_init = 0
    t0 = t_init+RESTORATION_OFFSET
    for inx in rst_setup_df.index[0:rst_stream]:
        if inx!=rst_setup_df.index[0]: t0 += rst_setup_df.ix[inx]['DeltaTC']
        rst_setup_df.loc[inx, 'RstStart'] = t0
        rst_setup_df.loc[inx, 'RstEnd'] = \
            rst_setup_df.ix[inx]['RstStart'] + \
            rst_setup_df.ix[inx]['RestorationTimes']

    dfx = copy.deepcopy(rst_setup_df)
    for inx in rst_setup_df.index[rst_stream:]:
        t0 = min(dfx['RstEnd'])   #rst_setup_df.ix[inx]['DeltaTC']

        finx = rst_setup_df[rst_setup_df['RstEnd']==min(dfx['RstEnd'])]

        for x in finx.index:
            if rst_setup_df.loc[x, 'Fin'] == 0:
                rst_setup_df.loc[x, 'Fin'] = 1
                break
        dfx = rst_setup_df[rst_setup_df['Fin']!=1]
        rst_setup_df.loc[inx, 'RstStart'] = t0
        rst_setup_df.loc[inx, 'RstEnd'] = \
            rst_setup_df.ix[inx]['RstStart'] + \
            rst_setup_df.ix[inx]['RestorationTimes']

    cp_losses = [component_meanloss.loc[c, scenario_header]
                 for c in rst_setup_df.index]
    rst_setup_df['EconLoss'] = cp_losses

    # add a column for 'component_meanloss'
    rst_setup_df.to_csv(
        os.path.join(output_path, 'restoration_setup_'+scenario_tag+'.csv'),
        index_label=['NodesToRepair'], sep=','
    )

    return rst_setup_df

# ============================================================================

def vis_restoration_process(scenario,
                            infrastructure,
                            rst_setup_df,
                            num_rst_steams,
                            repair_path,
                            fig_name):
    """
    Plots:
    - restoration timeline of components, and
    - restoration of supply to output nodes

    --------------------------------------------------------------------------
    Outputs:
    [1] Plot of restored capacity, as step functions
        - Restoration displayed as percentage of pre-disasater
          system output capacity
        - Restoration work is conducted to recover output based on
          'output streams' or 'production lines'
        - Restoration is prioritised in accordance with line priorities
          defined in input file
    [2] A simple Gantt chart of component restoration
    [3] rst_time_line:
        Array of restored line capacity for each time step simulated
    [2] line_rst_times:
        Dict with LINES as keys, and TIME to full restoration as values
    --------------------------------------------------------------------------
    """
    sns.set(style='white')
    
    gainsboro = "#DCDCDC"
    whitesmoke = "#F5F5F5"
    lineht = 10

    output_dict = infrastructure.output_nodes
    out_node_list = infrastructure.output_nodes.keys()

    comps = rst_setup_df.index.values.tolist()
    y = range(1, len(comps)+1)
    xstep = 10
    xbase = 5.0
    xmax = \
        int(xstep * np.ceil(1.01*max(rst_setup_df['RstEnd'])/np.float(xstep)))

    # Limit number of x-steps for labelling
    if xmax/xstep > 15:
        xstep = int(xbase * round((xmax/10.0)/xbase))
    if xmax < xstep:
        xstep = 1
    elif xmax == 0:
        xmax = 2
        xstep = 1
    xtiks = range(0, xmax+1, xstep)
    if xmax > xtiks[-1]:
        xtiks.append(xmax)

    hw_ratio_ax2 = 1.0/2.8
    fig_w_cm  = 9.0
    fig_h_cm  = (fig_w_cm*hw_ratio_ax2) * (1 + len(y)/7.5 + 0.5)
    num_grids = 7 + 3 + len(y)

    fig = plt.figure(facecolor='white', figsize=(fig_w_cm, fig_h_cm))
    gs  = gridspec.GridSpec(num_grids, 1)
    ax1 = plt.subplot(gs[:-11])
    ax2 = plt.subplot(gs[-8:])
    ticklabelsize = 12

    # ----------------------------------------------------------------------
    # Component restoration plot

    ax1.hlines(y, rst_setup_df['RstStart'], rst_setup_df['RstEnd'],
               linewidth=lineht, color=spl.COLR_SET2[2])
    ax1.set_title('Component Restoration Timeline: '+str(num_rst_steams)+
                  ' Simultaneous Repairs', loc='left', y=1.01, size=18)
    ax1.set_ylim([0.5,max(y)+0.5])
    ax1.set_yticks(y)
    ax1.set_yticklabels(comps, size=ticklabelsize)
    ax1.set_xlim([0, max(xtiks)+1])
    ax1.set_xticks(xtiks)
    ax1.set_xticklabels([]);
    for i in range(0, xmax+1, xstep):
        ax1.axvline(i, color='w', linewidth=0.5)
    ax1.yaxis.grid(True, which="major", linestyle='-',
                   linewidth=lineht, color=whitesmoke)
    
    spines_to_remove = ['left', 'top', 'right', 'bottom']
    for spine in spines_to_remove:
        ax1.spines[spine].set_visible(False)

    # ----------------------------------------------------------------------
    # Supply restoration plot

    sns.axes_style(style='ticks')
    sns.despine(ax=ax2, left=True)

    ax2.set_ylim([0,100])
    ax2.set_yticks(range(0,101,20))
    ax2.set_yticklabels(range(0,101,20), size=ticklabelsize)
    ax2.yaxis.grid(True, which="major", color=gainsboro)
    ax2.tick_params(axis='x', which="major", bottom='on', length=4)
    ax2.set_xlim([0, max(xtiks)])
    ax2.set_xticks(xtiks);
    ax2.set_xticklabels(xtiks, size=ticklabelsize, rotation=0)
    ax2.set_xlabel('Restoration Time ('+scenario.time_unit+')', size=16)
    ax2.set_ylabel('System Capacity (%)', size=16)
    
    rst_time_line = np.zeros((len(out_node_list), xmax))
    line_rst_times = {}
    for x, onode in enumerate(out_node_list):
        line_rst_times[onode] = \
            max(rst_setup_df.loc[repair_path[onode]]['RstEnd'])
        
        ax1.axvline(line_rst_times[onode], linestyle=':', 
                    color=spl.COLR_SET1[2], alpha=0.8)
        ax2.axvline(line_rst_times[onode], linestyle=':', 
                    color=spl.COLR_SET1[2], alpha=0.8)
        ax2.annotate(onode, xy=(line_rst_times[onode], 105),
                     ha='center', va='bottom', rotation=90, 
                     fontname='Open Sans', size=ticklabelsize, color='k',
                     annotation_clip=False)    
        rst_time_line[x, :] = \
            100. * output_dict[onode]['capacity_fraction'] * \
            np.array(list(np.zeros(int(line_rst_times[onode]))) +
                     list(np.ones(xmax - int(line_rst_times[onode])))
                     )

    xrst = np.array(range(0, xmax, 1))
    yrst = np.sum(rst_time_line, axis=0)
    ax2.step(xrst, yrst, where='post', color=spl.COLR_SET1[2], clip_on=False)
    fill_between_steps(ax2, xrst, yrst, 0, step_where='post',
                       alpha=0.25, color=spl.COLR_SET1[2])


    fig.savefig(
        os.path.join(scenario.output_path, fig_name),
        format='png', bbox_inches='tight', dpi=400
    )

    plt.close(fig)

    return rst_time_line, line_rst_times

# ============================================================================


def component_criticality(infrastructure,
                          scenario,
                          ctype_scenario_outcomes,
                          hazard_type,
                          scenario_tag,
                          fig_name):
    """
    Plots criticality of components based on cost & time of reparation

    **************************************************************************
    REQUIRED IMPROVEMENTS:
     1. implement a criticality ranking
     2. use the criticality ranking as the label
     3. remove label overlap
    **************************************************************************
    """

    # sns.set(style="ticks",
    #         rc={"axes.facecolor": '#EAEAF2',
    #             "axes.linewidth": 0.75,
    #             "grid.color": 'white',
    #             "grid.linestyle": '-',
    #             "grid.linewidth": 1.5,
    #             "xtick.major.size": 8,
    #             "ytick.major.size": 8})

    sns.set(style="darkgrid",
            rc={"axes.edgecolor": '0.15',
                "axes.linewidth": 0.75,
                "grid.color": 'white',
                "grid.linestyle": '-',
                "grid.linewidth": 2.0,
                "xtick.major.size": 8,
                "ytick.major.size": 8})

    fig = plt.figure(figsize=(7, 7))
    ax = fig.add_subplot(111)

    rt = ctype_scenario_outcomes['restoration_time']
    pctloss_sys = ctype_scenario_outcomes['loss_tot']
    pctloss_ntype = ctype_scenario_outcomes['loss_per_type']*15

    nt_names = ctype_scenario_outcomes.index.tolist()
    nt_ids = range(1, len(nt_names)+1)

    clrmap = [plt.cm.autumn(1.2 * x/float(len(ctype_scenario_outcomes.index)))
              for x in range(len(ctype_scenario_outcomes.index))]

    ax.scatter(rt, pctloss_sys, s=pctloss_ntype, 
            c=clrmap, label=nt_ids,
            marker='o', edgecolor='bisque', lw=1.5,
            clip_on=False)

    for cid, name, i, j in zip(nt_ids, nt_names, rt, pctloss_sys):
        plt.annotate(
            cid, 
            xy=(i, j), xycoords='data',
            xytext=(-20, 20), textcoords='offset points',
            ha='center', va='bottom', rotation=0,
            size=13, fontweight='bold', color='dodgerblue',
            annotation_clip=False,
            bbox=dict(boxstyle='round, pad=0.2', fc='yellow', alpha=0.0),
            arrowprops=dict(arrowstyle = '-|>',
                            shrinkA=5.0,
                            shrinkB=5.0,
                            connectionstyle = 'arc3,rad=0.0',
                            color='dodgerblue',
                            alpha=0.8,
                            linewidth=0.5),)

        plt.annotate(
            "{0:>2.0f}   {1:<s}".format(cid, name), 
            xy = (1.05, 0.95-0.035*cid),
            xycoords=('axes fraction', 'axes fraction'),
            ha = 'left', va = 'top', rotation=0,
            size=9)

    ax.text(1.05, 0.995, 
            "Infrastructure: " + infrastructure.system_class+ "\n" +
            "Hazard: " + hazard_type + " " + scenario_tag,
            ha = 'left', va = 'top', rotation=0,
            fontsize=11, clip_on=False, transform=ax.transAxes)

    ylim = [0, int(max(pctloss_sys)+1)]
    ax.set_ylim(ylim)
    ax.set_yticks([0, max(ylim)*0.5, max(ylim)])
    ax.set_yticklabels(['%0.2f' %y for y in [0, max(ylim)*0.5, max(ylim)]],
                       size=12)
    
    xlim = [0, np.ceil(max(rt)/10.0)*10]
    ax.set_xlim(xlim)
    ax.set_xticks([0, max(xlim)*0.5, max(xlim)])
    ax.set_xticklabels([int(x) for x in [0, max(xlim)*0.5, max(xlim)]],
                       size=12)
    
    # plt.grid(linewidth=3.0)
    ax.set_title('Component Criticality', size=13, y=1.04)
    ax.set_xlabel('Time to Restoration (' +scenario.time_unit+')',
                  size=13, labelpad=14)
    ax.set_ylabel('System Loss (%)', size=13, labelpad=14)

    sns.despine(left=False, bottom=False, right=True, top=True,
                offset=12, trim=True)

    figfile = os.path.join(scenario.output_path, fig_name)
    fig.savefig(figfile, format='png', bbox_inches='tight', dpi=300)
    plt.close(fig)

# ============================================================================


def draw_component_loss_barchart_v1(ctype_loss_vals_tot,
                                    ctype_loss_by_type,
                                    ctype_lossbytype_rank,
                                    ctype_resp_sorted,
                                    scenario_tag,
                                    hazard_type,
                                    output_path,
                                    fig_name):
    """
    :param ctype_loss_vals_tot:
    :param ctype_loss_by_type:
    :param ctype_lossbytype_rank:
    :param ctype_resp_sorted:
    :param scenario_tag:
    :param hazard_type:
    :param output_path:
    :param fig_name:
    :return: builds and saves bar charts of direct economic
             losses for components types
    """

    # Set color maps:
    clrmap1 = [plt.cm.autumn(1.2*x/float(len(ctype_loss_vals_tot)))
               for x in range(len(ctype_loss_vals_tot))]
    clrmap2 = [clrmap1[int(i)] for i in ctype_lossbytype_rank]

    a = 1.0     # transparency
    bar_width = 0.7
    yadjust = bar_width/2.0
    subplot_spacing = 0.6

    cpt = [spl.split_long_label(x,delims=[' ', '_'], max_chars_per_line=22)
           for x in ctype_resp_sorted.index.tolist()]
    pos = np.arange(0,len(cpt))

    fig, (ax1, ax2) = plt.subplots(ncols=2, sharey=True,
                                   facecolor='white',
                                   figsize=(12,len(pos)*0.6))
    fig.subplots_adjust(wspace=subplot_spacing)

    # -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
    # Economic loss contributed by all components of a specific type,
    # as a percentage of the value of the system

    ax1.barh(pos, ctype_loss_vals_tot, bar_width,
             color=clrmap1, edgecolor='bisque', alpha=a)
    ax1.set_xlim(0, max(ctype_loss_by_type))
    ax1.set_ylim(pos.max()+bar_width, pos.min()-bar_width)
    ax1.tick_params(top='off', bottom='off', left='off', right='on')
    ax1.set_title('Economic Loss \nPercent of System Value',
                     fontname='Open Sans', fontsize=12,
                     fontweight='bold', ha='right', x=1.00, y=0.99)

    # add the numbers to the side of each bar
    for p, c, cv in zip(pos, cpt, ctype_loss_vals_tot):
        ax1.annotate(('%0.1f' % np.float(cv))+'%',
                     xy=(cv+0.5, p+yadjust),
                     xycoords=('data', 'data'),
                     ha='right', va='center', size=11,
                     annotation_clip=False)

    ax1.xaxis.set_ticks_position('none')
    ax1.set_axis_off()

    # -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
    # Aggregated economic loss for all components of a specific type

    ax2.barh(pos, ctype_loss_by_type, bar_width,
             color=clrmap2, edgecolor='bisque', alpha=a)
    ax2.set_xlim(0, max(ctype_loss_by_type))
    ax2.set_ylim(pos.max()+bar_width, pos.min()-bar_width)
    ax2.tick_params(top='off', bottom='off', left='on', right='off')
    ax2.set_title('Economic Loss \nPercent of Component Type Value',
                  fontname='Open Sans', fontsize=12,
                  fontweight='bold', ha='left', x=0,  y=0.99)

    for p, c, cv in zip(pos, cpt, ctype_loss_by_type):
        ax2.annotate(('%0.1f' % np.float(cv))+'%', xy=(cv+0.5, p+yadjust),
                     xycoords=('data', 'data'),
                     ha='left', va='center', size=11,
                     annotation_clip=False)

    ax2.xaxis.set_ticks_position('none')
    ax2.set_axis_off()

    # -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --

    ax1.invert_xaxis()

    for yloc, ylab in zip(pos, cpt):
        ax1.annotate(ylab,
                     xy=(1.0+subplot_spacing/2.0, yloc+yadjust),
                     xycoords=('axes fraction', 'data'),
                     ha='center', va='center', size=11, color='k',
                     annotation_clip=False)

    ax1.annotate('HAZARD EVENT\n' + hazard_type + '\n' + scenario_tag,
                 xy=(1.0 + subplot_spacing/2.0, -1.25),
                 xycoords=('axes fraction', 'data'),
                 ha='center', va='center', size=12,
                 fontname='Open Sans', color='darkgrey', weight='bold',
                 annotation_clip=False)

    fig.savefig(os.path.join(output_path, fig_name),
                format='png', bbox_inches='tight', dpi=300)

    plt.close(fig)

# ============================================================================


def draw_component_loss_barchart_v2(ctype_loss_vals_tot,
                                    ctype_loss_by_type,
                                    ctype_resp_sorted,
                                    scenario_tag,
                                    hazard_type,
                                    output_path,
                                    fig_name):
    """ Plots bar charts of direct economic losses for components types """

    bar_width = 0.36
    bar_offset = 0.02
    bar_clr_1 = spl.COLR_SET1[0]
    bar_clr_2 = spl.COLR_SET1[1]
    grid_clr = "#BBBBBB"

    cpt = [spl.split_long_label(x,delims=[' ', '_'], max_chars_per_line=22)
           for x in ctype_resp_sorted.index.tolist()]
    pos = np.arange(0, len(cpt))

    fig = plt.figure(figsize=(4.5, len(pos)*0.6), facecolor='white')
    axes = fig.add_subplot(111, facecolor='white')

    # ------------------------------------------------------------------------
    # Economic loss:
    #   - Contribution to % loss of total system, by components type
    #   - Percentage econ loss for all components of a specific type

    axes.barh(
        pos-bar_width/2.0-bar_offset, ctype_loss_vals_tot, bar_width,
        align='center',
        color=bar_clr_1, alpha=0.80, edgecolor=None,
        label="% loss of total system value (for a component type)"
    )

    axes.barh(
        pos+bar_width/2.0+bar_offset, ctype_loss_by_type, bar_width,
        align='center',
        color=bar_clr_2, alpha=0.80, edgecolor=None,
        label="% loss for component type"
    )

    for p, c, cv in zip(pos, cpt, ctype_loss_vals_tot):
        axes.annotate(('%0.1f' % np.float(cv))+'%',
                      xy=(cv+0.7, p-bar_width/2.0-bar_offset),
                      xycoords=('data', 'data'),
                      ha='left', va='center', size=8, color=bar_clr_1,
                      annotation_clip=False)

    for p, c, cv in zip(pos, cpt, ctype_loss_by_type):
        axes.annotate(('%0.1f' % np.float(cv))+'%',
                      xy=(cv+0.7, p+bar_width/2.0+bar_offset*2),
                      xycoords=('data', 'data'),
                      ha='left', va='center', size=8, color=bar_clr_2,
                      annotation_clip=False)

    axes.annotate(
        "ECONOMIC LOSS % by COMPONENT TYPE",
        xy=(0.0, -1.65), xycoords=('axes fraction', 'data'),
        ha='left', va='top',
        fontname='Open Sans', size=10, color='k', weight='bold',
        annotation_clip=False)
    axes.annotate(
        "Hazard: " + hazard_type + scenario_tag,
        xy=(0.0, -1.2), xycoords=('axes fraction', 'data'),
        ha='left', va='top',
        fontname='Open Sans', size=10, color='slategray', weight='bold',
        annotation_clip=False)

    lgnd = axes.legend(loc="upper left", ncol=1, bbox_to_anchor=(-0.1, -0.04),
                       borderpad=0, frameon=0,
                       prop={'size':8, 'weight':'medium'})
    for text in lgnd.get_texts():
        text.set_color('#555555')
    axes.axhline(y=pos.max()+bar_width*2.4, xmin=0, xmax=0.4,
                 lw=0.6, ls='-', color='#444444', clip_on=False)

    # ------------------------------------------------------------------------
    spines_to_remove = ['top', 'bottom']
    for spine in spines_to_remove:
        axes.spines[spine].set_visible(False)
    axes.spines['left'].set_color(grid_clr)
    axes.spines['left'].set_linewidth(0.5)
    axes.spines['right'].set_color(grid_clr)
    axes.spines['right'].set_linewidth(0.5)

    axes.set_xlim(0, 100)
    axes.set_xticks(np.linspace(0, 100, 5, endpoint=True))
    axes.set_xticklabels([''])
    axes.xaxis.grid(True, color=grid_clr, linewidth=0.5, linestyle='-')

    axes.set_ylim([pos.max()+bar_width*1.5, pos.min()-bar_width*1.5])
    axes.set_yticks(pos)
    axes.set_yticklabels(cpt, size=8, color='k')
    axes.yaxis.grid(False)

    axes.tick_params(top='off', bottom='off', left='off', right='off')

    # ------------------------------------------------------------------------

    fig.savefig(
        os.path.join(output_path, fig_name),
        format='png', bbox_inches='tight', dpi=400
    )

    plt.close(fig)

# ============================================================================


def draw_component_failure_barchart(uncosted_comptypes,
                                    ctype_failure_mean,
                                    scenario_name,
                                    scenario_tag,
                                    hazard_type,
                                    output_path,
                                    figname):

    comp_type_fail_sorted = \
        ctype_failure_mean.sort_values(by=(scenario_name), ascending=False)
    cpt_failure_vals = comp_type_fail_sorted[scenario_name].values * 100

    for x in uncosted_comptypes:
        if x in comp_type_fail_sorted.index.tolist():
            comp_type_fail_sorted = comp_type_fail_sorted.drop(x, axis=0)

    cptypes = comp_type_fail_sorted.index.tolist()
    cpt = [spl.split_long_label(x,delims=[' ', '_'],max_chars_per_line=22)
           for x in cptypes]
    pos = np.arange(len(cptypes))

    fig = plt.figure(figsize=(4.5, len(pos)*0.55),
                     facecolor='white')
    ax = fig.add_subplot(111)
    bar_width = 0.4
    bar_clr = "#D62F20"   #CA1C1D"    # dodgerblue
    grid_clr = "#BBBBBB"

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    spines_to_remove = ['top', 'bottom']
    for spine in spines_to_remove:
        ax.spines[spine].set_visible(False)
    ax.spines['left'].set_color(grid_clr)
    ax.spines['left'].set_linewidth(0.5)
    ax.spines['right'].set_color(grid_clr)
    ax.spines['right'].set_linewidth(0.5)

    ax.set_xlim(0, 100)
    ax.set_xticks(np.linspace(0, 100, 5, endpoint=True))
    ax.set_xticklabels([''])
    ax.xaxis.grid(True, color=grid_clr, linewidth=0.5, linestyle='-')

    ax.set_ylim([pos.max()+bar_width, pos.min()-bar_width])
    ax.set_yticks(pos)
    ax.set_yticklabels(cpt, size=8, color='k')
    ax.yaxis.grid(False)

    ax.tick_params(top='off', bottom='off', left='off', right='off')

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    ax.barh(pos, cpt_failure_vals, bar_width,
            color=bar_clr, alpha=0.8, edgecolor=None)

    # add the numbers to the side of each bar
    for p, c, cv in zip(pos, cptypes, cpt_failure_vals):
        plt.annotate(('%0.1f' % cv)+'%', xy=(cv+0.5, p),
                     va='center', size=8, color="#CA1C1D",
                     annotation_clip=False)

    ax.annotate('FAILURE RATE: % FAILED COMPONENTS by TYPE',
                xy=(0.0, -1.45), xycoords=('axes fraction', 'data'),
                ha='left', va='top', annotation_clip=False,
                fontname='Open Sans', size=10, weight='bold', color='k')
    ax.annotate('Hazard: ' + hazard_type + scenario_tag,
                xy=(0.0, -1.0), xycoords=('axes fraction', 'data'),
                ha='left', va='top', annotation_clip=False,
                fontname='Open Sans', size=10, weight='bold',
                color='slategray')

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    fig.savefig(
        os.path.join(output_path, figname),
        format='png', bbox_inches='tight', dpi=400
    )

    plt.close(fig)

# ============================================================================


def calc_comptype_damage_scenario_given_hazard(infrastructure,
                                               scenario,
                                               hazards,
                                               ctype_resp_sorted,
                                               component_response,
                                               cp_types_costed,
                                               scenario_header):

    nodes_all = infrastructure.components.keys()
    nodes_costed = [x for x in nodes_all
                    if infrastructure.components[x].component_type in
                    cp_types_costed]
    nodes_costed.sort()

    comptype_num = {
        x:len(list(infrastructure.get_components_for_type(x)))
        for x in cp_types_costed
        }
    comptype_used = {x:0 for x in cp_types_costed}

    # ------------------------------------------------------------------------
    # Logic for internal component replacement / scavenging

    comptype_for_internal_replacement = {}
    # for x in cp_types_in_system:
    #     if x in cp_types_costed:
    #         comptype_for_internal_replacement[x] = \
    #             int(np.floor(
    #                 (1.0 - comptype_resp_df.loc[
    #                     (x, 'num_failures'), scenario_header]
    #                  ) * comptype_num[x]
    #             ))
    #     else:
    #         comptype_for_internal_replacement[x] = 0
    for x in cp_types_costed:
        comptype_for_internal_replacement[x] = \
            int(np.floor(
                (1.0 - ctype_resp_sorted.loc[x, 'num_failures']
                 ) * comptype_num[x]
            ))

    # ------------------------------------------------------------------------
    # Using the HAZUS method:

    comp_rst = {t: {n: 0 for n in nodes_costed}
                for t in scenario.restoration_time_range}
    for c in nodes_costed:
        ct = infrastructure.components[c].component_type
        haz_ix = hazards.hazard_scenario_name.index(scenario_header)
        sc_haz_val = \
            hazards.listOfhazards[haz_ix].get_hazard_intensity_at_location(
                infrastructure.components[c].longitude,
                infrastructure.components[c].latitude)

        comptype_used[ct] += 1
        comps_avl_for_int_replacement = \
            comptype_for_internal_replacement[ct] - comptype_used[ct]
        comp_type_ds = \
            [xx.damage_state_name for xx in
             list(infrastructure.components[c].damage_states.values())]

        for t in scenario.restoration_time_range:
            comp_rst[t][c] = comp_recovery_given_hazard_and_time(
                infrastructure.components[c],
                component_response,
                comp_type_ds,
                scenario_header,
                sc_haz_val,
                t,
                comps_avl_for_int_replacement,
                threshold=RESTORATION_THRESHOLD)[0]

    comp_rst_df = pd.DataFrame(comp_rst,
                               index=nodes_costed,
                               columns=scenario.restoration_time_range)

    comp_rst_time_given_haz = \
        [np.round(comp_rst_df.columns[comp_rst_df.loc[c]
                                      >= RESTORATION_THRESHOLD][0], 0)
         for c in nodes_costed]

    # ------------------------------------------------------------------------

    component_fullrst_time = pd.DataFrame(
                        {'Full Restoration Time': comp_rst_time_given_haz},
                        index=nodes_costed)
    component_fullrst_time.index.names=['component_id']

    # ------------------------------------------------------------------------

    ctype_scenario_outcomes = copy.deepcopy(
        100 * ctype_resp_sorted.drop(['func_mean', 'func_std'], axis=1)
    )

    cpmap = {c:sorted(list(infrastructure.get_components_for_type(c)))
             for c in cp_types_costed}

    rtimes = []
    for x in ctype_scenario_outcomes.index:
        rtimes.append(np.mean(component_fullrst_time.loc[cpmap[x]].values))
    ctype_scenario_outcomes['restoration_time'] = rtimes

    return component_fullrst_time, ctype_scenario_outcomes


def main():

    # --------------------------------------------------------------------------
    # *** BEGIN : SETUP ***

    # Read in SETUP data
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--setup", type=str,
                        help="Setup file for simulation scenario, and \n"
                             "locations of inputs, outputs, and system model.")
    parser.add_argument("-v", "--verbose",  type=str,
                        help="Choose option for logging level from: \n"
                             "DEBUG, INFO, WARNING, ERROR, CRITICAL.")
    parser.add_argument("-d", "--dirfile", type=str,
                        help="JSON file with location of input/output files "
                             "from past simulation that is to be analysed\n.")
    args = parser.parse_args()

    if args.setup is None:
        raise ValueError("Must provide a correct setup argument: "
                         "`-s` or `--setup`,\n"
                         "Setup file for simulation scenario, and \n"
                         "locations of inputs, outputs, and system model.\n")

    if not os.path.exists(args.dirfile):
        raise ValueError("Could not locate file with directory locations"
                         "with results from pre-run simulations.\n")

    # Define input files, output location, scenario inputs
    with open(args.dirfile, 'r') as dat:
        dir_dict = json.load(dat)

    # Configure simulation model.
    # Read data and control parameters and construct objects.
    config = Configuration(args.setup,
                           run_mode='analysis',
                           output_path=dir_dict["OUTPUT_PATH"])
    scenario = Scenario(config)
    hazards = HazardsContainer(config)
    infrastructure = ingest_model(config)

    if not config.SYS_CONF_FILE_NAME == dir_dict["SYS_CONF_FILE_NAME"]:
        raise NameError("Names for supplied system model names did not match."
                        "Aborting.\n")

    SYS_CONFIG_FILE = config.SYS_CONF_FILE
    OUTPUT_PATH = dir_dict["OUTPUT_PATH"]
    RAW_OUTPUT_DIR = dir_dict["RAW_OUTPUT_DIR"]

    RESTORATION_STREAMS = scenario.restoration_streams
    FOCAL_HAZARD_SCENARIOS = hazards.focal_hazard_scenarios

    if config.HAZARD_INPUT_METHOD == "hazard_array":
        hazard_intensity_vals = \
            [hazard_data[0]['hazard_intensity']
             for hazard_data in
             hazards.scenario_hazard_data.values()]
        haz_vals_str = [('%0.3f' % np.float(x))
                        for x in hazard_intensity_vals]

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # READ in raw output files from prior analysis of system fragility

    economic_loss_array = \
        np.load(os.path.join(
            RAW_OUTPUT_DIR, 'economic_loss_array.npy'))

    calculated_output_array = \
        np.load(os.path.join(
            RAW_OUTPUT_DIR, 'calculated_output_array.npy'))

    exp_damage_ratio = \
        np.load(os.path.join(
            RAW_OUTPUT_DIR, 'exp_damage_ratio.npy'))

    sys_frag = \
        np.load(os.path.join(
            RAW_OUTPUT_DIR, 'sys_frag.npy'))

    # TODO: NOT IMPLEMENTED -- need to.
    # output_array_given_recovery = \
    #     np.load(os.path.join(
    #         RAW_OUTPUT_DIR, 'output_array_given_recovery.npy'))
    #
    # required_time = \
    #     np.load(os.path.join(RAW_OUTPUT_DIR, 'required_time.npy'))

    if infrastructure.system_class.lower() == 'powerstation':
        pe_sys = np.load(os.path.join(RAW_OUTPUT_DIR, 'pe_sys_econloss.npy'))
    elif infrastructure.system_class.lower() == 'substation':
        pe_sys = np.load(os.path.join(RAW_OUTPUT_DIR, 'pe_sys_cpfailrate.npy'))
    elif infrastructure.system_class.lower() == \
            'PotableWaterTreatmentPlant'.lower():
        pe_sys = np.load(os.path.join(RAW_OUTPUT_DIR, 'pe_sys_econloss.npy'))

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # Read in SIMULATED HAZARD RESPONSE for <COMPONENT TYPES>

    comptype_resp_df = \
        pd.read_csv(os.path.join(OUTPUT_PATH, 'comptype_response.csv'),
                    index_col=['component_type', 'response'],
                    skipinitialspace=True)
    comptype_resp_df.columns = hazards.hazard_scenario_name

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # Nodes not considered in the loss calculations
    # NEED TO MOVE THESE TO A MORE LOGICAL PLACE

    uncosted_comptypes = ['CONN_NODE',
                          'SYSTEM_INPUT',
                          'SYSTEM_OUTPUT',
                          'JUNCTION_NODE',
                          'Generation Source',
                          'Grounding']

    cp_types_in_system = infrastructure.get_component_types()
    cp_types_costed = [x for x in cp_types_in_system
                       if x not in uncosted_comptypes]

    comptype_resp_df = comptype_resp_df.drop(
        uncosted_comptypes, level='component_type', axis=0)

    # Get list of only those components that are included in cost calculations:
    cpmap = {c:sorted(list(infrastructure.get_components_for_type(c)))
             for c in cp_types_in_system}
    comps_costed = [v for x in cp_types_costed for v in cpmap[x]]

    nodes_all = infrastructure.components.keys()
    nodes_all.sort()
    comps_uncosted = list(set(nodes_all).difference(comps_costed))

    ctype_failure_mean = comptype_resp_df.xs('num_failures', level='response')
    ctype_failure_mean.columns.names = ['Scenario Name']

    # ctype_loss_mean = \
    #     ct_resp_flat[ct_resp_flat['response'] == 'loss_mean'].\
    #     drop('response', axis=1)

    # ctype_loss_tot = \
    #     ct_resp_flat[ct_resp_flat['response'] == 'loss_tot'].\
    #     drop('response', axis=1)

    # ctype_loss_std = \
    #     ct_resp_flat[ct_resp_flat['response'] == 'loss_std'].\
    #     drop('response', axis=1)

    # ctype_func_mean = \
    #     ct_resp_flat[ct_resp_flat['response'] == 'func_mean'].\
    #     drop('response', axis=1)

    # ctype_func_std = \
    #     ct_resp_flat[ct_resp_flat['response'] == 'func_std'].\
    #     drop('response', axis=1)

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # Value of component types relative to system value

    comptype_value_dict = {}
    for ct in sorted(cp_types_costed):
        comp_val = [infrastructure.components[comp_id].cost_fraction
                    for comp_id in cpmap[ct]]
        comptype_value_dict[ct] = sum(comp_val)

    comptype_value_list = [comptype_value_dict[ct]
                           for ct in sorted(comptype_value_dict.keys())]

    component_response = \
        pd.read_csv(os.path.join(OUTPUT_PATH, 'component_response.csv'),
                    index_col=['component_id', 'response'],
                    skiprows=0, skipinitialspace=True)
    # component_response = component_response.drop(
    #     comps_uncosted, level='component_id', axis=0)
    component_meanloss = \
        component_response.query('response == "loss_mean"').\
            reset_index('response').drop('response', axis=1)

    comptype_resp_df = comptype_resp_df.drop(
        uncosted_comptypes, level='component_type', axis=0)

    # TODO : ADD THIS BACK IN!!
    # # Read in the <SYSTEM FRAGILITY MODEL> fitted to simulated data
    # system_fragility_mdl = \
    #     pd.read_csv(os.path.join(OUTPUT_PATH, 'system_model_fragility.csv'),
    #                 index_col=0)
    # system_fragility_mdl.index.name = "Damage States"

    # Define the system as a network, with components as nodes
    # Network setup with igraph
    G = infrastructure._component_graph
    # --------------------------------------------------------------------------
    # *** END : SETUP ***

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # Set weighting criteria for edges:
    # This influences the path chosen for restoration
    # Options are:
    #   [1] None
    #   [2] 'MIN_COST'
    #   [3] 'MIN_TIME'
    weight_criteria = 'MIN_COST'

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    col_tp = []
    for h in FOCAL_HAZARD_SCENARIOS:
        col_tp.extend(zip([h]*len(RESTORATION_STREAMS), RESTORATION_STREAMS))
    mcols = pd.MultiIndex.from_tuples(
                col_tp, names=['Hazard', 'Restoration Streams'])
    line_rst_times_df = \
        pd.DataFrame(index=infrastructure.output_nodes.keys(), columns=mcols)
    line_rst_times_df.index.name = 'Output Lines'

    # --------------------------------------------------------------------------
    # *** BEGIN : FOCAL_HAZARD_SCENARIOS FOR LOOP ***
    for sc_haz_str in FOCAL_HAZARD_SCENARIOS:

        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        # Differentiated setup based on hazard input type - scenario vs array
        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

        if config.HAZARD_INPUT_METHOD == "hazard_array":
            scenario_header = hazards.hazard_scenario_name[
                hazards.hazard_scenario_list.index(sc_haz_str)]
        elif config.HAZARD_INPUT_METHOD == "scenario_file":
            scenario_header = sc_haz_str
        scenario_tag = str(sc_haz_str)+ " " + hazards.intensity_measure_unit +\
                       " | " + hazards.intensity_measure_param


        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        # Extract scenario-specific values from the 'hazard response' dataframe
        # Scenario response: by component type
        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

        ctype_resp_scenario \
            = comptype_resp_df[scenario_header].unstack(level=-1)
        ctype_resp_scenario = ctype_resp_scenario.sort_index()

        # uncosted_comptypes_in_df \
        #     = list(set(ctype_resp_scenario.index.tolist()) &
        #            set(uncosted_comptypes))
        # if uncosted_comptypes_in_df:
        #     ctype_resp_scenario = ctype_resp_scenario.drop(
        #         uncosted_comptypes_in_df, axis=0)

        ctype_resp_scenario['loss_per_type']\
            = ctype_resp_scenario['loss_mean']/comptype_value_list

        ctype_resp_sorted = ctype_resp_scenario.sort_values(
            by='loss_tot', ascending=False)

        ctype_loss_vals_tot \
            = ctype_resp_sorted['loss_tot'].values * 100
        ctype_loss_by_type \
            = ctype_resp_sorted['loss_per_type'].values * 100
        ctype_lossbytype_rank = \
            len(ctype_loss_by_type) - \
            stats.rankdata(ctype_loss_by_type, method='dense').astype(int)

        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        # Economic loss percentage for component types

        fig_name = 'fig_SC_' + sc_haz_str + '_loss_sys_vs_comptype_v1.png'
        draw_component_loss_barchart_v1(ctype_loss_vals_tot,
                                        ctype_loss_by_type,
                                        ctype_lossbytype_rank,
                                        ctype_resp_sorted,
                                        scenario_tag,
                                        hazards.hazard_type,
                                        OUTPUT_PATH,
                                        fig_name)

        fig_name = 'fig_SC_' + sc_haz_str + '_loss_sys_vs_comptype_v2.png'
        draw_component_loss_barchart_v2(ctype_loss_vals_tot,
                                        ctype_loss_by_type,
                                        ctype_resp_sorted,
                                        scenario_tag,
                                        hazards.hazard_type,
                                        OUTPUT_PATH,
                                        fig_name)

        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        # FAILURE RATE -- PERCENTAGE of component types

        fig_name = 'fig_SC_' + sc_haz_str + '_comptype_failures.png'
        draw_component_failure_barchart(uncosted_comptypes,
                                        ctype_failure_mean,
                                        scenario_header,
                                        scenario_tag,
                                        hazards.hazard_type,
                                        OUTPUT_PATH,
                                        fig_name)

        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        # RESTORATION PROGNOSIS for specified scenarios

        component_fullrst_time, ctype_scenario_outcomes = \
            calc_comptype_damage_scenario_given_hazard(infrastructure,
                                                       scenario,
                                                       hazards,
                                                       ctype_resp_sorted,
                                                       component_response,
                                                       cp_types_costed,
                                                       scenario_header)

        # All the nodes that need to be fixed for each output node:
        repair_list_combined = prep_repair_list(infrastructure,
                                                component_meanloss,
                                                component_fullrst_time,
                                                comps_uncosted,
                                                weight_criteria,
                                                scenario_header)

        repair_path = copy.deepcopy(repair_list_combined)
        output_node_list = infrastructure.output_nodes.keys()

        for num_rst_steams in RESTORATION_STREAMS:
            # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
            # SYSTEM RESTORATION for given scenario & restoration setup
            rst_setup_df = calc_restoration_setup(
                component_meanloss,
                output_node_list,
                comps_uncosted,
                repair_list_combined,
                num_rst_steams,
                RESTORATION_OFFSET,
                component_fullrst_time,
                scenario.output_path,
                scenario_header,
                scenario_tag
            )

            fig_rst_gantt_name = 'fig_SC_' + sc_haz_str + '_str' +\
                                 str(num_rst_steams) + '_restoration.png'
            rst_time_line, line_rst_times = vis_restoration_process(
                scenario,
                infrastructure,
                rst_setup_df,
                num_rst_steams,
                repair_path,
                fig_rst_gantt_name
            )

            line_rst_times_df[(sc_haz_str, num_rst_steams)] = \
                [line_rst_times[x] for x in output_node_list]

            # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
            # COMPONENT CRITICALITY for given scenario & restoration setup

            fig_name = 'fig_SC_' + sc_haz_str + '_str' +\
                       str(num_rst_steams) + '_component_criticality.png'
            component_criticality(infrastructure,
                                  scenario,
                                  ctype_scenario_outcomes,
                                  hazards.hazard_type,
                                  scenario_tag,
                                  fig_name)

    # --------------------------------------------------------------------------
    # *** END : FOCAL_HAZARD_SCENARIOS FOR LOOP ***

    line_rst_times_csv = os.path.join(
        OUTPUT_PATH, 'line_restoration_prognosis.csv')
    line_rst_times_df.to_csv(line_rst_times_csv, sep=',')

    print("--- --- --- --- --- --- --- --- ---")
    print(Fore.YELLOW + "Scenario loss analysis complete." + Fore.RESET + "\n")
    print("Outputs saved in: \n" +
          Fore.GREEN + OUTPUT_PATH + Fore.RESET + '\n')
    ############################################################################


if __name__ == "__main__":
    print()
    print(Back.WHITE + Fore.BLUE + Style.BRIGHT +
          " >> Scenario loss analysis initiated ... " +
          Style.RESET_ALL + "\n")
    main()
