import { useState, useEffect, useRef } from 'react';
import { ModelViewer } from './viewer/ModelViewer';
import type { ThreeViewer } from './viewer/ThreeViewer';
import { GenerationPanel } from './features/generation/GenerationPanel';
import { apiService, type Project, type Job } from './services/api';
import { Box, Eye, Grid, Download, FolderPlus, Info } from 'lucide-react';

export function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [currentProject, setCurrentProject] = useState<Project | null>(null);
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  console.debug('Active Job:', activeJob?.id);
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [telemetry, setTelemetry] = useState<{ vertexCount: number; faceCount: number; dimensions: [number, number, number] } | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isWireframe, setIsWireframe] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<string>('Pronto para iniciar');

  const viewerRef = useRef<ThreeViewer | null>(null);

  // Carregar ou inicializar projetos
  useEffect(() => {
    loadProjects();
  }, []);

  const loadProjects = async () => {
    try {
      const list = await apiService.listProjects();
      setProjects(list);
      if (list.length > 0) {
        setCurrentProject(list[0]);
        if (list[0].active_model_path) {
          setModelUrl(apiService.getFileDownloadUrl(list[0].active_model_path));
        }
      } else {
        // Criar projeto inicial padrão
        const initial = await apiService.createProject({
          name: 'Projeto Principal',
          description: 'Projeto padrão do AI 3D Studio',
          category: 'mechanical'
        });
        setProjects([initial]);
        setCurrentProject(initial);
      }
    } catch (err) {
      console.error(err);
      setStatusMessage('Aviso: Backend local ainda não conectado ou inicializando.');
    }
  };

  const handleCreateNewProject = async () => {
    const name = prompt('Nome do novo projeto:', `Projeto ${projects.length + 1}`);
    if (!name) return;
    try {
      const created = await apiService.createProject({ name });
      setProjects([created, ...projects]);
      setCurrentProject(created);
      setModelUrl(null);
      setTelemetry(null);
      setStatusMessage(`Projeto "${name}" criado com sucesso.`);
    } catch (e: any) {
      alert(`Erro: ${e.message}`);
    }
  };

  const handleGenerate = async (shapeType: string, params: Record<string, any>) => {
    if (!currentProject) return;
    setIsLoading(true);
    setStatusMessage(`Disparando geração de ${shapeType}...`);

    try {
      const job = await apiService.startProceduralJob(currentProject.id, {
        shape_type: shapeType,
        ...params
      });
      setActiveJob(job);
      pollJob(job.id);
    } catch (err: any) {
      setIsLoading(false);
      setStatusMessage(`Erro na solicitação: ${err.message}`);
    }
  };

  const pollJob = (jobId: string) => {
    const interval = setInterval(async () => {
      try {
        const job = await apiService.getJob(jobId);
        setActiveJob(job);
        setStatusMessage(`Tarefa ${job.status}...`);

        if (job.status === 'Concluída') {
          clearInterval(interval);
          setIsLoading(false);
          setStatusMessage('Modelo gerado com sucesso!');
          if (job.result_files && job.result_files.length > 0) {
            const url = apiService.getFileDownloadUrl(job.result_files[0]);
            setModelUrl(url);
          }
          loadProjects();
        } else if (job.status === 'Falhou' || job.status === 'Cancelada') {
          clearInterval(interval);
          setIsLoading(false);
          setStatusMessage(`Tarefa ${job.status}: ${job.error_message || 'Erro desconhecido'}`);
        }
      } catch (e) {
        clearInterval(interval);
        setIsLoading(false);
      }
    }, 500);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#09090b', color: '#f4f4f5', fontFamily: 'sans-serif' }}>
      {/* Topbar */}
      <header style={{ padding: '12px 24px', background: '#18181b', borderBottom: '1px solid #27272a', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <Box color="#3b82f6" size={26} />
          <div>
            <h1 style={{ fontSize: '18px', fontWeight: 'bold', margin: 0 }}>AI 3D STUDIO</h1>
            <span style={{ fontSize: '11px', color: '#71717a' }}>v2.1 Universal • 100% Local (127.0.0.1) • Sem Blender</span>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <span style={{ fontSize: '13px', color: '#a1a1aa' }}>Projeto:</span>
          <select
            value={currentProject?.id || ''}
            onChange={(e) => {
              const p = projects.find((proj) => proj.id === e.target.value);
              if (p) {
                setCurrentProject(p);
                setModelUrl(p.active_model_path ? apiService.getFileDownloadUrl(p.active_model_path) : null);
              }
            }}
            style={{ padding: '6px 12px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46', borderRadius: '4px' }}
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <button
            onClick={handleCreateNewProject}
            style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 12px', background: '#27272a', color: '#fff', border: '1px solid #3f3f46', borderRadius: '4px', cursor: 'pointer' }}
          >
            <FolderPlus size={16} /> Novo Projeto
          </button>
        </div>
      </header>

      {/* Main Content Layout */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* Left Sidebar: Controls & Generation */}
        <aside style={{ width: '380px', background: '#121215', borderRight: '1px solid #27272a', padding: '16px', overflowY: 'auto' }}>
          <GenerationPanel onGenerate={handleGenerate} isLoading={isLoading} />

          {/* Telemetria da Malha */}
          {telemetry && (
            <div style={{ marginTop: '16px', background: '#18181b', padding: '14px', borderRadius: '8px', border: '1px solid #27272a' }}>
              <h4 style={{ fontSize: '14px', fontWeight: 600, margin: '0 0 10px 0', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Info size={16} color="#10b981" /> Métricas e Telemetria Real
              </h4>
              <div style={{ fontSize: '12px', color: '#d4d4d8', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <div><strong>Vértices:</strong> {telemetry.vertexCount.toLocaleString()}</div>
                <div><strong>Faces / Triângulos:</strong> {telemetry.faceCount.toLocaleString()}</div>
                <div><strong>Dimensões (X×Y×Z):</strong> {telemetry.dimensions[0]}m × {telemetry.dimensions[1]}m × {telemetry.dimensions[2]}m</div>
              </div>
            </div>
          )}

          {/* Download de Arquivos */}
          {modelUrl && (
            <div style={{ marginTop: '16px', background: '#18181b', padding: '14px', borderRadius: '8px', border: '1px solid #27272a' }}>
              <h4 style={{ fontSize: '14px', fontWeight: 600, margin: '0 0 10px 0' }}>Exportar Modelo</h4>
              <a
                href={modelUrl}
                download="modelo_gerado.glb"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '8px',
                  padding: '8px',
                  background: '#059669',
                  color: '#fff',
                  textDecoration: 'none',
                  borderRadius: '6px',
                  fontWeight: 600,
                  fontSize: '13px'
                }}
              >
                <Download size={16} /> Baixar Arquivo GLB Validado
              </a>
            </div>
          )}
        </aside>

        {/* Center: 3D WebGL Viewport */}
        <main style={{ flex: 1, position: 'relative', display: 'flex', flexDirection: 'column' }}>
          {/* Viewport Toolbar */}
          <div style={{ position: 'absolute', top: '16px', left: '16px', zIndex: 10, display: 'flex', gap: '8px' }}>
            <button
              onClick={() => {
                if (viewerRef.current) {
                  const state = viewerRef.current.toggleWireframe();
                  setIsWireframe(state);
                }
              }}
              style={{ padding: '6px 12px', background: '#18181bcc', backdropFilter: 'blur(4px)', color: '#fff', border: '1px solid #3f3f46', borderRadius: '4px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px' }}
            >
              <Eye size={14} /> {isWireframe ? 'Modo Sólido' : 'Modo Aramado'}
            </button>
            <button
              onClick={() => viewerRef.current?.toggleGrid()}
              style={{ padding: '6px 12px', background: '#18181bcc', backdropFilter: 'blur(4px)', color: '#fff', border: '1px solid #3f3f46', borderRadius: '4px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px' }}
            >
              <Grid size={14} /> Grade
            </button>
            <button
              onClick={() => viewerRef.current?.setView('front')}
              style={{ padding: '6px 10px', background: '#18181bcc', color: '#fff', border: '1px solid #3f3f46', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}
            >
              Frente
            </button>
            <button
              onClick={() => viewerRef.current?.setView('top')}
              style={{ padding: '6px 10px', background: '#18181bcc', color: '#fff', border: '1px solid #3f3f46', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}
            >
              Topo
            </button>
            <button
              onClick={() => viewerRef.current?.setView('iso')}
              style={{ padding: '6px 10px', background: '#18181bcc', color: '#fff', border: '1px solid #3f3f46', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}
            >
              Iso
            </button>
          </div>

          <div style={{ flex: 1, width: '100%', height: '100%' }}>
            <ModelViewer
              modelUrl={modelUrl}
              viewerRef={viewerRef}
              onMeshLoaded={(info) => setTelemetry(info)}
            />
          </div>

          {/* Bottom Status Bar */}
          <footer style={{ padding: '6px 16px', background: '#18181b', borderTop: '1px solid #27272a', fontSize: '12px', color: '#a1a1aa', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>Status: <span style={{ color: '#60a5fa' }}>{statusMessage}</span></div>
            <div>Controles: Botão Esquerdo (Órbita) • Botão Direito (Pan) • Scroll (Zoom)</div>
          </footer>
        </main>
      </div>
    </div>
  );
}

export default App;
