from typing import Callable, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn

try:
    from torchmcubes import marching_cubes as _torchmcubes_fn
except ImportError:
    _torchmcubes_fn = None


def _pymcubes_fallback(vol: torch.Tensor, thresh: float) -> Tuple[torch.Tensor, torch.Tensor]:
    """
    Fallback automático para PyMCubes (`mcubes.marching_cubes`) ou `scikit-image`
    (`skimage.measure.marching_cubes`) quando `torchmcubes` não está compilado no ambiente.
    Mantém a mesma convenção de eixos (x, y, z) e orientação de faces esperada por
    `MarchingCubeHelper.forward`.
    """
    vol_np = np.asarray(vol.detach().cpu().numpy(), dtype=np.float32)
    try:
        import mcubes
        verts, faces = mcubes.marching_cubes(vol_np, float(thresh))
    except ImportError:
        from skimage import measure
        verts, faces, _, _ = measure.marching_cubes(vol_np, level=float(thresh))

    # PyMCubes / skimage retornam vértices em (axis0=z, axis1=y, axis2=x); inverter para (x, y, z)
    # pois `MarchingCubeHelper.forward` aplica `v_pos = v_pos[..., [2, 1, 0]]` em seguida.
    verts_xyz = np.ascontiguousarray(verts[:, [2, 1, 0]], dtype=np.float32)
    faces_fixed = np.ascontiguousarray(faces.astype(np.int64))
    return (
        torch.from_numpy(verts_xyz).to(device=vol.device, dtype=torch.float32),
        torch.from_numpy(faces_fixed).to(device=vol.device, dtype=torch.long),
    )


marching_cubes: Callable = _torchmcubes_fn if _torchmcubes_fn is not None else _pymcubes_fallback


class IsosurfaceHelper(nn.Module):
    points_range: Tuple[float, float] = (0, 1)

    @property
    def grid_vertices(self) -> torch.FloatTensor:
        raise NotImplementedError


class MarchingCubeHelper(IsosurfaceHelper):
    def __init__(self, resolution: int) -> None:
        super().__init__()
        self.resolution = resolution
        self.mc_func: Callable = marching_cubes
        self._grid_vertices: Optional[torch.FloatTensor] = None

    @property
    def grid_vertices(self) -> torch.FloatTensor:
        if self._grid_vertices is None:
            # keep the vertices on CPU so that we can support very large resolution
            x, y, z = (
                torch.linspace(*self.points_range, self.resolution),
                torch.linspace(*self.points_range, self.resolution),
                torch.linspace(*self.points_range, self.resolution),
            )
            x, y, z = torch.meshgrid(x, y, z, indexing="ij")
            verts = torch.cat(
                [x.reshape(-1, 1), y.reshape(-1, 1), z.reshape(-1, 1)], dim=-1
            ).reshape(-1, 3)
            self._grid_vertices = verts
        return self._grid_vertices

    def forward(
        self,
        level: torch.FloatTensor,
    ) -> Tuple[torch.FloatTensor, torch.LongTensor]:
        level = -level.view(self.resolution, self.resolution, self.resolution)
        try:
            v_pos, t_pos_idx = self.mc_func(level.detach(), 0.0)
        except AttributeError:
            print("torchmcubes was not compiled with CUDA support, use CPU version instead.")
            v_pos, t_pos_idx = self.mc_func(level.detach().cpu(), 0.0)
        v_pos = v_pos[..., [2, 1, 0]]
        v_pos = v_pos / (self.resolution - 1.0)
        return v_pos.to(level.device), t_pos_idx.to(level.device)
