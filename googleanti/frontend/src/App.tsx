import { useState, useEffect, useRef, useCallback } from 'react';
import { ModelViewer } from './viewer/ModelViewer';
import type { ThreeViewer, MeshTelemetryInfo } from './viewer/ThreeViewer';
import { GenerationPanel, type ImageTo3dFormOptions } from './features/generation/GenerationPanel';
import {
  apiService,
  type Project,
  type Job,
  type SupportedExportFormat,
  extractFilenameFromPath,
} from './services/api';
import { Box, Eye, Grid, Download, FolderPlus, Info, Compass, AlertTriangle, CheckCircle2, XCircle } from 'lucide-react';

export function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [currentProject, setCurrentProject] = useState<Project | null>(null);
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [coordinateSystem, setCoordinateSystem] = useState<'Y-up' | 'legacy_z_up'>('Y-up');
  const [telemetry, setTelemetry] = useState<MeshTelemetryInfo | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isExporting, setIsExporting] = useState<boolean>(false);
  const [selectedExportFormat, setSelectedExportFormat] = useState<SupportedExportFormat>('glb');
  const [availableFormats, setAvailableFormats] = useState<Record<string, string>>({});
  const [isWireframe, setIsWireframe] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<string>('Pronto para iniciar');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const viewerRef = useRef<ThreeViewer | null>(null);
  const pollIntervalRef = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current !== null) {
      window.clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => {
      stopPolling();
    };
  }, [stopPolling]);

  const refreshProjectArtifacts = useCallback(async (projectId: string) => {
    try {
      const info = await apiService.listProjectArtifacts(projectId);
      setAvailableFormats(info.active_formats || {});
    } catch {
      setAvailableFormats({});
    }
  }, []);

  const selectProjectAndLoadModel = useCallback(
    async (project: Project) => {
      setCurrentProject(project);
      setErrorMessage(null);
      const coord = project.coordinate_system === 'legacy_z_up' ? 'legacy_z_up' : 'Y-up';
      setCoordinateSystem(coord);

      if (project.active_model_path) {
        const contextualUrl = apiService.getArtifactDownloadUrl(project.id, project.active_model_path);
        setModelUrl(contextualUrl);
        await refreshProjectArtifacts(project.id);
      } else {
        setModelUrl(null);
        setTelemetry(null);
        setAvailableFormats({});
      }
    },
    [refreshProjectArtifacts]
  );

  useEffect(() => {
    let isMounted = true;
    (async () => {
      try {
        const list = await apiService.listProjects();
        if (!isMounted) return;
        setProjects(list);
        if (list.length > 0) {
          await selectProjectAndLoadModel(list[0]);
        } else {
          const initial = await apiService.createProject({
            name: 'Projeto Principal',
            description: 'Projeto padrão do AI 3D Studio',
            category: 'mechanical',
          });
          if (!isMounted) return;
          setProjects([initial]);
          await selectProjectAndLoadModel(initial);
        }
      } catch (err) {
        console.error(err);
        if (isMounted) {
          setStatusMessage('Aviso: Backend local ainda não conectado ou inicializando.');
        }
      }
    })();
    return () => {
      isMounted = false;
    };
  }, [selectProjectAndLoadModel]);

  const handleCreateNewProject = async () => {
    const name = prompt('Nome do novo projeto:', `Projeto ${projects.length + 1}`);
    if (!name) return;
    try {
      setErrorMessage(null);
      const created = await apiService.createProject({ name });
      setProjects((prev) => [created, ...prev]);
      await selectProjectAndLoadModel(created);
      setStatusMessage(`Projeto "${name}" criado com sucesso.`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setErrorMessage(`Erro ao criar projeto: ${msg}`);
    }
  };

  const pollJob = useCallback(
    (jobId: string, projectId: string) => {
      stopPolling();
      pollIntervalRef.current = window.setInterval(async () => {
        try {
          const job = await apiService.getJob(jobId);
          setActiveJob(job);
          setStatusMessage(`Tarefa ${job.status}...`);

          if (job.status === 'Concluída') {
            stopPolling();
            setIsLoading(false);
            setErrorMessage(null);
            setStatusMessage('Modelo 3D gerado e validado com sucesso!');

            const updatedProject = await apiService.getProject(projectId);
            setProjects((prev) => prev.map((p) => (p.id === updatedProject.id ? updatedProject : p)));
            await selectProjectAndLoadModel(updatedProject);
          } else if (job.status === 'Falhou' || job.status === 'Cancelada') {
            stopPolling();
            setIsLoading(false);
            const reason = job.error_message || (job.status === 'Cancelada' ? 'Cancelada pelo usuário.' : 'Erro desconhecido.');
            setStatusMessage(`Tarefa ${job.status}: ${reason}`);
            if (job.status === 'Falhou') {
              setErrorMessage(reason);
            }
          }
        } catch (e: unknown) {
          stopPolling();
          setIsLoading(false);
          const msg = e instanceof Error ? e.message : String(e);
          setErrorMessage(`Erro ao acompanhar tarefa: ${msg}`);
        }
      }, 350);
    },
    [selectProjectAndLoadModel, stopPolling]
  );

  const handleGenerate = async (shapeType: string, params: Record<string, unknown>) => {
    if (!currentProject) return;
    setErrorMessage(null);
    setIsLoading(true);
    setStatusMessage(`Disparando geração procedural (${shapeType})...`);

    try {
      const job = await apiService.startProceduralJob(currentProject.id, {
        shape_type: shapeType,
        ...params,
      });
      setActiveJob(job);
      pollJob(job.id, currentProject.id);
    } catch (err: unknown) {
      setIsLoading(false);
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(msg);
      setStatusMessage(`Falha na validação/solicitação: ${msg}`);
    }
  };

  const handleGenerateTextTo3D = async (promptText: string) => {
    if (!currentProject) return;
    setErrorMessage(null);
    setIsLoading(true);
    setStatusMessage('Interpretando prompt semântico e gerando composição 3D...');

    try {
      const job = await apiService.startTextTo3dJob(currentProject.id, promptText);
      setActiveJob(job);
      pollJob(job.id, currentProject.id);
    } catch (err: unknown) {
      setIsLoading(false);
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(msg);
      setStatusMessage(`Falha no Text-to-3D: ${msg}`);
    }
  };

  const handleGenerateImageTo3D = async (file: File, options: ImageTo3dFormOptions) => {
    if (!currentProject) return;
    setErrorMessage(null);
    setIsLoading(true);
    setStatusMessage(`Enviando e validando imagem "${file.name}"...`);

    try {
      const uploaded = await apiService.uploadReferenceImage(currentProject.id, file);
      setStatusMessage(
        `Imagem validada (${uploaded.width}×${uploaded.height} ${uploaded.format.toUpperCase()}). Iniciando reconstrução ${options.mode}...`
      );

      const job = await apiService.startImageTo3dJob(currentProject.id, {
        reference_image_filename: uploaded.filename,
        mode: options.mode,
        thickness: options.thickness,
        resolution_scale: options.resolution_scale,
        relief_depth: options.relief_depth,
        base_thickness: options.base_thickness,
      });
      setActiveJob(job);
      pollJob(job.id, currentProject.id);
    } catch (err: unknown) {
      setIsLoading(false);
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(msg);
      setStatusMessage(`Falha no Image-to-3D: ${msg}`);
    }
  };

  const handleCancelActiveJob = async () => {
    if (!activeJob) return;
    try {
      setStatusMessage('Solicitando cancelamento cooperativo da tarefa...');
      await apiService.cancelJob(activeJob.id);
      const updated = await apiService.getJob(activeJob.id);
      setActiveJob(updated);
      if (updated.status === 'Cancelada' || updated.status === 'Concluída' || updated.status === 'Falhou') {
        stopPolling();
        setIsLoading(false);
        setStatusMessage(`Tarefa ${updated.status}: ${updated.error_message || 'Operação encerrada.'}`);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(`Não foi possível cancelar a tarefa: ${msg}`);
    }
  };

  const handleExportAndDownload = async () => {
    if (!currentProject) return;
    setErrorMessage(null);
    setIsExporting(true);
    try {
      setStatusMessage(`Preparando exportação validada em ${selectedExportFormat.toUpperCase()}...`);
      const exported = await apiService.exportProjectModelFormat(currentProject.id, selectedExportFormat);
      await refreshProjectArtifacts(currentProject.id);

      const downloadUrl = apiService.getArtifactDownloadUrl(currentProject.id, exported.filename);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = exported.filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      setStatusMessage(`Download iniciado: ${exported.filename} (${selectedExportFormat.toUpperCase()} validado).`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(msg);
      setStatusMessage(`Erro na exportação: ${msg}`);
    } finally {
      setIsExporting(false);
    }
  };

  const activeInspection =
    activeJob?.metadata && typeof activeJob.metadata === 'object' && 'inspection' in activeJob.metadata
      ? (activeJob.metadata.inspection as Record<string, unknown>)
      : null;

  const parsedIntent =
    typeof activeJob?.metadata?.parsed_intent === 'string' ? activeJob.metadata.parsed_intent : null;
  const detectedComponentsCount =
    typeof activeJob?.metadata?.detected_components_count === 'number'
      ? activeJob.metadata.detected_components_count
      : null;
  const extractedDimensions =
    activeJob?.metadata?.extracted_dimensions && typeof activeJob.metadata.extracted_dimensions === 'object'
      ? (activeJob.metadata.extracted_dimensions as Record<string, number>)
      : null;
  const detectedColor =
    typeof activeJob?.metadata?.detected_color === 'string' ? activeJob.metadata.detected_color : null;
  const imageTo3dMode =
    typeof activeJob?.metadata?.image_to_3d_mode === 'string' ? activeJob.metadata.image_to_3d_mode : null;
  const referenceImageFilename =
    typeof activeJob?.metadata?.reference_image_filename === 'string'
      ? activeJob.metadata.reference_image_filename
      : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#09090b', color: '#f4f4f5', fontFamily: 'sans-serif' }}>
      {/* Topbar */}
      <header style={{ padding: '12px 24px', background: '#18181b', borderBottom: '1px solid #27272a', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <Box color="#3b82f6" size={26} />
          <div>
            <h1 style={{ fontSize: '18px', fontWeight: 'bold', margin: 0 }}>AI 3D STUDIO</h1>
            <span style={{ fontSize: '11px', color: '#71717a' }}>v2.2 Multimodal • 100% Local (127.0.0.1) • Convenção Nativa Y-up</span>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <span style={{ fontSize: '13px', color: '#a1a1aa' }}>Projeto:</span>
          <select
            value={currentProject?.id || ''}
            onChange={(e) => {
              const p = projects.find((proj) => proj.id === e.target.value);
              if (p) {
                selectProjectAndLoadModel(p);
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
        {/* Left Sidebar: Controls, Status, Telemetry & Multiformat Export */}
        <aside style={{ width: '405px', background: '#121215', borderRight: '1px solid #27272a', padding: '16px', overflowY: 'auto' }}>
          <GenerationPanel
            onGenerate={handleGenerate}
            onGenerateTextTo3D={handleGenerateTextTo3D}
            onGenerateImageTo3D={handleGenerateImageTo3D}
            onCancel={handleCancelActiveJob}
            isLoading={isLoading}
            activeJobStatus={activeJob?.status || null}
          />

          {/* Alerta de Erro Claro em Português */}
          {errorMessage && (
            <div
              style={{
                marginTop: '12px',
                background: '#450a0a',
                border: '1px solid #dc2626',
                borderRadius: '8px',
                padding: '12px',
                color: '#fecaca',
                fontSize: '12px',
                display: 'flex',
                gap: '8px',
                alignItems: 'flex-start',
              }}
            >
              <AlertTriangle size={16} color="#f87171" style={{ flexShrink: 0, marginTop: '2px' }} />
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, marginBottom: '2px' }}>Atenção</div>
                <div>{errorMessage}</div>
              </div>
            </div>
          )}

          {/* Card de Status da Tarefa Ativa / Recente */}
          {activeJob && (
            <div style={{ marginTop: '12px', background: '#18181b', padding: '12px 14px', borderRadius: '8px', border: '1px solid #27272a', fontSize: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                <span style={{ color: '#a1a1aa' }}>
                  Tarefa (<code>{activeJob.operation_type}</code>): <code>{activeJob.id}</code>
                </span>
                <span
                  style={{
                    padding: '2px 8px',
                    borderRadius: '999px',
                    fontWeight: 600,
                    fontSize: '11px',
                    background:
                      activeJob.status === 'Concluída'
                        ? '#064e3b'
                        : activeJob.status === 'Cancelada' || activeJob.status === 'Falhou'
                        ? '#7f1d1d'
                        : '#1e3a8a',
                    color:
                      activeJob.status === 'Concluída'
                        ? '#6ee7b7'
                        : activeJob.status === 'Cancelada' || activeJob.status === 'Falhou'
                        ? '#fca5a5'
                        : '#93c5fd',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '4px',
                  }}
                >
                  {activeJob.status === 'Concluída' && <CheckCircle2 size={12} />}
                  {(activeJob.status === 'Cancelada' || activeJob.status === 'Falhou') && <XCircle size={12} />}
                  {activeJob.status}
                </span>
              </div>
              {typeof activeJob.progress === 'number' && (
                <div style={{ width: '100%', height: '6px', background: '#27272a', borderRadius: '3px', overflow: 'hidden' }}>
                  <div
                    style={{
                      width: `${Math.min(100, Math.max(0, Math.round(activeJob.progress * 100)))}%`,
                      height: '100%',
                      background: activeJob.status === 'Concluída' ? '#10b981' : '#3b82f6',
                      transition: 'width 0.2s ease',
                    }}
                  />
                </div>
              )}
            </div>
          )}

          {/* Telemetria Real da Malha + Telemetria Semântica / Multimodal (Bloco 8) */}
          {telemetry && (
            <div style={{ marginTop: '14px', background: '#18181b', padding: '14px', borderRadius: '8px', border: '1px solid #27272a' }}>
              <h4 style={{ fontSize: '14px', fontWeight: 600, margin: '0 0 10px 0', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Info size={16} color="#10b981" /> Métricas e Telemetria Real (Y-up)
              </h4>
              <div style={{ fontSize: '12px', color: '#d4d4d8', display: 'flex', flexDirection: 'column', gap: '5px' }}>
                <div><strong>Vértices (Buffer WebGL):</strong> {telemetry.vertexCount.toLocaleString()}</div>
                <div><strong>Faces / Triângulos:</strong> {telemetry.faceCount.toLocaleString()}</div>
                <div>
                  <strong>Dimensões (X × Y × Z):</strong>{' '}
                  {telemetry.dimensions[0]}m × {telemetry.dimensions[1]}m (Altura) × {telemetry.dimensions[2]}m
                </div>
                <div>
                  <strong>Limites Y (Solo XZ):</strong> Y<sub>min</sub> = {telemetry.boundsMin[1]}m → Y<sub>máx</sub> = {telemetry.boundsMax[1]}m
                </div>
                <div>
                  <strong>Convenção:</strong>{' '}
                  <span style={{ color: '#34d399', fontWeight: 600 }}>
                    {telemetry.coordinateSystem === 'legacy_z_up' ? 'Legado Z-up (Normalizado p/ Y-up)' : 'Y-up Nativo (glTF 2.0)'}
                  </span>
                </div>
                {activeInspection && typeof activeInspection.is_watertight === 'boolean' && (
                  <div>
                    <strong>Malha Estanque (Watertight):</strong> {activeInspection.is_watertight ? 'Sim' : 'Não'}
                  </div>
                )}

                {/* Metadados Semânticos Text-to-3D */}
                {parsedIntent && (
                  <div style={{ marginTop: '6px', paddingTop: '6px', borderTop: '1px solid #27272a' }}>
                    <div>
                      <strong>Intenção Semântica (Text-to-3D):</strong>{' '}
                      <span style={{ color: '#60a5fa', fontWeight: 600 }}>{parsedIntent}</span>
                    </div>
                    {detectedComponentsCount !== null && (
                      <div>
                        <strong>Componentes na IR:</strong> {detectedComponentsCount}
                      </div>
                    )}
                    {detectedColor && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <strong>Cor / Material:</strong>
                        <span
                          style={{
                            display: 'inline-block',
                            width: '10px',
                            height: '10px',
                            borderRadius: '2px',
                            background: detectedColor,
                            border: '1px solid #52525b',
                          }}
                        />
                        <code>{detectedColor}</code>
                      </div>
                    )}
                    {extractedDimensions && Object.keys(extractedDimensions).length > 0 && (
                      <div>
                        <strong>Dimensões Extraídas:</strong>{' '}
                        {Object.entries(extractedDimensions)
                          .map(([k, v]) => `${k}: ${v}`)
                          .join(' • ')}
                      </div>
                    )}
                  </div>
                )}

                {/* Metadados Image-to-3D */}
                {imageTo3dMode && (
                  <div style={{ marginTop: '6px', paddingTop: '6px', borderTop: '1px solid #27272a' }}>
                    <div>
                      <strong>Modo Image-to-3D:</strong>{' '}
                      <span style={{ color: '#60a5fa', fontWeight: 600 }}>
                        {imageTo3dMode === 'heightmap' ? 'Mapa de Relevo (Heightmap)' : 'Extrusão de Silhueta 2D'}
                      </span>
                    </div>
                    {referenceImageFilename && currentProject && (
                      <div style={{ marginTop: '6px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <img
                          src={apiService.getReferenceImageUrl(currentProject.id, referenceImageFilename)}
                          alt="Referência 2D"
                          style={{
                            width: '44px',
                            height: '44px',
                            objectFit: 'contain',
                            borderRadius: '4px',
                            background: '#09090b',
                            border: '1px solid #3f3f46',
                          }}
                        />
                        <div style={{ fontSize: '11px', color: '#a1a1aa', wordBreak: 'break-all' }}>
                          Ref.: <code>{referenceImageFilename}</code>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Exportação e Download Multiformato Contextual Seguro (GLB, OBJ, STL) */}
          {currentProject?.active_model_path && (
            <div style={{ marginTop: '14px', background: '#18181b', padding: '14px', borderRadius: '8px', border: '1px solid #27272a' }}>
              <h4 style={{ fontSize: '14px', fontWeight: 600, margin: '0 0 10px 0' }}>
                Exportar e Baixar Artefato Validado
              </h4>

              <div style={{ marginBottom: '10px' }}>
                <label style={{ display: 'block', fontSize: '12px', color: '#a1a1aa', marginBottom: '4px' }}>
                  Formato de Exportação:
                </label>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '6px' }}>
                  {(['glb', 'obj', 'stl'] as SupportedExportFormat[]).map((fmt) => {
                    const isSelected = selectedExportFormat === fmt;
                    const isReadyOnDisk = Boolean(availableFormats[fmt]);
                    return (
                      <button
                        key={fmt}
                        type="button"
                        onClick={() => setSelectedExportFormat(fmt)}
                        style={{
                          padding: '7px 8px',
                          borderRadius: '6px',
                          border: isSelected ? '1px solid #10b981' : '1px solid #3f3f46',
                          background: isSelected ? '#064e3b' : '#27272a',
                          color: '#fff',
                          fontWeight: 600,
                          fontSize: '12px',
                          cursor: 'pointer',
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                          gap: '2px',
                        }}
                      >
                        <span>.{fmt.toUpperCase()}</span>
                        <span style={{ fontSize: '10px', color: isReadyOnDisk ? '#6ee7b7' : '#a1a1aa', fontWeight: 400 }}>
                          {isReadyOnDisk ? 'Disponível' : 'Gerar sob demanda'}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>

              <button
                type="button"
                disabled={isExporting || isLoading}
                onClick={handleExportAndDownload}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '8px',
                  padding: '9px',
                  background: isExporting ? '#05966988' : '#059669',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '6px',
                  fontWeight: 600,
                  fontSize: '13px',
                  cursor: isExporting || isLoading ? 'not-allowed' : 'pointer',
                }}
              >
                <Download size={16} />
                {isExporting
                  ? `Exportando .${selectedExportFormat.toUpperCase()}...`
                  : `Baixar Arquivo .${selectedExportFormat.toUpperCase()} Validado`}
              </button>

              <div style={{ marginTop: '8px', fontSize: '11px', color: '#71717a', wordBreak: 'break-all' }}>
                Rota segura: <code>/api/v1/projects/{currentProject.id}/artifacts/{availableFormats[selectedExportFormat] || extractFilenameFromPath(currentProject.active_model_path).replace(/\.glb$/i, `.${selectedExportFormat}`)}</code>
              </div>
            </div>
          )}
        </aside>

        {/* Center: 3D WebGL Viewport */}
        <main style={{ flex: 1, position: 'relative', display: 'flex', flexDirection: 'column' }}>
          {/* Viewport Toolbar */}
          <div style={{ position: 'absolute', top: '16px', left: '16px', zIndex: 10, display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            <button
              onClick={() => {
                if (viewerRef.current) {
                  const state = viewerRef.current.toggleWireframe();
                  setIsWireframe(state);
                }
              }}
              style={{ padding: '6px 10px', background: '#18181bcc', backdropFilter: 'blur(4px)', color: '#fff', border: '1px solid #3f3f46', borderRadius: '4px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px' }}
            >
              <Eye size={14} /> {isWireframe ? 'Modo Sólido' : 'Modo Aramado'}
            </button>
            <button
              onClick={() => viewerRef.current?.toggleGrid()}
              style={{ padding: '6px 10px', background: '#18181bcc', backdropFilter: 'blur(4px)', color: '#fff', border: '1px solid #3f3f46', borderRadius: '4px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px' }}
            >
              <Grid size={14} /> Grade XZ
            </button>
            <button
              onClick={() => viewerRef.current?.toggleAxes()}
              style={{ padding: '6px 10px', background: '#18181bcc', backdropFilter: 'blur(4px)', color: '#fff', border: '1px solid #3f3f46', borderRadius: '4px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px' }}
            >
              <Compass size={14} /> Eixos Y-up
            </button>
            <button
              onClick={() => viewerRef.current?.fitCameraToCurrentModel()}
              style={{ padding: '6px 10px', background: '#18181bcc', color: '#fff', border: '1px solid #3f3f46', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}
            >
              Enquadrar
            </button>
            <button
              onClick={() => viewerRef.current?.setView('front')}
              style={{ padding: '6px 10px', background: '#18181bcc', color: '#fff', border: '1px solid #3f3f46', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}
            >
              Frente
            </button>
            <button
              onClick={() => viewerRef.current?.setView('back')}
              style={{ padding: '6px 10px', background: '#18181bcc', color: '#fff', border: '1px solid #3f3f46', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}
            >
              Trás
            </button>
            <button
              onClick={() => viewerRef.current?.setView('left')}
              style={{ padding: '6px 10px', background: '#18181bcc', color: '#fff', border: '1px solid #3f3f46', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}
            >
              Esquerda
            </button>
            <button
              onClick={() => viewerRef.current?.setView('right')}
              style={{ padding: '6px 10px', background: '#18181bcc', color: '#fff', border: '1px solid #3f3f46', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}
            >
              Direita
            </button>
            <button
              onClick={() => viewerRef.current?.setView('top')}
              style={{ padding: '6px 10px', background: '#18181bcc', color: '#fff', border: '1px solid #3f3f46', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}
            >
              Topo (+Y)
            </button>
            <button
              onClick={() => viewerRef.current?.setView('bottom')}
              style={{ padding: '6px 10px', background: '#18181bcc', color: '#fff', border: '1px solid #3f3f46', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}
            >
              Base (-Y)
            </button>
            <button
              onClick={() => viewerRef.current?.setView('iso')}
              style={{ padding: '6px 10px', background: '#18181bcc', color: '#fff', border: '1px solid #3f3f46', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}
            >
              Iso
            </button>
          </div>

          {/* Legenda Visual de Eixos Y-up */}
          <div
            style={{
              position: 'absolute',
              top: '16px',
              right: '16px',
              zIndex: 10,
              padding: '6px 10px',
              background: '#18181bcc',
              backdropFilter: 'blur(4px)',
              border: '1px solid #3f3f46',
              borderRadius: '6px',
              fontSize: '11px',
              display: 'flex',
              gap: '10px',
              alignItems: 'center',
            }}
          >
            <span style={{ color: '#ef4444', fontWeight: 600 }}>● X: Largura</span>
            <span style={{ color: '#22c55e', fontWeight: 600 }}>● Y: Altura (Cima)</span>
            <span style={{ color: '#3b82f6', fontWeight: 600 }}>● Z: Profundidade</span>
          </div>

          <div style={{ flex: 1, width: '100%', height: '100%' }}>
            <ModelViewer
              modelUrl={modelUrl}
              coordinateSystem={coordinateSystem}
              jobMetadata={activeJob?.metadata || null}
              viewerRef={viewerRef}
              onMeshLoaded={(info) => setTelemetry(info)}
            />
          </div>

          {/* Bottom Status Bar */}
          <footer style={{ padding: '6px 16px', background: '#18181b', borderTop: '1px solid #27272a', fontSize: '12px', color: '#a1a1aa', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>Status: <span style={{ color: '#60a5fa' }}>{statusMessage}</span></div>
            <div>Controles: Botão Esquerdo (Órbita) • Botão Direito (Pan) • Scroll (Zoom) • Plano Base XZ (Y=0)</div>
          </footer>
        </main>
      </div>
    </div>
  );
}

export default App;
