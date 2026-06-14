#!/usr/bin/env bash
# Восстановление OCC (pythonocc-core) для Sinlex API и анализа STEP.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONDA_PREFIX="${ROOT}/.conda"
ENV_NAME="${SINLEX_CONDA_ENV:-sinlex}"

if [[ ! -x "${CONDA_PREFIX}/bin/conda" ]]; then
  echo "Installing Miniconda to ${CONDA_PREFIX}..."
  wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh
  bash /tmp/miniconda.sh -b -p "${CONDA_PREFIX}"
  rm -f /tmp/miniconda.sh
fi

CONDA="${CONDA_PREFIX}/bin/conda"
"${CONDA}" tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main 2>/dev/null || true
"${CONDA}" tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r 2>/dev/null || true

if ! "${CONDA}" env list | awk '{print $1}' | grep -qx "${ENV_NAME}"; then
  echo "Creating conda env ${ENV_NAME} with pythonocc-core..."
  "${CONDA}" create -y -n "${ENV_NAME}" -c conda-forge python=3.10 pythonocc-core=7.8.1.1 numpy pip
fi

PY="${CONDA_PREFIX}/envs/${ENV_NAME}/bin/python"
"${PY}" -m pip install -q -r "${ROOT}/requirements.txt" scipy rtree

"${PY}" -c "from OCC.Core.STEPControl import STEPControl_Reader; print('OCC OK')"
echo "Python for services: ${PY}"
echo "Restart: systemctl restart sinlex-server sinlex-streamlit"
