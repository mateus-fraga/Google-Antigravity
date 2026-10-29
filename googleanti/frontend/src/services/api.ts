const API_BASE = 'http://127.0.0.1:8000/api/v1';

export interface Project {
  id: string;
  name: string;
  description: string;
  category: string;
  purpose: string;
  strategy: string;
  created_at: string;
  updated_at: string;
  active_model_path?: string | null;
}

export interface Job {
  id: string;
  project_id: string;
  operation_type: string;
  status: string;
  progress?: number | null;
  error_message?: string | null;
  result_files: string[];
  metadata: Record<string, any>;
}

export const apiService = {
  async listProjects(): Promise<Project[]> {
    const res = await fetch(`${API_BASE}/projects`);
    if (!res.ok) throw new Error('Falha ao listar projetos');
    return res.json();
  },

  async createProject(data: { name: string; description?: string; category?: string; purpose?: string }): Promise<Project> {
    const res = await fetch(`${API_BASE}/projects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error('Falha ao criar projeto');
    return res.json();
  },

  async startProceduralJob(projectId: string, params: Record<string, any>): Promise<Job> {
    const res = await fetch(`${API_BASE}/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_id: projectId,
        operation_type: 'procedural_generation',
        params,
      }),
    });
    if (!res.ok) throw new Error('Falha ao disparar tarefa de geração');
    return res.json();
  },

  async getJob(jobId: string): Promise<Job> {
    const res = await fetch(`${API_BASE}/jobs/${jobId}`);
    if (!res.ok) throw new Error('Falha ao consultar tarefa');
    return res.json();
  },

  async cancelJob(jobId: string): Promise<void> {
    await fetch(`${API_BASE}/jobs/${jobId}/cancel`, { method: 'POST' });
  },

  getFileDownloadUrl(relativePath: string): string {
    return `${API_BASE}/files/download?path=${encodeURIComponent(relativePath)}`;
  }
};
