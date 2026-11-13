import re
import uuid
from typing import Dict, Any, List, Optional, Tuple
import trimesh

from backend.app.schemas.geometry import (
    Component,
    Transformation,
    MaterialDef,
    IntermediateObjectRepresentation,
    ObjectCategory,
    ObjectPurpose,
    GenerationStrategy,
    MIN_DIMENSION,
    MAX_DIMENSION,
    MIN_GEAR_TEETH,
    MAX_GEAR_TEETH,
)
from backend.app.procedural.engine import ProceduralGenerator, _NAMED_COLORS_HEX


class TextTo3DGenerator:
    """
    Bloco 6 (Task 6.3): Interpretador semântico determinístico Text-to-3D (PT-BR e EN).
    Converte descrições em linguagem natural (com medidas explícitas em m/cm/mm, número de dentes,
    cores/materiais e estruturas simples ou compostas) em uma instância validada de
    `IntermediateObjectRepresentation` (IOR) e sintetiza a malha 3D unificada em convenção Y-up
    via `ProceduralGenerator.generate_from_ir`.
    """

    MAX_PROMPT_LENGTH: int = 2000

    # Mapeamento de palavras de cor (incluindo flexões de gênero em PT-BR) para hexadecimal
    _COLOR_KEYWORDS: List[Tuple[str, str, bool]] = [
        ("dourado", "#d4af37", True),
        ("dourada", "#d4af37", True),
        ("ouro", "#d4af37", True),
        ("gold", "#d4af37", True),
        ("golden", "#d4af37", True),
        ("prateado", "#c0c0c0", True),
        ("prateada", "#c0c0c0", True),
        ("prata", "#c0c0c0", True),
        ("silver", "#c0c0c0", True),
        ("metalico", "#94a3b8", True),
        ("metálico", "#94a3b8", True),
        ("metalica", "#94a3b8", True),
        ("metálica", "#94a3b8", True),
        ("metallic", "#94a3b8", True),
        ("aco", "#94a3b8", True),
        ("aço", "#94a3b8", True),
        ("steel", "#94a3b8", True),
        ("bronze", "#cd7f32", True),
        ("cobre", "#b87333", True),
        ("copper", "#b87333", True),
        ("vermelho", "#ef4444", False),
        ("vermelha", "#ef4444", False),
        ("red", "#ef4444", False),
        ("azul", "#3b82f6", False),
        ("blue", "#3b82f6", False),
        ("verde", "#22c55e", False),
        ("green", "#22c55e", False),
        ("amarelo", "#eab308", False),
        ("amarela", "#eab308", False),
        ("yellow", "#eab308", False),
        ("laranja", "#f97316", False),
        ("orange", "#f97316", False),
        ("roxo", "#a855f7", False),
        ("roxa", "#a855f7", False),
        ("purple", "#a855f7", False),
        ("madeira", "#8b5a2b", False),
        ("marrom", "#8b5a2b", False),
        ("wood", "#8b5a2b", False),
        ("wooden", "#8b5a2b", False),
        ("brown", "#8b5a2b", False),
        ("preto", "#1f2937", False),
        ("preta", "#1f2937", False),
        ("black", "#1f2937", False),
        ("branco", "#f8fafc", False),
        ("branca", "#f8fafc", False),
        ("white", "#f8fafc", False),
        ("ciano", "#06b6d4", False),
        ("cyan", "#06b6d4", False),
        ("cinza", "#888888", False),
        ("gray", "#888888", False),
        ("grey", "#888888", False),
    ]

    _UNIT_PATTERN = r"(?:mm|mil[ií]metros?|millimeters?|cm|cent[ií]metros?|centimeters?|m|metros?|meters?)"

    @classmethod
    def validate_prompt(cls, prompt: Any) -> str:
        """
        Valida o prompt de entrada rejeitando valores não textuais, vazios, excessivamente longos
        (> 2000 caracteres) ou contendo dimensões negativas/nulas explícitas.
        """
        if not isinstance(prompt, str):
            raise ValueError("O prompt deve ser uma string de texto válida.")
        cleaned = prompt.strip()
        if not cleaned:
            raise ValueError("O prompt textual para geração Text-to-3D não pode ser vazio.")
        if len(cleaned) > cls.MAX_PROMPT_LENGTH:
            raise ValueError(
                f"O prompt excede o tamanho máximo permitido de {cls.MAX_PROMPT_LENGTH} caracteres "
                f"(recebido: {len(cleaned)} caracteres)."
            )

        lower = cleaned.lower()

        # Detectar valores numéricos negativos associados a medidas ou unidades (sem confundir hífens em palavras como 'text-to-3d')
        negative_measure_regex = re.compile(
            r"(?:^|[\s:=(\[,])-\s*\d+(?:[.,]\d+)?\s*(?:mm|cm|m|metros?|cent[ií]metros?|mil[ií]metros?|dentes|teeth)?\b"
        )
        if negative_measure_regex.search(lower):
            raise ValueError(
                "Dimensões negativas não são permitidas no prompt Text-to-3D. Informe apenas medidas estritamente positivas."
            )

        # Detectar medida zero explícita com unidade ou palavra-chave dimensional (exceto furo/bore)
        zero_unit_regex = re.compile(
            r"(?:^|[\s:=(\[,])0+(?:[.,]0+)?\s*(?:mm|cm|m|metros?|cent[ií]metros?|mil[ií]metros?|dentes|teeth)\b"
        )
        if zero_unit_regex.search(lower):
            raise ValueError(
                "Dimensões iguais a zero não são permitidas no prompt Text-to-3D. Informe medidas maiores que zero."
            )

        zero_keyword_regex = re.compile(
            r"\b(?:raio|radius|altura|height|largura|width|profundidade|depth|espessura|thickness|di[aâ]metro|diameter|dentes|teeth)"
            r"\s*(?:de|of|=|:)?\s*0+(?:[.,]0+)?\b"
        )
        if zero_keyword_regex.search(lower):
            raise ValueError(
                "Dimensões iguais a zero não são permitidas no prompt Text-to-3D. Informe medidas maiores que zero."
            )

        return cleaned

    @classmethod
    def _convert_to_meters(cls, number_str: str, unit_str: Optional[str]) -> float:
        val = float(number_str.replace(",", "."))
        if val <= 0.0:
            raise ValueError(f"As medidas geométricas extraídas do prompt devem ser positivas (recebido: {val}).")
        unit = (unit_str or "m").strip().lower()
        if unit.startswith("mm") or unit.startswith("mil"):
            meters = val * 0.001
        elif unit.startswith("cm") or unit.startswith("cent"):
            meters = val * 0.01
        else:
            meters = val * 1.0

        if meters < MIN_DIMENSION or meters > MAX_DIMENSION:
            raise ValueError(
                f"A medida convertida ({meters}m) está fora dos limites seguros [{MIN_DIMENSION}, {MAX_DIMENSION}] metros."
            )
        return round(meters, 6)

    @classmethod
    def _extract_named_measure(cls, text: str, keywords_pattern: str) -> Optional[float]:
        """
        Busca um valor dimensional tanto no formato:
          1. '<keyword> [de/of/:/=] <num> [unit]' (ex.: 'raio externo de 1.2m', 'altura 75cm')
          2. '<num> <unit> de <keyword>' (ex.: '75cm de altura', '1.5m de largura')
        """
        # Padrão 1: Palavra-chave antes do número
        pat_after = re.compile(
            rf"\b(?:{keywords_pattern})\s*(?:de|of|com|with|=|:)?\s*(\d+(?:[.,]\d+)?)\s*({cls._UNIT_PATTERN})?\b",
            re.IGNORECASE,
        )
        m1 = pat_after.search(text)
        if m1:
            return cls._convert_to_meters(m1.group(1), m1.group(2))

        # Padrão 2: Número + unidade antes de 'de <palavra-chave>'
        pat_before = re.compile(
            rf"\b(\d+(?:[.,]\d+)?)\s*({cls._UNIT_PATTERN})?\s+(?:de|of)\s+(?:{keywords_pattern})\b",
            re.IGNORECASE,
        )
        m2 = pat_before.search(text)
        if m2:
            return cls._convert_to_meters(m2.group(1), m2.group(2))

        return None

    @classmethod
    def _extract_dimensions_and_counts(cls, text: str) -> Dict[str, Any]:
        extracted: Dict[str, Any] = {}
        lower = text.lower()

        # 1. Padrões multiplicativos 2D / 3D: ex. '1.5m x 0.8m' ou '2m x 1m x 0.5m'
        mult_regex = re.compile(
            rf"\b(\d+(?:[.,]\d+)?)\s*({cls._UNIT_PATTERN})?\s*(?:x|por|by|\*)\s*"
            rf"(\d+(?:[.,]\d+)?)\s*({cls._UNIT_PATTERN})?"
            rf"(?:\s*(?:x|por|by|\*)\s*(\d+(?:[.,]\d+)?)\s*({cls._UNIT_PATTERN})?)?\b",
            re.IGNORECASE,
        )
        m_mult = mult_regex.search(lower)
        if m_mult:
            v1, u1, v2, u2, v3, u3 = m_mult.groups()
            # Se u1 foi omitido mas u2 foi informado (ex.: '120 x 80 cm'), herdar u2 quando v1 >= 5
            eff_u1 = u1 or (u2 if (u2 and float(v1.replace(",", ".")) >= 5.0) else "m")
            eff_u2 = u2 or u1 or "m"
            extracted["width"] = cls._convert_to_meters(v1, eff_u1)
            extracted["depth"] = cls._convert_to_meters(v2, eff_u2)
            if v3 is not None:
                eff_u3 = u3 or eff_u2
                extracted["height"] = cls._convert_to_meters(v3, eff_u3)

        # 2. Medidas nomeadas explícitas (sobrescrevem ou complementam)
        h_val = cls._extract_named_measure(lower, r"altura|height|alto|tall")
        if h_val is not None:
            extracted["height"] = h_val

        w_val = cls._extract_named_measure(lower, r"largura|width|largo|wide")
        if w_val is not None:
            extracted["width"] = w_val

        d_val = cls._extract_named_measure(lower, r"profundidade|depth|comprimento|length|fundo")
        if d_val is not None:
            extracted["depth"] = d_val

        outer_r = cls._extract_named_measure(lower, r"raio\s+externo|outer\s+radius|raio\s+maior|major\s+radius")
        if outer_r is not None:
            extracted["outer_radius"] = outer_r

        inner_r = cls._extract_named_measure(lower, r"raio\s+interno|inner\s+radius|raio\s+menor|minor\s+radius")
        if inner_r is not None:
            extracted["inner_radius"] = inner_r

        bore_r = cls._extract_named_measure(lower, r"raio\s+do\s+furo|furo\s+central|bore\s+radius|furo|bore")
        if bore_r is not None:
            extracted["bore_radius"] = bore_r

        # Raio genérico (quando não seguido de externo/interno/do furo)
        generic_r_after = re.compile(
            rf"\b(?:raio|radius)\s+(?!externo|interno|maior|menor|do\s+furo)(?:de\s+|of\s+|=|:)?(\d+(?:[.,]\d+)?)\s*({cls._UNIT_PATTERN})?\b",
            re.IGNORECASE,
        )
        m_r = generic_r_after.search(lower)
        if m_r:
            extracted["radius"] = cls._convert_to_meters(m_r.group(1), m_r.group(2))
        else:
            generic_r_before = re.compile(
                rf"\b(\d+(?:[.,]\d+)?)\s*({cls._UNIT_PATTERN})?\s+(?:de\s+|of\s+)(?:raio|radius)\b",
                re.IGNORECASE,
            )
            m_rb = generic_r_before.search(lower)
            if m_rb:
                extracted["radius"] = cls._convert_to_meters(m_rb.group(1), m_rb.group(2))

        diam_val = cls._extract_named_measure(lower, r"di[aâ]metro|diameter")
        if diam_val is not None and "radius" not in extracted:
            extracted["diameter"] = diam_val
            extracted["radius"] = round(diam_val / 2.0, 6)

        top_t = cls._extract_named_measure(lower, r"espessura\s+do\s+tampo|top\s+thickness")
        if top_t is not None:
            extracted["top_thickness"] = top_t

        leg_t = cls._extract_named_measure(lower, r"espessura\s+das?\s+pernas?|leg\s+thickness")
        if leg_t is not None:
            extracted["leg_thickness"] = leg_t

        thick_val = cls._extract_named_measure(lower, r"espessura|thickness")
        if thick_val is not None:
            extracted["thickness"] = thick_val

        # 3. Contagem de dentes para engrenagens
        teeth_match = re.search(r"\b(\d+)\s*(?:dentes|dente|teeth|tooth)\b", lower)
        if not teeth_match:
            teeth_match = re.search(r"\b(?:dentes|teeth)\s*(?:de|=|:)?\s*(\d+)\b", lower)
        if teeth_match:
            t_count = int(teeth_match.group(1))
            if t_count < MIN_GEAR_TEETH or t_count > MAX_GEAR_TEETH:
                raise ValueError(
                    f"Quantidade de dentes ({t_count}) fora dos limites permitidos [{MIN_GEAR_TEETH}, {MAX_GEAR_TEETH}]."
                )
            extracted["num_teeth"] = t_count

        return extracted

    @classmethod
    def _extract_material(cls, text: str, default_color: str = "#3b82f6", default_metallic: bool = False) -> Tuple[MaterialDef, str]:
        lower = text.lower()
        detected_color_hex = default_color
        detected_color_name = "default"
        is_metallic = default_metallic or bool(
            re.search(r"\b(?:met[aá]lic[oa]|metallic|a[cç]o|steel|ferro|iron|alum[ií]nio|aluminum)\b", lower)
        )

        # Verificar código hexadecimal explícito (#RRGGBB)
        hex_match = re.search(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", text)
        if hex_match:
            raw_hex = hex_match.group(0).lower()
            if len(raw_hex) == 4:
                raw_hex = "#" + "".join(c * 2 for c in raw_hex[1:])
            detected_color_hex = raw_hex
            detected_color_name = raw_hex
        else:
            for kw, hex_val, kw_metallic in cls._COLOR_KEYWORDS:
                if re.search(rf"\b{re.escape(kw)}\b", lower):
                    detected_color_hex = hex_val
                    detected_color_name = kw
                    if kw_metallic:
                        is_metallic = True
                    break

        roughness = 0.25 if is_metallic else 0.55
        metalness = 0.85 if is_metallic else 0.15
        mat = MaterialDef(
            color=detected_color_hex,
            base_color=detected_color_hex,
            roughness=roughness,
            metalness=metalness,
            name=f"Material_{detected_color_name}",
        )
        return mat, detected_color_name

    @classmethod
    def _classify_intent(cls, text: str) -> str:
        lower = text.lower()

        # 1. Objetos compostos específicos
        if re.search(r"\b(?:haltere|halteres|dumbbell|barra\s+com\s+pesos)\b", lower) or (
            re.search(r"\b(?:eixo|barra|shaft|rod)\b", lower)
            and re.search(r"\b(?:duas|dois|two|2|pontas|extremidades|ends)\b", lower)
        ):
            return "dumbbell"

        if re.search(r"\b(?:torre|tower|castelo|farol|lighthouse)\b", lower) or (
            re.search(r"\b(?:cilindro|cil[ií]ndric[oa]|cylinder|coluna)\b", lower)
            and re.search(r"\b(?:cone|c[oô]nic[oa]|conical|teto|telhado|roof)\b", lower)
        ):
            return "tower"

        if re.search(r"\b(?:pilar|pillar|pedestal|coluna\s+cl[aá]ssica)\b", lower) or (
            re.search(r"\b(?:coluna|column)\b", lower)
            and re.search(r"\b(?:base|capitel|topo)\b", lower)
        ):
            return "pillar"

        if re.search(r"\b(?:mesa|table|escrivaninha|desk|bancada)\b", lower):
            return "table"

        # 2. Primitivas parametrizadas e mecânicas
        if re.search(r"\b(?:engrenagem|gear|roda\s+dentada|pinh[aã]o|cog)\b", lower):
            return "gear"

        if re.search(r"\b(?:anel|argola|torus|rosquinha|donut|ring)\b", lower):
            return "torus"

        if re.search(r"\b(?:cone|pir[aâ]mide\s+circular|funil)\b", lower):
            return "cone"

        if re.search(r"\b(?:esfera|bola|sphere|ball|globo|orb)\b", lower):
            return "sphere"

        if re.search(r"\b(?:cilindro|cylinder|tubo|cano|tambor|barra\s+cil[ií]ndrica|coluna)\b", lower):
            return "cylinder"

        if re.search(r"\b(?:parede|muro|wall|divis[oó]ria)\b", lower):
            return "wall"

        if re.search(r"\b(?:caixa|cubo|bloco|paralelep[ií]pedo|box|cube|block)\b", lower):
            return "box"

        return "box"

    @classmethod
    def parse_prompt_to_ir(cls, prompt: str) -> Tuple[IntermediateObjectRepresentation, Dict[str, Any]]:
        """
        Analisa semanticamente um prompt em PT-BR ou EN e retorna:
        1. `IntermediateObjectRepresentation` validada contendo os `Component`s extraídos;
        2. Dicionário de metadados semânticos (`parsed_intent`, `detected_components_count`,
           `extracted_dimensions`, `detected_color`, `prompt`).
        """
        cleaned_prompt = cls.validate_prompt(prompt)
        lower = cleaned_prompt.lower()

        intent = cls._classify_intent(cleaned_prompt)
        dims = cls._extract_dimensions_and_counts(cleaned_prompt)

        default_color_map = {
            "gear": ("#94a3b8", True),
            "dumbbell": ("#64748b", True),
            "table": ("#8b5a2b", False),
            "tower": ("#cbd5e1", False),
            "pillar": ("#e2e8f0", False),
            "wall": ("#d1d5db", False),
            "box": ("#3b82f6", False),
            "cylinder": ("#06b6d4", False),
            "sphere": ("#ec4899", False),
            "cone": ("#f97316", False),
            "torus": ("#a855f7", False),
        }
        def_col, def_met = default_color_map.get(intent, ("#3b82f6", False))
        material, detected_color_name = cls._extract_material(cleaned_prompt, default_color=def_col, default_metallic=def_met)

        components: List[Component] = []
        category = ObjectCategory.MECHANICAL
        purpose = ObjectPurpose.GENERAL

        if intent == "table":
            category = ObjectCategory.FURNITURE
            w = dims.get("width", 1.2)
            d = dims.get("depth", 0.8)
            h = dims.get("height", 0.75)
            top_t = dims.get("top_thickness", dims.get("thickness", min(0.05, h * 0.1)))
            if top_t >= h:
                raise ValueError(
                    f"A espessura do tampo ({top_t}m) deve ser estritamente menor que a altura da mesa ({h}m)."
                )
            leg_t = dims.get("leg_thickness", min(0.06, min(w, d) * 0.1))
            if leg_t * 2.0 >= min(w, d):
                raise ValueError(
                    f"A espessura das pernas ({leg_t}m) é excessiva para as dimensões do tampo ({w}m x {d}m)."
                )

            leg_h = round(h - top_t, 6)
            offset_x = round((w / 2.0) - (leg_t / 2.0), 6)
            offset_z = round((d / 2.0) - (leg_t / 2.0), 6)

            # Tampo posicionado no topo das pernas (de Y = leg_h até Y = h)
            components.append(
                Component(
                    id="comp_table_top",
                    name="Tampo da Mesa",
                    type="table_top",
                    parameters={"width": w, "height": top_t, "depth": d},
                    transformation=Transformation(position=[0.0, leg_h, 0.0]),
                    material=material,
                )
            )
            # 4 pernas apoiadas em Y = 0.0 até Y = leg_h
            leg_idx = 1
            for sx in (-1.0, 1.0):
                for sz in (-1.0, 1.0):
                    components.append(
                        Component(
                            id=f"comp_table_leg_{leg_idx}",
                            name=f"Perna {leg_idx}",
                            type="table_leg",
                            parameters={"width": leg_t, "height": leg_h, "depth": leg_t},
                            transformation=Transformation(position=[sx * offset_x, 0.0, sz * offset_z]),
                            material=material,
                        )
                    )
                    leg_idx += 1

            dims.setdefault("width", w)
            dims.setdefault("depth", d)
            dims.setdefault("height", h)
            dims.setdefault("top_thickness", top_t)
            dims.setdefault("leg_thickness", leg_t)

        elif intent == "gear":
            category = ObjectCategory.MECHANICAL
            purpose = ObjectPurpose.TECHNICAL
            outer_r = dims.get("outer_radius", dims.get("radius", 1.0))
            inner_r = dims.get("inner_radius", round(outer_r * 0.78, 6))
            if inner_r >= outer_r:
                raise ValueError(
                    f"O raio interno ({inner_r}m) deve ser estritamente menor que o raio externo ({outer_r}m)."
                )
            bore_r = dims.get("bore_radius", round(min(0.3, inner_r * 0.4), 6))
            if bore_r >= inner_r:
                raise ValueError(
                    f"O raio do furo ({bore_r}m) deve ser estritamente menor que o raio interno ({inner_r}m)."
                )
            num_teeth = int(dims.get("num_teeth", 16))
            h = dims.get("height", dims.get("thickness", 0.25))

            components.append(
                Component(
                    id="comp_gear_main",
                    name="Corpo da Engrenagem",
                    type="gear",
                    parameters={
                        "outer_radius": outer_r,
                        "inner_radius": inner_r,
                        "bore_radius": bore_r,
                        "num_teeth": num_teeth,
                        "height": h,
                    },
                    transformation=Transformation(position=[0.0, 0.0, 0.0]),
                    material=material,
                )
            )
            dims.update(
                {
                    "outer_radius": outer_r,
                    "inner_radius": inner_r,
                    "bore_radius": bore_r,
                    "num_teeth": num_teeth,
                    "height": h,
                }
            )

        elif intent == "tower":
            category = ObjectCategory.ARCHITECTURE
            total_h = dims.get("height", 3.0)
            body_r = dims.get("radius", dims.get("width", 1.2) / 2.0)
            has_base = bool(re.search(r"\bbase\b", lower))

            current_y = 0.0
            if has_base:
                base_h = round(total_h * 0.12, 6)
                base_w = round(body_r * 2.4, 6)
                components.append(
                    Component(
                        id="comp_tower_base",
                        name="Base da Torre",
                        type="box",
                        parameters={"width": base_w, "height": base_h, "depth": base_w},
                        transformation=Transformation(position=[0.0, 0.0, 0.0]),
                        material=material,
                    )
                )
                current_y = base_h

            rem_h = total_h - current_y
            body_h = round(rem_h * 0.7, 6)
            roof_h = round(rem_h * 0.3, 6)
            roof_r = round(body_r * 1.2, 6)

            roof_mat = MaterialDef(
                color="#ef4444" if detected_color_name == "default" else material.color,
                base_color="#ef4444" if detected_color_name == "default" else material.base_color,
                roughness=0.5,
                metalness=0.2,
                name="RoofMaterial",
            )

            components.append(
                Component(
                    id="comp_tower_body",
                    name="Corpo Cilíndrico da Torre",
                    type="cylinder",
                    parameters={"radius": body_r, "height": body_h, "sections": 32},
                    transformation=Transformation(position=[0.0, current_y, 0.0]),
                    material=material,
                )
            )
            components.append(
                Component(
                    id="comp_tower_roof",
                    name="Topo Cônico da Torre",
                    type="cone",
                    parameters={"radius": roof_r, "height": roof_h, "sections": 32},
                    transformation=Transformation(position=[0.0, round(current_y + body_h, 6), 0.0]),
                    material=roof_mat,
                )
            )
            dims.setdefault("height", total_h)
            dims.setdefault("radius", body_r)

        elif intent == "dumbbell":
            category = ObjectCategory.MECHANICAL
            shaft_len = dims.get("width", dims.get("depth", dims.get("height", 0.6)))
            weight_r = dims.get("outer_radius", dims.get("radius", 0.18))
            shaft_r = dims.get("inner_radius", round(min(0.05, weight_r * 0.35), 6))
            use_cylinders = bool(re.search(r"\b(?:cilindros?|discos?|anilhas?|cylinders?|disks?)\b", lower)) and not bool(
                re.search(r"\b(?:esferas?|bolas?|spheres?|balls?)\b", lower)
            )

            # Eixo horizontal centrado em Y = weight_r (para que as pontas toquem Y = 0.0)
            components.append(
                Component(
                    id="comp_dumbbell_shaft",
                    name="Eixo Central",
                    type="cylinder",
                    parameters={"radius": shaft_r, "height": shaft_len, "sections": 24},
                    transformation=Transformation(
                        position=[0.0, weight_r, 0.0],
                        rotation=[0.0, 0.0, 90.0],
                    ),
                    material=material,
                )
            )

            half_span = round(shaft_len / 2.0, 6)
            for side_name, sign in (("Esquerda", -1.0), ("Direita", 1.0)):
                if use_cylinders:
                    disk_w = round(weight_r * 0.6, 6)
                    components.append(
                        Component(
                            id=f"comp_dumbbell_weight_{'left' if sign < 0 else 'right'}",
                            name=f"Peso Cilíndrico ({side_name})",
                            type="cylinder",
                            parameters={"radius": weight_r, "height": disk_w, "sections": 32},
                            transformation=Transformation(
                                position=[sign * half_span, weight_r, 0.0],
                                rotation=[0.0, 0.0, 90.0],
                            ),
                            material=material,
                        )
                    )
                else:
                    # Esfera tem base em Y=0 e raio=weight_r (centro em Y=weight_r)
                    components.append(
                        Component(
                            id=f"comp_dumbbell_weight_{'left' if sign < 0 else 'right'}",
                            name=f"Esfera da Ponta ({side_name})",
                            type="sphere",
                            parameters={"radius": weight_r, "subdivisions": 24},
                            transformation=Transformation(
                                position=[sign * half_span, 0.0, 0.0],
                            ),
                            material=material,
                        )
                    )

            dims.setdefault("shaft_length", shaft_len)
            dims.setdefault("weight_radius", weight_r)

        elif intent == "pillar":
            category = ObjectCategory.ARCHITECTURE
            total_h = dims.get("height", 2.4)
            col_r = dims.get("radius", dims.get("width", 0.6) / 2.0)
            base_w = round(col_r * 2.4, 6)
            base_h = round(total_h * 0.12, 6)
            cap_h = round(total_h * 0.12, 6)
            col_h = round(total_h - base_h - cap_h, 6)

            components.extend(
                [
                    Component(
                        id="comp_pillar_base",
                        name="Base Quadrada do Pilar",
                        type="box",
                        parameters={"width": base_w, "height": base_h, "depth": base_w},
                        transformation=Transformation(position=[0.0, 0.0, 0.0]),
                        material=material,
                    ),
                    Component(
                        id="comp_pillar_column",
                        name="Coluna Cilíndrica",
                        type="cylinder",
                        parameters={"radius": col_r, "height": col_h, "sections": 32},
                        transformation=Transformation(position=[0.0, base_h, 0.0]),
                        material=material,
                    ),
                    Component(
                        id="comp_pillar_capital",
                        name="Topo / Capitel do Pilar",
                        type="box",
                        parameters={"width": base_w, "height": cap_h, "depth": base_w},
                        transformation=Transformation(position=[0.0, round(base_h + col_h, 6), 0.0]),
                        material=material,
                    ),
                ]
            )
            dims.setdefault("height", total_h)
            dims.setdefault("radius", col_r)

        elif intent == "cylinder":
            r = dims.get("radius", dims.get("width", 1.0) / 2.0)
            h = dims.get("height", 1.5)
            components.append(
                Component(
                    id="comp_cylinder_main",
                    name="Cilindro Principal",
                    type="cylinder",
                    parameters={"radius": r, "height": h, "sections": 32},
                    transformation=Transformation(position=[0.0, 0.0, 0.0]),
                    material=material,
                )
            )
            dims.update({"radius": r, "height": h})

        elif intent == "sphere":
            r = dims.get("radius", dims.get("width", 1.0) / 2.0)
            components.append(
                Component(
                    id="comp_sphere_main",
                    name="Esfera Principal",
                    type="sphere",
                    parameters={"radius": r, "subdivisions": 32},
                    transformation=Transformation(position=[0.0, 0.0, 0.0]),
                    material=material,
                )
            )
            dims.update({"radius": r})

        elif intent == "cone":
            r = dims.get("radius", dims.get("width", 1.0) / 2.0)
            h = dims.get("height", 1.5)
            components.append(
                Component(
                    id="comp_cone_main",
                    name="Cone Principal",
                    type="cone",
                    parameters={"radius": r, "height": h, "sections": 32},
                    transformation=Transformation(position=[0.0, 0.0, 0.0]),
                    material=material,
                )
            )
            dims.update({"radius": r, "height": h})

        elif intent == "torus":
            maj_r = dims.get("outer_radius", dims.get("radius", 0.6))
            min_r = dims.get("inner_radius", dims.get("thickness", round(maj_r * 0.3, 6)))
            if min_r >= maj_r:
                raise ValueError(
                    f"O raio menor/espessura ({min_r}m) do anel/torus deve ser menor que o raio principal ({maj_r}m)."
                )
            components.append(
                Component(
                    id="comp_torus_main",
                    name="Torus Principal",
                    type="torus",
                    parameters={"major_radius": maj_r, "minor_radius": min_r, "sections": 32},
                    transformation=Transformation(position=[0.0, 0.0, 0.0]),
                    material=material,
                )
            )
            dims.update({"major_radius": maj_r, "minor_radius": min_r})

        elif intent == "wall":
            category = ObjectCategory.ARCHITECTURE
            w = dims.get("width", 3.0)
            h = dims.get("height", 2.5)
            d = dims.get("depth", dims.get("thickness", 0.2))
            components.append(
                Component(
                    id="comp_wall_main",
                    name="Parede Estrutural",
                    type="wall",
                    parameters={"width": w, "height": h, "depth": d},
                    transformation=Transformation(position=[0.0, 0.0, 0.0]),
                    material=material,
                )
            )
            dims.update({"width": w, "height": h, "depth": d})

        else:
            # Default: box / cubo / paralelepípedo
            is_cube = bool(re.search(r"\b(?:cubo|cube)\b", lower))
            default_side = dims.get("width", dims.get("height", dims.get("depth", 1.0)))
            w = dims.get("width", default_side if is_cube else 1.0)
            h = dims.get("height", default_side if is_cube else 1.0)
            d = dims.get("depth", default_side if is_cube else 1.0)
            components.append(
                Component(
                    id="comp_box_main",
                    name="Bloco / Caixa Principal",
                    type="box",
                    parameters={"width": w, "height": h, "depth": d},
                    transformation=Transformation(position=[0.0, 0.0, 0.0]),
                    material=material,
                )
            )
            dims.update({"width": w, "height": h, "depth": d})

        ir = IntermediateObjectRepresentation(
            id=f"ir-{uuid.uuid4().hex[:8]}",
            name=f"text3d_{intent}",
            category=category,
            purpose=purpose,
            strategy=GenerationStrategy.PROCEDURAL,
            description=cleaned_prompt,
            unit="meters",
            align_to_ground=True,
            components=components,
            user_inputs={"prompt": cleaned_prompt},
            inferred_data={
                "parsed_intent": intent,
                "detected_components_count": len(components),
                "extracted_dimensions": dims,
                "detected_color": material.color,
            },
        )

        semantic_metadata: Dict[str, Any] = {
            "prompt": cleaned_prompt,
            "parsed_intent": intent,
            "detected_components_count": len(components),
            "extracted_dimensions": dims,
            "detected_color": material.color,
            "ir_id": ir.id,
        }
        return ir, semantic_metadata

    @classmethod
    def generate_from_prompt(cls, prompt: str) -> Tuple[trimesh.Trimesh, IntermediateObjectRepresentation, Dict[str, Any]]:
        """
        Executa o pipeline completo Text-to-3D:
        1. Interpreta o prompt em `IntermediateObjectRepresentation` e metadados semânticos;
        2. Sintetiza a malha 3D unificada Y-up via `ProceduralGenerator.generate_from_ir(ir)`.
        Retorna `(mesh, ir, semantic_metadata)`.
        """
        ir, semantic_metadata = cls.parse_prompt_to_ir(prompt)
        mesh = ProceduralGenerator.generate_from_ir(ir, align_to_ground=True)
        mesh.metadata.update(semantic_metadata)
        return mesh, ir, semantic_metadata
