# Plano de Instalação — Motor LRM Nativo (`TripoSR`)

Este guia descreve a instalação das dependências de inferência neural local do **TripoSR (`stabilityai/TripoSR`)** no ambiente virtual do backend (`backend/venv`), otimizado para GPUs NVIDIA modernas (incluindo **RTX 5070 / arquitetura Blackwell `sm_120`**).

---

## 1. Arquitetura `tsr` e Marching Cubes Já Integrados no Projeto

Para evitar falhas de compilação C++/CUDA do `torchmcubes` (como `metadata-generation-failed` por isolamento de build do `pip` ou ausência de `nvcc` no sistema) e a ausência de `setup.py` no repositório original `VAST-AI-Research/TripoSR`:

1. **A arquitetura oficial `tsr` já está embarcada diretamente no projeto** em `backend/app/lrm/tsr/`.
2. **O extrator de iso-superfície (`backend/app/lrm/tsr/models/isosurface.py`) possui fallback automático para `PyMCubes` (`mcubes`)**, que já possui wheels pré-compiladas para todas as plataformas e já está instalado no `backend/venv` (`PyMCubes 0.1.6`), mantendo toda a inferência neural (DINOv2 + Transformer Triplane + NeRF Renderer) acelerada via PyTorch/CUDA.

---

## 2. Instalação em Nova Máquina (após `git clone`)

Ao clonar o projeto em outra máquina, você **não precisa** compilar `torchmcubes` nem clonar o repositório do `TripoSR` separadamente. Basta instalar o PyTorch com CUDA e o `requirements.txt`:

```bash
cd /home/mateusfragag/Documents/projects/googleanti
source backend/venv/bin/activate

# 1. Instalar PyTorch com suporte CUDA 12.8 (RTX 5070 / Blackwell)
pip install --upgrade pip setuptools wheel
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 2. Instalar as demais dependências do backend (incluindo PyMCubes, rembg, transformers, einops)
pip install -r backend/requirements.txt
```

*(Opcional: caso deseje compilar o `torchmcubes` nativo em uma máquina que possua `cuda-toolkit` / `nvcc` completo instalado em `/usr/local/cuda`, é obrigatório passar a flag `--no-build-isolation`: `pip install --no-build-isolation git+https://github.com/tatsy/torchmcubes.git`).*
