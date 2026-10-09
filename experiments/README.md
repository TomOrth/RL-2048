# Experiments

This directory is reserved for the SFT and GRPO experiments and their evaluation. The repository currently implements the 2048 game, web interface, and model connector; training pipelines have not been added.

As experiments are implemented, organize them into `sft/`, `grpo/`, `evaluation/`, and `configs/`. Maintain separate dependency files and environments for Mac training, CUDA training, and the lightweight game app. Reuse `backend/app/engine.py` for game rules, with an explicit import or packaging arrangement rather than duplicating the rules.

Version prompts, rewards, configurations, dataset manifests, and evaluation seed sets. For each run, record the Git commit, model and adapter revisions, dataset version, random seeds, decoding constraints, thinking settings, and token limits. Use the same evaluation setup for the base, SFT, and SFT+GRPO models.

Generated `data/`, `datasets/`, `artifacts/`, `checkpoints/`, `runs/`, and model weight files are ignored by Git. Keep large artifacts in local or external storage and commit their manifests or locations alongside experiment configuration.
