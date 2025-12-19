#!/bin/bash
export PYTHONPATH="src:${PYTHONPATH}"
poetry run behave
