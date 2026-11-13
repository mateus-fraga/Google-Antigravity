import React, { useState, useEffect, useRef } from 'react';
import { Play, Loader2, Sparkles, XCircle, Type, Image as ImageIcon, Sliders, Upload } from 'lucide-react';
import type { ImageTo3dMode } from '../../services/api';

export type GenerationTabMode = 'procedural' | 'text_to_3d' | 'image_to_3d';

export interface ImageTo3dFormOptions {
  mode: ImageTo3dMode;
  thickness: number;
  resolution_scale: number;
  relief_depth: number;
  base_thickness: number;
}

interface GenerationPanelProps {
  onGenerate: (shapeType: string, params: Record<string, unknown>) => void;
  onGenerateTextTo3D?: (prompt: string) => void;
  onGenerateImageTo3D?: (file: File, options: ImageTo3dFormOptions) => void;
  onCancel?: () => void;
  isLoading: boolean;
  activeJobStatus?: string | null;
}

const PROMPT_TEMPLATES: { label: string; prompt: string }[] = [
  {
    label: 'Mesa de centro...',
    prompt: 'Mesa de centro em madeira com 120cm de largura, 45cm de altura e 60cm de profundidade',
  },
  {
    label: 'Engrenagem dourada...',
    prompt: 'Engrenagem metálica dourada com 18 dentes, raio externo 1.4m e altura 25cm',
  },
  {
    label: 'Torre de castelo...',
    prompt: 'Torre de castelo em pedra com raio 80cm e altura 2.4m',
  },
  {
    label: 'Halter metálico...',
    prompt: 'Halter metálico azul com largura 1.2m e raio 35cm',
  },
];

export const GenerationPanel: React.FC<GenerationPanelProps> = ({
  onGenerate,
  onGenerateTextTo3D,
  onGenerateImageTo3D,
  onCancel,
  isLoading,
  activeJobStatus,
}) => {
  const [activeTab, setActiveTab] = useState<GenerationTabMode>('procedural');

  // Estado da Aba 1: Procedural
  const [shapeType, setShapeType] = useState('gear');
  const [params, setParams] = useState<Record<string, number>>({
    outer_radius: 1.2,
    inner_radius: 0.9,
    bore_radius: 0.3,
    num_teeth: 14,
    height: 0.25,
    width: 1.0,
    depth: 1.0,
    radius: 0.5,
    sections: 32,
    top_thickness: 0.05,
    leg_thickness: 0.05,
  });

  // Estado da Aba 2: Texto para 3D
  const [promptText, setPromptText] = useState<string>(PROMPT_TEMPLATES[0].prompt);

  // Estado da Aba 3: Imagem para 3D
  const [selectedImageFile, setSelectedImageFile] = useState<File | null>(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);
  const [imageMode, setImageMode] = useState<ImageTo3dMode>('silhouette');
  const [imageOptions, setImageOptions] = useState<{
    thickness: number;
    resolution_scale: number;
    relief_depth: number;
    base_thickness: number;
  }>({
    thickness: 0.15,
    resolution_scale: 1.0,
    relief_depth: 0.15,
    base_thickness: 0.05,
  });

  const previewUrlRef = useRef<string | null>(null);

  useEffect(() => {
    return () => {
      if (previewUrlRef.current) {
        URL.revokeObjectURL(previewUrlRef.current);
        previewUrlRef.current = null;
      }
    };
  }, []);

  const handleParamChange = (key: string, val: number) => {
    setParams((prev) => ({ ...prev, [key]: val }));
  };

  const handleImageOptionChange = (
    key: 'thickness' | 'resolution_scale' | 'relief_depth' | 'base_thickness',
    val: number
  ) => {
    setImageOptions((prev) => ({ ...prev, [key]: val }));
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] || null;
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
    if (file) {
      const objectUrl = URL.createObjectURL(file);
      previewUrlRef.current = objectUrl;
      setSelectedImageFile(file);
      setImagePreviewUrl(objectUrl);
    } else {
      setSelectedImageFile(null);
      setImagePreviewUrl(null);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (activeTab === 'procedural') {
      onGenerate(shapeType, params);
      return;
    }

    if (activeTab === 'text_to_3d') {
      if (onGenerateTextTo3D) {
        onGenerateTextTo3D(promptText);
      } else {
        onGenerate('text_to_3d', { prompt: promptText });
      }
      return;
    }

    if (activeTab === 'image_to_3d') {
      if (!selectedImageFile) return;
      if (onGenerateImageTo3D) {
        onGenerateImageTo3D(selectedImageFile, {
          mode: imageMode,
          thickness: imageOptions.thickness,
          resolution_scale: imageOptions.resolution_scale,
          relief_depth: imageOptions.relief_depth,
          base_thickness: imageOptions.base_thickness,
        });
      }
    }
  };

  const isSubmitDisabled =
    isLoading ||
    (activeTab === 'text_to_3d' && promptText.trim().length === 0) ||
    (activeTab === 'image_to_3d' && !selectedImageFile);

  const inputStyle: React.CSSProperties = {
    width: '100%',
    padding: '6px',
    borderRadius: '4px',
    background: '#27272a',
    color: '#fff',
    border: '1px solid #3f3f46',
    opacity: isLoading ? 0.65 : 1,
  };

  return (
    <div style={{ backgroundColor: '#18181b', padding: '16px', borderRadius: '8px', color: '#f4f4f5', border: '1px solid #27272a' }}>
      <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <Sparkles size={18} color="#3b82f6" /> Motor de Geração 3D Multimodal (Y-up)
      </h3>

      {/* Navegação por 3 Abas: Procedural | Texto para 3D | Imagem para 3D */}
      <div
        role="tablist"
        aria-label="Modos de Geração 3D"
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr 1fr',
          gap: '4px',
          background: '#09090b',
          padding: '4px',
          borderRadius: '6px',
          border: '1px solid #27272a',
          marginBottom: '14px',
        }}
      >
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'procedural'}
          disabled={isLoading}
          onClick={() => setActiveTab('procedural')}
          style={{
            padding: '7px 6px',
            borderRadius: '4px',
            border: 'none',
            background: activeTab === 'procedural' ? '#2563eb' : 'transparent',
            color: activeTab === 'procedural' ? '#fff' : '#a1a1aa',
            fontWeight: 600,
            fontSize: '11px',
            cursor: isLoading ? 'not-allowed' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '4px',
            opacity: isLoading ? 0.6 : 1,
          }}
        >
          <Sliders size={13} /> Procedural
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'text_to_3d'}
          disabled={isLoading}
          onClick={() => setActiveTab('text_to_3d')}
          style={{
            padding: '7px 6px',
            borderRadius: '4px',
            border: 'none',
            background: activeTab === 'text_to_3d' ? '#2563eb' : 'transparent',
            color: activeTab === 'text_to_3d' ? '#fff' : '#a1a1aa',
            fontWeight: 600,
            fontSize: '11px',
            cursor: isLoading ? 'not-allowed' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '4px',
            opacity: isLoading ? 0.6 : 1,
          }}
        >
          <Type size={13} /> Texto p/ 3D
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'image_to_3d'}
          disabled={isLoading}
          onClick={() => setActiveTab('image_to_3d')}
          style={{
            padding: '7px 6px',
            borderRadius: '4px',
            border: 'none',
            background: activeTab === 'image_to_3d' ? '#2563eb' : 'transparent',
            color: activeTab === 'image_to_3d' ? '#fff' : '#a1a1aa',
            fontWeight: 600,
            fontSize: '11px',
            cursor: isLoading ? 'not-allowed' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '4px',
            opacity: isLoading ? 0.6 : 1,
          }}
        >
          <ImageIcon size={13} /> Imagem p/ 3D
        </button>
      </div>

      <form onSubmit={handleSubmit}>
        {/* ================= ABA 1: PROCEDURAL ================= */}
        {activeTab === 'procedural' && (
          <>
            <div style={{ marginBottom: '12px' }}>
              <label style={{ display: 'block', fontSize: '13px', marginBottom: '4px', color: '#a1a1aa' }}>Tipo de Modelo:</label>
              <select
                value={shapeType}
                onChange={(e) => setShapeType(e.target.value)}
                disabled={isLoading}
                style={{ width: '100%', padding: '8px', borderRadius: '6px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              >
                <option value="gear">Engrenagem Mecânica (Paramétrica)</option>
                <option value="cylinder">Cilindro / Eixo Vertical</option>
                <option value="box">Cubo / Paralelepípedo</option>
                <option value="table">Mesa Paramétrica (Mobiliário)</option>
              </select>
            </div>

            {shapeType === 'gear' && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '12px' }}>
                <div>
                  <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Raio Externo (m):</label>
                  <input
                    type="number"
                    step="0.05"
                    disabled={isLoading}
                    value={Number.isNaN(params.outer_radius) ? '' : params.outer_radius}
                    onChange={(e) => handleParamChange('outer_radius', parseFloat(e.target.value))}
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Raio Interno (m):</label>
                  <input
                    type="number"
                    step="0.05"
                    disabled={isLoading}
                    value={Number.isNaN(params.inner_radius) ? '' : params.inner_radius}
                    onChange={(e) => handleParamChange('inner_radius', parseFloat(e.target.value))}
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Número de Dentes:</label>
                  <input
                    type="number"
                    disabled={isLoading}
                    value={Number.isNaN(params.num_teeth) ? '' : params.num_teeth}
                    onChange={(e) => handleParamChange('num_teeth', parseInt(e.target.value, 10))}
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Altura Y / Espessura (m):</label>
                  <input
                    type="number"
                    step="0.05"
                    disabled={isLoading}
                    value={Number.isNaN(params.height) ? '' : params.height}
                    onChange={(e) => handleParamChange('height', parseFloat(e.target.value))}
                    style={inputStyle}
                  />
                </div>
                <div style={{ gridColumn: '1 / -1' }}>
                  <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Raio do Furo Central (m):</label>
                  <input
                    type="number"
                    step="0.05"
                    disabled={isLoading}
                    value={Number.isNaN(params.bore_radius) ? '' : params.bore_radius}
                    onChange={(e) => handleParamChange('bore_radius', parseFloat(e.target.value))}
                    style={inputStyle}
                  />
                </div>
              </div>
            )}

            {shapeType === 'box' && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', marginBottom: '12px' }}>
                <div>
                  <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Largura X (m):</label>
                  <input
                    type="number"
                    step="0.1"
                    disabled={isLoading}
                    value={Number.isNaN(params.width) ? '' : params.width}
                    onChange={(e) => handleParamChange('width', parseFloat(e.target.value))}
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Altura Y (m):</label>
                  <input
                    type="number"
                    step="0.1"
                    disabled={isLoading}
                    value={Number.isNaN(params.height) ? '' : params.height}
                    onChange={(e) => handleParamChange('height', parseFloat(e.target.value))}
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Profundidade Z (m):</label>
                  <input
                    type="number"
                    step="0.1"
                    disabled={isLoading}
                    value={Number.isNaN(params.depth) ? '' : params.depth}
                    onChange={(e) => handleParamChange('depth', parseFloat(e.target.value))}
                    style={inputStyle}
                  />
                </div>
              </div>
            )}

            {shapeType === 'cylinder' && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '12px' }}>
                <div>
                  <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Raio XZ (m):</label>
                  <input
                    type="number"
                    step="0.1"
                    disabled={isLoading}
                    value={Number.isNaN(params.radius) ? '' : params.radius}
                    onChange={(e) => handleParamChange('radius', parseFloat(e.target.value))}
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Altura Y (m):</label>
                  <input
                    type="number"
                    step="0.1"
                    disabled={isLoading}
                    value={Number.isNaN(params.height) ? '' : params.height}
                    onChange={(e) => handleParamChange('height', parseFloat(e.target.value))}
                    style={inputStyle}
                  />
                </div>
              </div>
            )}

            {shapeType === 'table' && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', marginBottom: '12px' }}>
                <div>
                  <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Largura X (m):</label>
                  <input
                    type="number"
                    step="0.1"
                    disabled={isLoading}
                    value={Number.isNaN(params.width) ? '' : params.width}
                    onChange={(e) => handleParamChange('width', parseFloat(e.target.value))}
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Altura Y (m):</label>
                  <input
                    type="number"
                    step="0.05"
                    disabled={isLoading}
                    value={Number.isNaN(params.height) ? '' : params.height}
                    onChange={(e) => handleParamChange('height', parseFloat(e.target.value))}
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Profundidade Z (m):</label>
                  <input
                    type="number"
                    step="0.1"
                    disabled={isLoading}
                    value={Number.isNaN(params.depth) ? '' : params.depth}
                    onChange={(e) => handleParamChange('depth', parseFloat(e.target.value))}
                    style={inputStyle}
                  />
                </div>
              </div>
            )}
          </>
        )}

        {/* ================= ABA 2: TEXTO PARA 3D ================= */}
        {activeTab === 'text_to_3d' && (
          <div style={{ marginBottom: '12px' }}>
            <label style={{ display: 'block', fontSize: '13px', marginBottom: '4px', color: '#a1a1aa' }}>
              Descrição Semântica do Modelo 3D (PT-BR ou EN):
            </label>
            <textarea
              rows={4}
              disabled={isLoading}
              value={promptText}
              onChange={(e) => setPromptText(e.target.value)}
              placeholder="Ex.: Mesa de centro em madeira com 120cm de largura, 45cm de altura e 60cm de profundidade..."
              style={{
                width: '100%',
                padding: '8px',
                borderRadius: '6px',
                background: '#27272a',
                color: '#fff',
                border: '1px solid #3f3f46',
                fontSize: '12px',
                resize: 'vertical',
                fontFamily: 'inherit',
                marginBottom: '8px',
              }}
            />

            <div style={{ fontSize: '11px', color: '#a1a1aa', marginBottom: '6px' }}>
              Templates rápidos (clique para preencher):
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
              {PROMPT_TEMPLATES.map((tpl) => (
                <button
                  key={tpl.label}
                  type="button"
                  disabled={isLoading}
                  onClick={() => setPromptText(tpl.prompt)}
                  style={{
                    padding: '4px 8px',
                    borderRadius: '999px',
                    background: '#27272a',
                    color: '#93c5fd',
                    border: '1px solid #3f3f46',
                    fontSize: '11px',
                    cursor: isLoading ? 'not-allowed' : 'pointer',
                    opacity: isLoading ? 0.6 : 1,
                  }}
                >
                  {tpl.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* ================= ABA 3: IMAGEM PARA 3D ================= */}
        {activeTab === 'image_to_3d' && (
          <div style={{ marginBottom: '12px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '13px', marginBottom: '4px', color: '#a1a1aa' }}>
                Imagem de Referência 2D (PNG, JPEG, WEBP — máx. 10 MB):
              </label>
              <label
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '8px',
                  padding: '10px',
                  borderRadius: '6px',
                  border: '1px dashed #3f3f46',
                  background: '#27272a',
                  color: '#e4e4e7',
                  fontSize: '12px',
                  cursor: isLoading ? 'not-allowed' : 'pointer',
                  opacity: isLoading ? 0.6 : 1,
                }}
              >
                <Upload size={15} color="#60a5fa" />
                <span>{selectedImageFile ? selectedImageFile.name : 'Selecionar imagem do computador...'}</span>
                <input
                  type="file"
                  accept="image/png, image/jpeg, image/webp"
                  disabled={isLoading}
                  onChange={handleFileChange}
                  style={{ display: 'none' }}
                />
              </label>
            </div>

            {imagePreviewUrl && selectedImageFile && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  padding: '8px',
                  background: '#09090b',
                  borderRadius: '6px',
                  border: '1px solid #27272a',
                }}
              >
                <img
                  src={imagePreviewUrl}
                  alt="Pré-visualização da imagem 2D selecionada"
                  style={{
                    width: '64px',
                    height: '64px',
                    objectFit: 'contain',
                    borderRadius: '4px',
                    background: '#18181b',
                    border: '1px solid #3f3f46',
                  }}
                />
                <div style={{ fontSize: '11px', color: '#d4d4d8', overflow: 'hidden' }}>
                  <div style={{ fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {selectedImageFile.name}
                  </div>
                  <div style={{ color: '#a1a1aa', marginTop: '2px' }}>
                    {(selectedImageFile.size / 1024).toFixed(1)} KB • Pré-visualização pronta
                  </div>
                </div>
              </div>
            )}

            <div>
              <label style={{ display: 'block', fontSize: '12px', marginBottom: '4px', color: '#a1a1aa' }}>
                Modo de Reconstrução 3D:
              </label>
              <select
                value={imageMode}
                disabled={isLoading}
                onChange={(e) => setImageMode(e.target.value as ImageTo3dMode)}
                style={{ width: '100%', padding: '8px', borderRadius: '6px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46', fontSize: '12px' }}
              >
                <option value="silhouette">Extrusão de Silhueta 2D + Furos (Alpha / Otsu)</option>
                <option value="heightmap">Mapa de Relevo / Altura por Luminância (Heightmap)</option>
              </select>
            </div>

            {imageMode === 'silhouette' ? (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                <div>
                  <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Espessura Y (m):</label>
                  <input
                    type="number"
                    step="0.02"
                    min="0.01"
                    max="5.0"
                    disabled={isLoading}
                    value={Number.isNaN(imageOptions.thickness) ? '' : imageOptions.thickness}
                    onChange={(e) => handleImageOptionChange('thickness', parseFloat(e.target.value))}
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Escala de Resolução:</label>
                  <input
                    type="number"
                    step="0.1"
                    min="0.1"
                    max="2.0"
                    disabled={isLoading}
                    value={Number.isNaN(imageOptions.resolution_scale) ? '' : imageOptions.resolution_scale}
                    onChange={(e) => handleImageOptionChange('resolution_scale', parseFloat(e.target.value))}
                    style={inputStyle}
                  />
                </div>
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                <div>
                  <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Relevo Y Máx. (m):</label>
                  <input
                    type="number"
                    step="0.02"
                    min="0.005"
                    max="5.0"
                    disabled={isLoading}
                    value={Number.isNaN(imageOptions.relief_depth) ? '' : imageOptions.relief_depth}
                    onChange={(e) => handleImageOptionChange('relief_depth', parseFloat(e.target.value))}
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Base Sólida Y (m):</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0.005"
                    max="5.0"
                    disabled={isLoading}
                    value={Number.isNaN(imageOptions.base_thickness) ? '' : imageOptions.base_thickness}
                    onChange={(e) => handleImageOptionChange('base_thickness', parseFloat(e.target.value))}
                    style={inputStyle}
                  />
                </div>
              </div>
            )}
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <button
            type="submit"
            disabled={isSubmitDisabled}
            style={{
              width: '100%',
              padding: '10px',
              backgroundColor: isSubmitDisabled ? '#2563eb88' : '#2563eb',
              color: '#fff',
              border: 'none',
              borderRadius: '6px',
              fontWeight: 600,
              cursor: isSubmitDisabled ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
            }}
          >
            {isLoading ? (
              <>
                <Loader2 className="animate-spin" size={18} />
                {activeJobStatus ? `Processando (${activeJobStatus})...` : 'Gerando Geometria...'}
              </>
            ) : (
              <>
                <Play size={18} />
                {activeTab === 'procedural' && 'Executar Geração Procedural'}
                {activeTab === 'text_to_3d' && 'Gerar Modelo 3D via Texto'}
                {activeTab === 'image_to_3d' && 'Enviar Imagem e Gerar 3D'}
              </>
            )}
          </button>

          {isLoading && onCancel && (
            <button
              type="button"
              onClick={onCancel}
              style={{
                width: '100%',
                padding: '8px 10px',
                backgroundColor: '#dc2626',
                color: '#fff',
                border: '1px solid #ef4444',
                borderRadius: '6px',
                fontWeight: 600,
                fontSize: '13px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px',
              }}
            >
              <XCircle size={16} /> Cancelar Tarefa em Execução
            </button>
          )}
        </div>
      </form>
    </div>
  );
};
