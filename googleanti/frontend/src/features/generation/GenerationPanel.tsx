import React, { useState } from 'react';
import { Play, Loader2, Sparkles } from 'lucide-react';

interface GenerationPanelProps {
  onGenerate: (shapeType: string, params: Record<string, any>) => void;
  isLoading: boolean;
}

export const GenerationPanel: React.FC<GenerationPanelProps> = ({ onGenerate, isLoading }) => {
  const [shapeType, setShapeType] = useState('gear');
  const [params, setParams] = useState<Record<string, any>>({
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
    leg_thickness: 0.05
  });

  const handleParamChange = (key: string, val: number) => {
    setParams((prev) => ({ ...prev, [key]: val }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onGenerate(shapeType, params);
  };

  return (
    <div style={{ backgroundColor: '#18181b', padding: '16px', borderRadius: '8px', color: '#f4f4f5' }}>
      <h3 style={{ fontSize: '18px', fontWeight: 600, marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <Sparkles size={20} color="#3b82f6" /> Geração Geométrica Procedural
      </h3>

      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: '12px' }}>
          <label style={{ display: 'block', fontSize: '14px', marginBottom: '4px', color: '#a1a1aa' }}>Tipo de Modelo:</label>
          <select
            value={shapeType}
            onChange={(e) => setShapeType(e.target.value)}
            style={{ width: '100%', padding: '8px', borderRadius: '6px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
          >
            <option value="gear">Engrenagem Mecânica (Paramétrica)</option>
            <option value="cylinder">Cilindro / Eixo</option>
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
                step="0.1"
                value={params.outer_radius}
                onChange={(e) => handleParamChange('outer_radius', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Número de Dentes:</label>
              <input
                type="number"
                value={params.num_teeth}
                onChange={(e) => handleParamChange('num_teeth', parseInt(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Espessura (m):</label>
              <input
                type="number"
                step="0.05"
                value={params.height}
                onChange={(e) => handleParamChange('height', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Furo Central (m):</label>
              <input
                type="number"
                step="0.05"
                value={params.bore_radius}
                onChange={(e) => handleParamChange('bore_radius', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
          </div>
        )}

        {shapeType === 'box' && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', marginBottom: '12px' }}>
            <div>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Largura (X):</label>
              <input
                type="number"
                step="0.1"
                value={params.width}
                onChange={(e) => handleParamChange('width', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Altura (Z):</label>
              <input
                type="number"
                step="0.1"
                value={params.height}
                onChange={(e) => handleParamChange('height', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Profundidade (Y):</label>
              <input
                type="number"
                step="0.1"
                value={params.depth}
                onChange={(e) => handleParamChange('depth', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
          </div>
        )}

        {shapeType === 'cylinder' && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '12px' }}>
            <div>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Raio (m):</label>
              <input
                type="number"
                step="0.1"
                value={params.radius}
                onChange={(e) => handleParamChange('radius', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Altura (m):</label>
              <input
                type="number"
                step="0.1"
                value={params.height}
                onChange={(e) => handleParamChange('height', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
          </div>
        )}

        {shapeType === 'table' && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', marginBottom: '12px' }}>
            <div>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Largura (m):</label>
              <input
                type="number"
                step="0.1"
                value={params.width}
                onChange={(e) => handleParamChange('width', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Altura (m):</label>
              <input
                type="number"
                step="0.05"
                value={params.height}
                onChange={(e) => handleParamChange('height', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '12px', color: '#a1a1aa' }}>Profundidade (m):</label>
              <input
                type="number"
                step="0.1"
                value={params.depth}
                onChange={(e) => handleParamChange('depth', parseFloat(e.target.value))}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46' }}
              />
            </div>
          </div>
        )}

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
              <Loader2 className="animate-spin" size={18} /> Gerando Geometria...
            </>
          ) : (
            <>
              <Play size={18} /> Executar Geração Procedural
            </>
          )}
        </button>
      </form>
    </div>
  );
};
