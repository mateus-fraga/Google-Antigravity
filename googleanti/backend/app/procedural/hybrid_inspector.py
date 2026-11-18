"""
Inspetor Geométrico Semântico (Vision LLM via Ollama local).

Consulta um modelo de visão local (padrão `llava`, configurável via `OLLAMA_VISION_MODEL`)
para inferir restrições geométricas estruturais de uma imagem 2D antes da etapa de
alinhamento PCA/inércia e corte estanque da base no `TripoSREngine`.

Em caso de indisponibilidade, timeout ou resposta inválida do Ollama, aplica fallback
seguro determinístico sem jamais abortar o job de reconstrução 3D.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from backend.app.config import settings

logger = logging.getLogger("ai_3d_studio.hybrid_inspector")

_VISION_PROMPT = (
    "Analyze the main 3D object in this image and return EXCLUSIVELY a strict JSON object "
    "with no markdown or extra text, containing exactly these three keys:\n"
    '{\n'
    '  "needs_flat_base": true or false (true if the object normally rests flat on a table/floor, e.g. vase, mug, statue, bottle, box, furniture),\n'
    '  "is_symmetrical": true or false (true if the object has a primary symmetry/upright axis, e.g. vase, bottle, pillar, bowl, goblet),\n'
    '  "primary_axis": "vertical" or "horizontal"\n'
    '}\n'
    "Return ONLY valid JSON."
)


class HybridInspector:
    """Inspetor geométrico baseado em Vision LLM local (Ollama) com fallback seguro."""

    DEFAULT_CONSTRAINTS: Dict[str, Any] = {
        "needs_flat_base": True,
        "is_symmetrical": True,
        "primary_axis": "vertical",
    }

    @classmethod
    def _default_copy(cls) -> Dict[str, Any]:
        return dict(cls.DEFAULT_CONSTRAINTS)

    @classmethod
    def _parse_and_validate_json(cls, raw_text: str) -> Dict[str, Any]:
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise ValueError("Resposta vazia do modelo Vision LLM.")

        cleaned = raw_text.strip()
        # Remover eventuais cercas markdown ```json ... ```
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
        if fence_match:
            cleaned = fence_match.group(1)
        elif not cleaned.startswith("{"):
            brace_match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
            if brace_match:
                cleaned = brace_match.group(0)

        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            raise ValueError("JSON retornado não é um objeto.")

        needs_flat_base = parsed.get("needs_flat_base")
        is_symmetrical = parsed.get("is_symmetrical")
        primary_axis = parsed.get("primary_axis")

        if not isinstance(needs_flat_base, bool):
            raise ValueError("Campo 'needs_flat_base' deve ser booleano.")
        if not isinstance(is_symmetrical, bool):
            raise ValueError("Campo 'is_symmetrical' deve ser booleano.")
        if not isinstance(primary_axis, str) or primary_axis.strip().lower() not in ("vertical", "horizontal"):
            raise ValueError("Campo 'primary_axis' deve ser 'vertical' ou 'horizontal'.")

        return {
            "needs_flat_base": needs_flat_base,
            "is_symmetrical": is_symmetrical,
            "primary_axis": primary_axis.strip().lower(),
        }

    @classmethod
    def inspect_image(
        cls,
        image_path: Path | str,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Consulta o modelo Vision configurado em `OLLAMA_VISION_MODEL` (`llava`) pedindo
        exclusivamente um JSON estrito com `needs_flat_base`, `is_symmetrical` e `primary_axis`.
        Nunca lança exceção em falhas de rede/timeout/JSON inválido: retorna `DEFAULT_CONSTRAINTS`.
        """
        resolved_model = (
            model
            or os.getenv("OLLAMA_VISION_MODEL")
            or getattr(settings, "OLLAMA_VISION_MODEL", "llava")
            or "llava"
        )
        resolved_url = (
            base_url
            or os.getenv("OLLAMA_BASE_URL")
            or getattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")
            or "http://127.0.0.1:11434"
        ).rstrip("/")
        resolved_timeout = float(
            timeout
            if timeout is not None
            else os.getenv("OLLAMA_TIMEOUT_SECONDS", getattr(settings, "OLLAMA_TIMEOUT_SECONDS", 15.0))
        )

        try:
            img_path = Path(image_path)
            if not img_path.exists() or not img_path.is_file():
                logger.warning("HybridInspector: imagem não encontrada em %s; usando fallback padrão.", img_path)
                return cls._default_copy()

            img_b64 = base64.b64encode(img_path.read_bytes()).decode("ascii")
            payload = {
                "model": resolved_model,
                "prompt": _VISION_PROMPT,
                "images": [img_b64],
                "format": "json",
                "stream": False,
                "options": {
                    "temperature": 0.0,
                },
            }

            response = httpx.post(
                f"{resolved_url}/api/generate",
                json=payload,
                timeout=resolved_timeout,
            )
            response.raise_for_status()

            body = response.json()
            raw_content = body.get("response", "") if isinstance(body, dict) else ""
            constraints = cls._parse_and_validate_json(raw_content)
            logger.info(
                "HybridInspector (%s): restrições inferidas=%s",
                resolved_model,
                constraints,
            )
            return constraints
        except Exception as exc:
            logger.warning(
                "HybridInspector: falha ao consultar Ollama (%s em %s): %s. Aplicando fallback padrão.",
                resolved_model,
                resolved_url,
                exc,
            )
            return cls._default_copy()
