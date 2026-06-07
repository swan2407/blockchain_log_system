# Experiment Results

`run_experiment.py` appends timestamped quantitative results to
`experiments/experiment_results.csv` by default.

The CSV uses one stable superset header so normal latency, HMAC performance,
tamper detection, recovery, and C-client integration results can be collected
in the same file. Fields that do not apply to a specific experiment are left
empty.

The generated `experiment_results.csv` file may be deleted between experiment
runs when a fresh result set is required.
