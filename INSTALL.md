# Installing and running BalteusBelt

BalteusBelt is a single-file, standard-library-only Python command line tool.
Running it needs **no** installation step: `python3 balteusbelt.py` is the whole
program. `install.sh` only adds the optional test runner.

## 1. Prerequisites (install these on the machine yourself)

* Python 3.8 or newer (`python3 --version`). Python 3.11 is what this project is
  developed and tested against.
* Nothing else. No compiler, no database, no service, no system package.

No environment variables are read, no config file is needed, and there is no
secret to set: a fresh checkout runs as-is.

## 2. Package manager

**pip**, driven by the committed `requirements.txt` pin
(`pytest==8.4.2`). There is no lockfile to match because the tool itself has no
runtime dependency; the pin exists so the test suite is reproducible.

If your Python is "externally managed" (PEP 668), create a virtualenv first:

```
python3 -m venv .venv
. .venv/bin/activate
```

## 3. Install the dependencies

```
bash install.sh
```

`install.sh` upgrades pip/setuptools/wheel, installs `requirements.txt`, checks
that `balteusbelt.py` imports and runs, and then **exits**. It never starts a
long-running process and never touches the system package manager.

## 4. Seed data

There is **no seed step**. The four built-in patterns (`oseberg`, `birka`,
`hedeby`, `mammen`) are compiled into `balteusbelt.py`, and `examples/` ships two
ready-to-run pattern files. Nothing is written to disk at any point.

## 5. Run it

```
python3 balteusbelt.py --help
python3 balteusbelt.py
```

`bash demo.sh` runs a full non-interactive tour (catalogue, grid, swaps, dye
counts, both file formats and the error contract).

## 6. Run the tests

```
python3 -m pytest
```

The suite lives in `tests/test_balteusbelt.py` and needs no network, no fixtures
outside the repository and no interactive input.
