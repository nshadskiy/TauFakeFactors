"""
Script for preprocessing n-tuples for the fake factor calculation
"""

import os
import sys
import argparse
import yaml
import multiprocessing

# import gc
from io import StringIO
from wurlitzer import pipes, STDOUT


from helper.Logger import Logger
import helper.filters as filters
import helper.weights as weights
import helper.functions as func


parser = argparse.ArgumentParser()

parser.add_argument(
    "--config",
    default="config",
    help="Name of a config file in configs/ which contains information for the preselection step.",
)
parser.add_argument(
    "--config-file",
    default=None,
    help="path to the config file",
)
parser.add_argument(
    "--nthreads",
    default=8,
    help="Number of threads to use for the preselection step.",
)

tau_wps = ["VLoose", "Loose", "Medium", "Tight", "VTight", "VVTight"]
output_feature = [
    "weight",
    "btag_weight",
    "njets",
    "nbtag",
    "boosted_q_1",
    "boosted_pt_2",
    "boosted_q_2",
    "boosted_gen_match_2",
    "boosted_m_vis",
    "boosted_mt_1",
    "no_extra_lep",
    "boosted_deltaR_ditaupair",
    "boosted_pt_1",
    "metphi",
    # following variables are not directly needed for the FF calculation
    "boosted_eta_1",
    "boosted_phi_1",
    "boosted_eta_2",
    "boosted_phi_2",
    "boosted_iso_1",
    "boosted_iso_2",
    "bpt_1",
    "beta_1",
    "bphi_1",
    "bpt_2",
    "mjj",
    "met",
]

for wp in tau_wps:
    output_feature.append("id_boostedtau_iso_" + wp + "_2")
    output_feature.append("id_wgt_boostedtau_iso_" + wp + "_2")


def run_preselection(args):
    import ROOT

    process, config = args
    print("Processing process: {}".format(process))
    # bookkeeping of samples files due to splitting based on the tau origin (genuine, jet fake, lepton fake)
    process_file_dict = dict()
    for tau_gen_mode in config["processes"][process]["tau_gen_modes"]:
        process_file_dict[tau_gen_mode] = list()

    # going through all contributing samples for the process
    for idx, sample in enumerate(config["processes"][process]["samples"]):
        # loading ntuple files
        rdf = ROOT.RDataFrame(config["tree"], func.get_ntuples(config, sample))
        if func.rdf_is_empty(rdf):
            print("WARNING: Sample {} is empty. Skipping...".format(sample))
            continue

        # apply wanted event filters
        selection_conf = config["event_selection"]
        if "had_boostedtau_pt" in selection_conf:
            rdf = filters.had_boostedtau_pt_cut(rdf, config["channel"], selection_conf)
        if "had_boostedtau_eta" in selection_conf:
            rdf = filters.had_boostedtau_eta_cut(rdf, config["channel"], selection_conf)
        if "had_boostedtau_decay_mode" in selection_conf:
            rdf = filters.had_boostedtau_decay_mode_cut(rdf, config["channel"], selection_conf)
        if "had_boostedtau_id_antiEle" in selection_conf:
            rdf = filters.had_boostedtau_id_antiEle_cut(rdf, config["channel"], selection_conf)
        if "had_boostedtau_id_antiMu" in selection_conf:
            rdf = filters.had_boostedtau_id_antiMu_cut(rdf, config["channel"], selection_conf)
        if "trigger" in selection_conf:
            rdf = filters.boosted_trigger_cut(rdf, config["channel"])

        if process == "embedding":
            rdf = filters.emb_boostedtau_gen_match(rdf, config["channel"]) 

        # calculate event weights for plotting
        mc_weight_conf = config["mc_weights"]
        rdf = rdf.Define("weight", "1.")
        if process not in ["data", "embedding"]:
            if process == "DYjets":
                if "generator" in mc_weight_conf and not config["stitching"]:
                    rdf = weights.gen_weight(rdf, datasets[sample])
                elif "generator" in mc_weight_conf and config["stitching"]:
                    rdf = weights.stitching_weight(
                        rdf, config["era"], process, datasets[sample]
                    )
            elif process == "Wjets":
                if "generator" in mc_weight_conf and not config["stitching"]:
                    rdf = weights.gen_weight(rdf, datasets[sample])
                elif "generator" in mc_weight_conf and config["stitching"]:
                    rdf = weights.stitching_weight(
                        rdf, config["era"], process, datasets[sample]
                    )
            else:
                if "generator" in mc_weight_conf:
                    rdf = weights.gen_weight(rdf, datasets[sample])
            if "lumi" in mc_weight_conf:
                rdf = weights.lumi_weight(rdf, config["era"])
            if "pileup" in mc_weight_conf:
                rdf = weights.pileup_weight(rdf)
            if "boosted_lep_iso" in mc_weight_conf:
                rdf = weights.boosted_lep_iso_weight(rdf, config["channel"])
            if "boosted_lep_id" in mc_weight_conf:
                rdf = weights.boosted_lep_id_weight(rdf, config["channel"])
            if "had_boostedtau_id_antiMu" in mc_weight_conf:
                rdf = weights.boostedtau_id_antiMu_weight(rdf, config["channel"], selection_conf)
            if "had_boostedtau_id_antiEle" in mc_weight_conf:
                rdf = weights.boostedtau_id_antiEle_weight(
                    rdf, config["channel"], selection_conf
                )
            if "trigger" in mc_weight_conf:
                rdf = weights.trigger_weight(rdf, config["channel"])
            if "Z_pt_reweight" in mc_weight_conf:
                rdf = weights.Z_pt_reweight(rdf, process)
            if "Top_pt_reweight" in mc_weight_conf:
                rdf = weights.Top_pt_reweight(rdf, process)

        emb_weight_conf = config["emb_weights"]
        if process == "embedding":
            if "generator" in emb_weight_conf:
                rdf = weights.emb_gen_weight(rdf, config["channel"])
            if "boosted_lep_iso" in emb_weight_conf:
                rdf = weights.boosted_lep_iso_weight(rdf, config["channel"])
            if "boosted_lep_id" in emb_weight_conf:
                rdf = weights.boosted_lep_id_weight(rdf, config["channel"])
            if "trigger" in emb_weight_conf:
                rdf = weights.trigger_weight(rdf, config["channel"])

        # default values for some output variables which are not defined in data, embedding; will not be used in FF calculation
        if process == "data" or process == "embedding":
            rdf = rdf.Define("btag_weight", "1.")
            rdf = rdf.Define("btag_weight_boosted", "1.")
            for wp in tau_wps:
                weightname = "id_wgt_boostedtau_iso_" + wp + "_2"
                if weightname not in rdf.GetColumnNames():
                    rdf = rdf.Define(weightname, "1.")
            if config["channel"] == "tt":
                for wp in tau_wps:
                    weightname = "id_wgt_boostedtau_iso_" + wp + "_1"
                    if weightname not in rdf.GetColumnNames():
                        rdf = rdf.Define(weightname, "1.")
        # for data set gen_match to -1
        if process == "data":
            rdf = rdf.Define("boosted_gen_match_2", "-1.")
            if config["channel"] == "tt":
                rdf = rdf.Define("boosted_gen_match_1", "-1.")

        # calculate additional variables
        if config["channel"] == "et":
            rdf = rdf.Define(
                "no_extra_lep",
                "(extramuon_veto < 0.5) && (boosted_extraelec_veto < 0.5) && (dilepton_veto < 0.5)",
            )
        elif config["channel"] == "mt":
            rdf = rdf.Define(
                "no_extra_lep",
                "(boosted_extramuon_veto < 0.5) && (extraelec_veto < 0.5) && (dilepton_veto < 0.5)",
            )
        elif config["channel"] == "tt":
            rdf = rdf.Define(
                "no_extra_lep",
                "(extramuon_veto < 0.5) && (extraelec_veto < 0.5) ",
            )
        else:
            print(
                "Extra lepton veto: Such a channel is not defined: {}".format(
                    config["channel"]
                )
            )
        
        # Redefinitions for boosted tau pairs
        rdf = rdf.Redefine("btag_weight", "btag_weight_boosted")
        rdf = rdf.Redefine("njets", "njets_boosted")
        rdf = rdf.Redefine("nbtag", "nbtag_boosted")
        rdf = rdf.Redefine("metphi", "metphi_boosted")

        # splitting data frame based on the tau origin (genuine, jet fake, lepton fake)
        for tau_gen_mode in config["processes"][process]["tau_gen_modes"]:
            tmp_rdf = rdf
            if tau_gen_mode != "all":
                tmp_rdf = filters.boostedtau_origin_split(
                    tmp_rdf, config["channel"], tau_gen_mode
                )

            # redirecting C++ stdout for Report() to python stdout
            out = StringIO()
            with pipes(stdout=out, stderr=STDOUT):
                tmp_rdf.Report().Print()
            print(out.getvalue())
            print("-" * 50)

            tmp_file_name = func.get_output_name(
                output_path, process, tau_gen_mode, idx
            )
            # check for empty data frame -> only save/calculate if event number is not zero
            if tmp_rdf.Count().GetValue() != 0:
                print(
                    "The current data frame will be saved to {}".format(tmp_file_name)
                )
                cols = tmp_rdf.GetColumnNames()
                missing_cols = [x for x in output_feature if x not in cols]
                if len(missing_cols) != 0:
                    raise ValueError("Missing columns: {}".format(missing_cols))
                tmp_rdf.Snapshot(config["tree"], tmp_file_name, output_feature)
                print("-" * 50)
                process_file_dict[tau_gen_mode].append(tmp_file_name)
            else:
                print("No events left after filters. Data frame will not be saved.")
                print("-" * 50)

    # combining all files of a process and tau origin
    for tau_gen_mode in config["processes"][process]["tau_gen_modes"]:
        out_file_name = func.get_output_name(output_path, process, tau_gen_mode)
        # combining sample files to a single process file, if there are any
        if len(process_file_dict[tau_gen_mode]) != 0:
            sum_rdf = ROOT.RDataFrame(config["tree"], process_file_dict[tau_gen_mode])
            print(
                "The processed files for the {} process are concatenated. The data frame will be saved to {}".format(
                    process, out_file_name
                )
            )
            sum_rdf.Snapshot(config["tree"], out_file_name, output_feature)
            print("-" * 50)
        else:
            print(
                "No processed files for the {} process. An empty data frame will be saved to {}".format(
                    process, out_file_name
                )
            )
            sum_rdf.Snapshot(config["tree"], out_file_name, [])
            print("-" * 50)

        # delete not needed sample files after combination
        for rf in process_file_dict[tau_gen_mode]:
            os.remove(rf)
        print("-" * 50)


if __name__ == "__main__":
    args = parser.parse_args()

    # loading of the chosen config file
    if args.config_file is not None:
        with open(args.config_file, "r") as file:
            config = yaml.load(file, yaml.FullLoader)
    else:
        with open("configs/" + args.config + ".yaml", "r") as file:
            config = yaml.load(file, yaml.FullLoader)
    # loading general dataset info file for xsec and event number
    with open("datasets/datasets.yaml", "r") as file:
        datasets = yaml.load(file, yaml.FullLoader)

    # define output path for the preselected samples
    output_path = os.path.join(
        config["output_path"], "preselection", config["era"], config["channel"]
    )
    func.check_output_path(output_path)

    # start output logging
    sys.stdout = Logger(output_path + "/preselection.log")
    # these variables are no defined in et, mt ntuples
    if config["channel"] == "tt":
        output_feature.append("boosted_gen_match_1")
        for wp in tau_wps:
            output_feature.append("id_boostedtau_iso_" + wp + "_1")
            output_feature.append("id_wgt_boostedtau_iso_" + wp + "_1")

    # going through all wanted processes and run the preselection function with a pool of 8 workers
    args_list = [(process, config) for process in config["processes"]]
    # for args in args_list:
    #     run_preselection(args)
    with multiprocessing.Pool(
        processes=min(len(config["processes"]), int(args.nthreads))
    ) as pool:
        pool.map(run_preselection, args_list)

    # dumping config to output directory for documentation
    with open(output_path + "/config.yaml", "w") as config_file:
        yaml.dump(config, config_file, default_flow_style=False)