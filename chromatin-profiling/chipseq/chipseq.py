#!/usr/bin/env python3
"""{PIPELINE_NAME} pipeline (version: {PIPELINE_VERSION}): creates
pipeline-specific config files to given output directory and runs the
pipeline (unless otherwise requested).
"""
# generic usage {PIPELINE_NAME} and {PIPELINE_VERSION} replaced while
# printing usage

#--- standard library imports
#
import sys
import os
import logging

#--- third-party imports
#
import yaml

#--- project specific imports
#
# add lib dir for this pipeline installation to PYTHONPATH
LIB_PATH = os.path.abspath(
    os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "lib"))
if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)
from readunits import get_samples_and_readunits_from_cfgfile
from readunits import get_readunits_from_args
from pipelines import get_pipeline_version
from pipelines import PipelineHandler
from pipelines import logger as aux_logger
from pipelines import get_cluster_cfgfile
from pipelines import default_argparser
import configargparse


__author__ = "Andreas Wilm"
__email__ = "wilma@gis.a-star.edu.sg"
__copyright__ = "2016 Genome Institute of Singapore"
__license__ = "The MIT License (MIT)"


# only dump() and following do not automatically create aliases
yaml.Dumper.ignore_aliases = lambda *args: True


PIPELINE_BASEDIR = os.path.dirname(sys.argv[0])
CFG_DIR = os.path.join(PIPELINE_BASEDIR, "cfg")

# same as folder name. also used for cluster job names
PIPELINE_NAME = "chipseq"

MARK_DUPS = True

# global logger
logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    '[{asctime}] {levelname:8s} {filename} {message}', style='{'))
logger.addHandler(handler)


def main():
    """main function
    """

    default_parser = default_argparser(CFG_DIR)
    parser = configargparse.ArgumentParser(description=__doc__.format(
        PIPELINE_NAME=PIPELINE_NAME, PIPELINE_VERSION=get_pipeline_version()),
                                     parents=[default_parser])

    parser._optionals.title = "Arguments"
    # pipeline specific args
    parser.add_argument("--control-fq1", nargs="+",
                        help="Control FastQ file/s (gzip only)."
                        " Multiple input files supported (auto-sorted)."
                        " Note: each file (or pair) gets a unique read-group id."
                        " Collides with --sample-cfg.")
    parser.add_argument('--control-fq2', nargs="+",
                        help="Control FastQ file/s (if paired) (gzip only). See also --control-fq1")
    parser.add_argument("--treatment-fq1", nargs="+",
                        help="Treatment FastQ file/s (gzip only)."
                        " Multiple input files supported (auto-sorted)."
                        " Note: each file (or pair) gets a unique read-group id."
                        " Collides with --sample-cfg.")
    parser.add_argument('--treatment-fq2', nargs="+",
                        help="Treatment FastQ file/s (if paired) (gzip only). See also --treatment-fq1")
    parser.add_argument('--control-bam',
                        help="Advanced: Injects control BAM (overwrites control-fq options)."
                        " WARNING: reference and postprocessing need to match pipeline requirements")
    parser.add_argument('--treatment-bam',
                        help="Advanced: Injects treatment BAM (overwrites treatment-fq options)."
                        " WARNING: reference and postprocessing need to match pipeline requirements")
    choices = ['bwa-aln', 'bwa-mem']
    default = choices[0]
    parser.add_argument('--mapper', default=default, choices=choices,
                        help="Mapper to use. One of {}. Default {}".format(",".join(choices), default))

    choices = ['TF', 'histone-narrow', 'histone-broad']#, 'open-chromatin']
    parser.add_argument('-t', '--peak-type', required=True, choices=choices,
                        help="Peak type. One of {}".format(",".join(choices)))
    parser.add_argument('--skip-macs2', action='store_true',
                        help="Don't run MACS2")
    parser.add_argument('--skip-dfilter', action='store_true',
                        help="Don't run DFilter")

    args = parser.parse_args()

    # Repeateable -v and -q for setting logging level.
    # See https://www.reddit.com/r/Python/comments/3nctlm/what_python_tools_should_i_be_using_on_every/
    # and https://gist.github.com/andreas-wilm/b6031a84a33e652680d4
    # script -vv -> DEBUG
    # script -v -> INFO
    # script -> WARNING
    # script -q -> ERROR
    # script -qq -> CRITICAL
    # script -qqq -> no logging at all
    logger.setLevel(logging.WARN + 10*args.quiet - 10*args.verbose)
    aux_logger.setLevel(logging.WARN + 10*args.quiet - 10*args.verbose)

    if os.path.exists(args.outdir):
        logger.fatal("Output directory %s already exists", args.outdir)
        sys.exit(1)


    # samples is a dictionary with sample names as key (mostly just
    # one) and readunit keys as value. readunits is a dict with
    # readunits (think: fastq pairs with attributes) as value
    if args.sample_cfg:
        if any([args.control_fq1, args.control_fq2, args.treatment_fq1, args.treatment_fq2,
                args.control_bam, args.treatment_bam]):
            logger.fatal("Config file overrides fastq and sample input arguments."
                         " Use one or the other")
            sys.exit(1)
            if not os.path.exists(args.sample_cfg):
                logger.fatal("Config file %s does not exist", args.sample_cfg)
                sys.exit(1)
        samples, readunits = get_samples_and_readunits_from_cfgfile(args.sample_cfg)
    else:
        samples = dict()

        if args.control_bam:
            control_readunits = dict()
            samples["control"] = []
            assert os.path.exists(args.control_bam)
        else:
            if not all([args.control_fq1, args.treatment_fq1]):
                logger.fatal("Need at least fq1 and sample without config file")
                sys.exit(1)
            control_readunits = get_readunits_from_args(args.control_fq1, args.control_fq2)
            samples["control"] = list(control_readunits.keys())

        if args.treatment_bam:
            treatment_readunits = dict()
            samples["treatment"] = []
            assert os.path.exists(args.treatment_bam)
        else:
            treatment_readunits = get_readunits_from_args(args.treatment_fq1, args.treatment_fq2)
            samples["treatment"] = list(treatment_readunits.keys())

        readunits = dict(control_readunits)
        readunits.update(treatment_readunits)

    assert sorted(samples) == sorted(["control", "treatment"])


    # turn arguments into cfg_dict that gets merged into pipeline config
    #
    cfg_dict = dict()
    cfg_dict['readunits'] = readunits
    cfg_dict['samples'] = samples

    # either paired end or not, but no mix allows
    if all([ru.get('fq2') for ru in readunits.values()]):
        cfg_dict['paired_end'] = True
    elif not any([ru.get('fq2') for ru in readunits.values()]):
        cfg_dict['paired_end'] = False
    else:
        logger.fatal("Mixed paired-end and single-end not allowed")
        sys.exit(1)
    cfg_dict['peak_type'] = args.peak_type
    cfg_dict['mapper'] = args.mapper
    cfg_dict['skip_macs2'] = args.skip_macs2
    cfg_dict['skip_dfilter'] = args.skip_dfilter

    pipeline_handler = PipelineHandler(
        PIPELINE_NAME, PIPELINE_BASEDIR,
        args, cfg_dict,
        cluster_cfgfile=get_cluster_cfgfile(CFG_DIR))
    pipeline_handler.setup_env()

    if args.control_bam or args.treatment_bam:
        raise NotImplementedError("BAM injection not implemented yet")

    pipeline_handler.submit(args.no_run)


if __name__ == "__main__":
    main()
