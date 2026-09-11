THIS IS NOT VERIFIED REAL AGRONOMIC DATA.

Purpose: provide a fully deterministic synthetic dataset that supports the same
ingestion, alignment, diagnostics, and identifiability pathway as the future real
agronomic dataset. The dataset remains synthetic and must never be interpreted as a
measured or validated dataset.

Dataset id: synthetic_real_data_substitute
Provenance: SIMULATED_REAL_DATA_SUBSTITUTE
Source type: synthetic
Generation: deterministic SimulationClock-driven synthetic generation
Crops: tomato, lettuce, pepper, grape, peach, plum, apple
Plots: plot_12010, plot_14705, plot_30412, plot_40811, plot_20500, plot_61200
Environments: GREENHOUSE, OUTDOOR
Use: replace the source file with a real dataset while preserving the same `ObservationDataset`
contract and pipeline.
