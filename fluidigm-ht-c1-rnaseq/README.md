Description
-----------

This pipeline ... FIXME

All runtime variables including program versions etc. can be found in
`conf.yaml`


How to
------

- Run `fluidigm-ht-c1-rnaseq.py -h` to get basic usage information.
- If called correctly, jobs will be run on the cluster automatically
- Using `-v` is recommended to get some more information
- Should the pipeline 'crash', it can be restarted by simply running
  `bash run.sh` (for local mode) or `qsub run.sh` (for cluster mode).


Output
------

- The main log file is `./logs/snakemake.log`
- All output files can be found in `./out/`



