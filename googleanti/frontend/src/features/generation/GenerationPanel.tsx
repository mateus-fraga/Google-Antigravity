import React, { useState } from 'react';
import { Play, Loader2, Sparkles, XCircle } from 'lucide-react';

interface GenerationPanelProps {
  onGenerate: (shapeType: string, params: Record<string, unknown>) => void;
  onCancel?: () => void;
  isLoading: boolean;
  activeJobStatus?: string | null;
}

export const GenerationPanel: React.FC<GenerationPanelProps> = ({
  onGenerate,
  onCancel,
  isLoading,
  activeJobStatus,
}) => {
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

  const handleParamChange = (key: string, val: number) => {
    setParams((prev) => ({ ...prev, [key]: val }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onGenerate(shapeType, params);
  };

  return (
    <div style={{ backgroundColor: '#18181b', padding: '16px', borderRadius: '8px', color: '#f4f4f5', border: '1px solid #27272a' }}>
      <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <Sparkles size={18} color="#3b82f6" /> Geração Geométrica Procedural (Y-up)
      </h3>

      <form onSubmit={handleSubmit}>
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
                value={Number.isNaN(params.outer_radius) ? '' : params.outer_radius}
                onChange={(e) => handleParamChange('outer_radius', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Raio Interno (m):</label>
              <input
                type="number"
                step="0.05"
                value={Number.isNaN(params.inner_radius) ? '' : params.inner_radius}
                onChange={(e) => handleParamChange('inner_radius', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Número de Dentes:</label>
              <input
                type="number"
                value={Number.isNaN(params.num_teeth) ? '' : params.num_teeth}
                onChange={(e) => handleParamChange('num_teeth', parseInt(e.target.value, 10))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Altura Y / Espessura (m):</label>
              <input
                type="number"
                step="0.05"
                value={Number.isNaN(params.height) ? '' : params.height}
                onChange={(e) => handleParamChange('height', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Raio do Furo Central (m):</label>
              <input
                type="number"
                step="0.05"
                value={Number.isNaN(params.bore_radius) ? '' : params.bore_radius}
                onChange={(e) => handleParamChange('bore_radius', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
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
                value={Number.isNaN(params.width) ? '' : params.width}
                onChange={(e) => handleParamChange('width', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Altura Y (m):</label>
              <input
                type="number"
                step="0.1"
                value={Number.isNaN(params.height) ? '' : params.height}
                onChange={(e) => handleParamChange('height', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Profundidade Z (m):</label>
              <input
                type="number"
                step="0.1"
                value={Number.isNaN(params.depth) ? '' : params.depth}
                onChange={(e) => handleParamChange('depth', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
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
                value={Number.isNaN(params.radius) ? '' : params.radius}
                onChange={(e) => handleParamChange('radius', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Altura Y (m):</label>
              <input
                type="number"
                step="0.1"
                value={Number.isNaN(params.height) ? '' : params.height}
                onChange={(e) => handleParamChange('height', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
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
                value={Number.isNaN(params.width) ? '' : params.width}
                onChange={(e) => handleParamChange('width', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Altura Y (m):</label>
              <input
                type="number"
                step="0.05"
                value={Number.isNaN(params.height) ? '' : params.height}
                onChange={(e) => handleParamChange('height', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Profundidade Z (m):</label>
              <input
                type="number"
                step="0.1"
                value={Number.isNaN(params.depth) ? '' : params.depth}
                onChange={(e) => handleParamChange('depth', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <button
            type="submit"
            disabled={isLoading}
            style={{
              width: '100%',
              padding: '10px',
              backgroundColor: isLoading ? '#2563eb88' : '#2563eb',
              color: '#fff',
              border: 'none',
              borderRadius: '6px',
              fontWeight: 600,
              cursor: isLoading ? 'not-allowed' : 'pointer',
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
                <Play size={18} /> Executar Geração Procedural
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

