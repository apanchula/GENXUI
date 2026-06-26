# GenXUI

A lightweight Streamlit interface for running and exploring [GenX.jl](https://github.com/GenXProject/GenX.jl) capacity expansion models.

Built for single-case, single-zone models as a development and learning tool. Not intended for production multi-zone or multi-period workflows.

---

## Features

| Page | Description |
|---|---|
| **Runner** | Select a case, launch Julia, and stream terminal output live. Displays a system resource and cost summary before each run. |
| **Inputs** | Browse and edit `resources/`, `system/`, `policies/`, and `settings/` files. Supports CSV tables and `.yml` settings with inline save. |
| **Results** | Interactive results dashboard — LCOE table, capacity chart, supply-to-load mix, cost breakdown, and storage metrics. Reads GenX output CSVs directly (no Julia re-run needed). |

---

## Prerequisites

### 1. Julia

Download and install Julia (≥ 1.9) from [julialang.org](https://julialang.org/downloads/).

Verify installation:
```bash
julia --version
```

Julia must be on your system `PATH` so the Runner page can invoke it.

### 2. GenX.jl

Clone the GenX repository and instantiate the Julia environment:

```bash
git clone https://github.com/GenXProject/GenX.jl.git
cd GenX.jl
julia --project=. -e "import Pkg; Pkg.instantiate()"
```

The first instantiation downloads all Julia dependencies and may take several minutes.

Your GenXUI folder should sit alongside (not inside) the `GenX.jl` directory:

```
parent/
├── GenX.jl/          # GenX source + cases
│   ├── MyCase/
│   │   ├── Run.jl
│   │   ├── resources/
│   │   ├── system/
│   │   └── settings/
│   └── ...
└── GenXUI/           # this repo
    ├── app.py
    └── pages/
```

GenXUI auto-discovers cases by scanning `../GenX.jl/` for directories that contain a `Run.jl` file.

### 3. Python

Python ≥ 3.10 is required (uses `X | Y` union type hints).

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Running the App

From the `GenXUI/` directory:

```bash
python -m streamlit run app.py
```

Then open [http://localhost:8501](http://localhost:8501) in your browser.

---

## Case Setup

Each GenX case must follow the standard GenX input structure:

```
MyCase/
├── Run.jl
├── resources/
│   ├── Thermal.csv
│   ├── Vre.csv
│   ├── Storage.csv
│   └── Vre_stor.csv
├── system/
│   ├── Demand_data.csv
│   ├── Generators_variability.csv
│   └── Fuels_data.csv
├── policies/
└── settings/
    └── genx_settings.yml
```

See the [GenX documentation](https://genxproject.github.io/GenX.jl/stable/User_Guide/model_input/) for full input file specifications.

---

## Results

After a successful run, GenX writes output CSVs to `MyCase/results/`. The Results page reads these directly and displays:

- **LCOE per resource** — with annual cost, generation, supply to load, and curtailment
- **Capacity built** — MW and MWh by resource
- **Supply to load mix** — donut chart by resource
- **Cost breakdown** — investment, fixed O&M, variable O&M, fuel, and startup costs
- **Storage metrics** — power, energy, and duration

---

## Limitations

- Single case at a time (no multi-case comparison)
- Single zone only — no transmission or network expansion
- No multi-stage investment support
- Julia startup latency (~60–90 s) before output appears in the terminal

---

## Attribution

Developed by **Alex Panchula** with [Claude Code](https://claude.ai/code) (Anthropic).

GenX is developed and maintained by the [GenX Project](https://github.com/GenXProject/GenX.jl) team.
