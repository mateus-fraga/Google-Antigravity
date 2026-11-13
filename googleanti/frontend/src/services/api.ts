const API_BASE = 'http://127.0.0.1:8000/api/v1';

export type SupportedExportFormat = 'glb' | 'obj' | 'stl';
export type GenerationOperationType = 'procedural_generation' | 'text_to_3d' | 'image_to_3d';
export type ImageTo3dMode = 'silhouette' | 'heightmap';

export interface Project {
  id: string;
  name: string;
  description: string;
  category: string;
  purpose: string;
  strategy: string;
  status?: string;
  created_at: string;
  updated_at: string;
  active_model_path?: string | null;
  coordinate_system?: 'Y-up' | 'legacy_z_up';
  geometry_schema_version?: number;
}

export interface JobInspectionMetadata {
  vertex_count?: number;
  face_count?: number;
  bounds?: [[number, number, number], [number, number, number]];
  dimensions?: [number, number, number];
  is_watertight?: boolean;
  volume?: number | null;
  area?: number;
  coordinate_system?: string;
  geometry_schema_version?: number;
}

export interface JobMetadata {
  coordinate_system?: string;
  geometry_schema_version?: number;
  inspection?: JobInspectionMetadata;
  export?: Record<string, unknown>;
  // Text-to-3D semantic metadata
  parsed_intent?: string;
  detected_components_count?: number;
  extracted_dimensions?: Record<string, number>;
  detected_color?: string | null;
  prompt?: string;
  ir_id?: string;
  text_to_3d?: Record<string, unknown>;
  // Image-to-3D metadata
  image_to_3d_mode?: ImageTo3dMode;
  reference_image_filename?: string;
  thickness?: number;
  resolution_scale?: number;
  base_thickness?: number;
  relief_depth?: number;
  image_url?: string;
  [key: string]: unknown;
}

export interface Job {
  id: string;
  project_id: string;
  operation_type: GenerationOperationType | string;
  status: string;
  progress?: number | null;
  error_message?: string | null;
  result_files: string[];
  metadata: JobMetadata;
}

export interface ReferenceImageUploadResponse {
  project_id: string;
  filename: string;
  relative_path: string;
  format: string;
  width: number;
  height: number;
  size_bytes: number;
  image_url: string;
}

export interface ImageTo3dJobParams {
  reference_image_filename: string;
  mode: ImageTo3dMode;
  thickness?: number;
  resolution_scale?: number;
  base_thickness?: number;
  relief_depth?: number;
  [key: string]: unknown;
}

export interface ProjectArtifactInfo {
  filename: string;
  format: string;
  size_bytes: number;
  download_url: string;
}

export interface ProjectArtifactsResponse {
  project_id: string;
  active_filename: string | null;
  active_stem: string | null;
  active_formats: Record<string, string>;
  artifacts: ProjectArtifactInfo[];
}

export interface ExportFormatResponse {
  project_id: string;
  format: SupportedExportFormat;
  filename: string;
  relative_path: string;
  download_url: string;
  file_size_bytes?: number;
  validated: boolean;
}

async function parseApiError(res: Response, fallbackMessage: string): Promise<string> {
  try {
    const data = await res.json();
    if (data && typeof data === 'object') {
      if (typeof data.detail === 'string') {
        return data.detail;
      }
      if (Array.isArray(data.detail) && data.detail.length > 0) {
        const messages = data.detail.map((item: { msg?: string; loc?: unknown[] }) => {
          const rawMsg = item.msg ? item.msg.replace(/^Value error,\s*/i, '') : 'Valor inválido';
          return rawMsg;
        });
        return messages.join(' | ');
      }
    }
  } catch {
    // Ignorar falha de parse JSON e retornar fallback
  }
  return `${fallbackMessage} (HTTP ${res.status})`;
}

export function extractFilenameFromPath(relativePath: string): string {
  const normalized = relativePath.replace(/\\/g, '/').trim();
  const parts = normalized.split('/').filter(Boolean);
  return parts.length > 0 ? parts[parts.length - 1] : normalized;
}

export const apiService = {
  async listProjects(): Promise<Project[]> {
    const res = await fetch(`${API_BASE}/projects`);
    if (!res.ok) throw new Error(await parseApiError(res, 'Falha ao listar projetos'));
    return res.json();
  },

  async getProject(projectId: string): Promise<Project> {
    const res = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}`);
    if (!res.ok) throw new Error(await parseApiError(res, 'Falha ao carregar dados do projeto'));
    return res.json();
  },

  async createProject(data: { name: string; description?: string; category?: string; purpose?: string }): Promise<Project> {
    const res = await fetch(`${API_BASE}/projects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error(await parseApiError(res, 'Falha ao criar projeto'));
    return res.json();
  },

  async startProceduralJob(
    projectId: string,
    params: Record<string, unknown>,
    operationType: GenerationOperationType = 'procedural_generation'
  ): Promise<Job> {
    const res = await fetch(`${API_BASE}/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_id: projectId,
        operation_type: operationType,
        params,
      }),
    });
    if (!res.ok) {
      throw new Error(await parseApiError(res, 'Parâmetros inválidos ou falha ao iniciar tarefa de geração'));
    }
    return res.json();
  },

  async startTextTo3dJob(
    projectId: string,
    prompt: string,
    extraParams?: Record<string, unknown>
  ): Promise<Job> {
    return this.startProceduralJob(
      projectId,
      {
        prompt,
        ...(extraParams || {}),
      },
      'text_to_3d'
    );
  },

  async uploadReferenceImage(projectId: string, file: File): Promise<ReferenceImageUploadResponse> {
    const formData = new FormData();
    formData.append('file', file);

    const res = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/images`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) {
      throw new Error(await parseApiError(res, 'Falha ao enviar imagem de referência'));
    }
    return res.json();
  },

  async startImageTo3dJob(projectId: string, params: ImageTo3dJobParams): Promise<Job> {
    return this.startProceduralJob(projectId, params, 'image_to_3d');
  },

  async getJob(jobId: string): Promise<Job> {
    const res = await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}`);
    if (!res.ok) throw new Error(await parseApiError(res, 'Falha ao consultar status da tarefa'));
    return res.json();
  },

  async cancelJob(jobId: string): Promise<{ message: string }> {
    const res = await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });
    if (!res.ok) throw new Error(await parseApiError(res, 'Falha ao solicitar cancelamento da tarefa'));
    return res.json();
  },

  async listProjectArtifacts(projectId: string): Promise<ProjectArtifactsResponse> {
    const res = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/artifacts`);
    if (!res.ok) throw new Error(await parseApiError(res, 'Falha ao verificar artefatos do projeto'));
    return res.json();
  },

  async exportProjectModelFormat(projectId: string, format: SupportedExportFormat): Promise<ExportFormatResponse> {
    const res = await fetch(
      `${API_BASE}/projects/${encodeURIComponent(projectId)}/export/${encodeURIComponent(format)}`,
      { method: 'POST' }
    );
    if (!res.ok) throw new Error(await parseApiError(res, `Falha ao exportar modelo para ${format.toUpperCase()}`));
    return res.json();
  },

  /**
   * SEC-001 (Task 4.3 / 4.4): Constrói a URL contextual segura de artefato do projeto:
   * `/api/v1/projects/{project_id}/artifacts/{filename}`
   */
  getArtifactDownloadUrl(projectId: string, filenameOrRelativePath: string): string {
    const filename = extractFilenameFromPath(filenameOrRelativePath);
    return `${API_BASE}/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(filename)}`;
  },

  /**
   * Bloco 7 / 8: Constrói a URL contextual segura para exibição da imagem de referência do projeto:
   * `/api/v1/projects/{project_id}/images/{filename}`
   */
  getReferenceImageUrl(projectId: string, filenameOrRelativePath: string): string {
    const filename = extractFilenameFromPath(filenameOrRelativePath);
    return `${API_BASE}/projects/${encodeURIComponent(projectId)}/images/${encodeURIComponent(filename)}`;
  },

  /**
   * Mantido apenas para compatibilidade caso um caminho relativo completo `projects/{project_id}/{filename}`
   * seja passado; extrai `project_id` e `filename` e direciona para a rota contextual segura.
   */
  getFileDownloadUrl(relativePath: string, projectId?: string): string {
    if (projectId) {
      return this.getArtifactDownloadUrl(projectId, relativePath);
    }
    const normalized = relativePath.replace(/\\/g, '/').trim();
    const parts = normalized.split('/').filter(Boolean);
    if (parts.length >= 3 && parts[0] === 'projects') {
      return this.getArtifactDownloadUrl(parts[1], parts[parts.length - 1]);
    }
    if (parts.length === 2) {
      return this.getArtifactDownloadUrl(parts[0], parts[1]);
    }
    return `${API_BASE}/files/download?path=${encodeURIComponent(relativePath)}`;
  },
};
