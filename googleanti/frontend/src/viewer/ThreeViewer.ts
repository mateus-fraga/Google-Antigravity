import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

export type CameraPresetView = 'front' | 'back' | 'left' | 'right' | 'side' | 'top' | 'bottom' | 'iso';

export interface MeshTelemetryInfo {
  vertexCount: number;
  faceCount: number;
  dimensions: [number, number, number];
  boundsMin: [number, number, number];
  boundsMax: [number, number, number];
  coordinateSystem: 'Y-up' | 'legacy_z_up';
}

export interface ViewerOptions {
  container: HTMLDivElement;
  onMeshLoaded?: (info: MeshTelemetryInfo) => void;
  onError?: (message: string | null) => void;
}

const TEXTURE_MAP_KEYS = [
  'map',
  'alphaMap',
  'aoMap',
  'bumpMap',
  'displacementMap',
  'emissiveMap',
  'envMap',
  'lightMap',
  'metalnessMap',
  'normalMap',
  'roughnessMap',
  'specularMap',
] as const;

export class ThreeViewer {
  private container: HTMLDivElement;
  private scene: THREE.Scene;
  private camera: THREE.PerspectiveCamera;
  private renderer: THREE.WebGLRenderer | null = null;
  private controls: OrbitControls | null = null;
  private grid: THREE.GridHelper;
  private axesGroup: THREE.Group;
  private currentMeshGroup: THREE.Group;
  private loader: GLTFLoader;
  private animationFrameId: number | null = null;
  private isWireframe: boolean = false;
  private isDestroyed: boolean = false;
  private loadRequestId: number = 0;
  private onMeshLoaded?: (info: MeshTelemetryInfo) => void;
  private onError?: (message: string | null) => void;

  constructor(options: ViewerOptions) {
    this.container = options.container;
    this.onMeshLoaded = options.onMeshLoaded;
    this.onError = options.onError;

    // Cena (convenção Y-up nativa do Three.js / glTF 2.0)
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x18181b); // Zinc-900

    // Câmera com vetor up explícito em +Y
    const width = this.container.clientWidth || 800;
    const height = this.container.clientHeight || 600;
    this.camera = new THREE.PerspectiveCamera(45, width / height, 0.05, 2000);
    this.camera.up.set(0, 1, 0);
    this.camera.position.set(3, 2.5, 4);

    // Grade de referência no plano horizontal XZ (y = 0)
    this.grid = new THREE.GridHelper(12, 24, 0x3f3f46, 0x27272a);
    this.grid.position.set(0, 0, 0);
    this.grid.userData = { permanentHelper: true };
    this.scene.add(this.grid);

    // Indicador de eixos orientados Y-up (X = Vermelho, Y = Verde/Vertical, Z = Azul)
    this.axesGroup = this.createLabeledAxesGroup(1.8);
    this.axesGroup.userData = { permanentHelper: true };
    this.scene.add(this.axesGroup);

    // Grupo exclusivo para modelos carregados dinamicamente (separado dos helpers permanentes)
    this.currentMeshGroup = new THREE.Group();
    this.currentMeshGroup.name = 'LoadedModelGroup';
    this.scene.add(this.currentMeshGroup);

    // Iluminação permanente da cena
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.85);
    ambientLight.userData = { permanentHelper: true };
    this.scene.add(ambientLight);

    const dirLight1 = new THREE.DirectionalLight(0xffffff, 1.25);
    dirLight1.position.set(5, 10, 7);
    dirLight1.castShadow = true;
    dirLight1.userData = { permanentHelper: true };
    this.scene.add(dirLight1);

    const dirLight2 = new THREE.DirectionalLight(0x90b0ef, 0.6);
    dirLight2.position.set(-5, -2, -5);
    dirLight2.userData = { permanentHelper: true };
    this.scene.add(dirLight2);

    this.loader = new GLTFLoader();

    // Inicialização protegida do WebGLRenderer (MEM-001)
    try {
      this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
      this.renderer.setSize(width, height);
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      this.renderer.shadowMap.enabled = true;
      this.container.appendChild(this.renderer.domElement);

      this.controls = new OrbitControls(this.camera, this.renderer.domElement);
      this.controls.enableDamping = true;
      this.controls.dampingFactor = 0.05;

      window.addEventListener('resize', this.onWindowResize);
      this.animate();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error('Falha ao inicializar contexto WebGL:', err);
      if (this.onError) {
        this.onError(`Não foi possível inicializar o acelerador gráfico WebGL no navegador: ${msg}`);
      }
    }
  }

  private createAxisLabelSprite(text: string, colorHex: string, position: THREE.Vector3): THREE.Sprite {
    const canvas = document.createElement('canvas');
    canvas.width = 64;
    canvas.height = 64;
    const ctx = canvas.getContext('2d');
    if (ctx) {
      ctx.clearRect(0, 0, 64, 64);
      ctx.font = 'bold 34px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = colorHex;
      ctx.fillText(text, 32, 32);
    }
    const texture = new THREE.CanvasTexture(canvas);
    const material = new THREE.SpriteMaterial({ map: texture, depthTest: false });
    const sprite = new THREE.Sprite(material);
    sprite.position.copy(position);
    sprite.scale.set(0.28, 0.28, 0.28);
    return sprite;
  }

  private createLabeledAxesGroup(size: number): THREE.Group {
    const group = new THREE.Group();
    group.name = 'PermanentAxesGroup';
    const axes = new THREE.AxesHelper(size);
    // Elevar sutilmente (0.5mm) para evitar z-fighting com a grade XZ
    axes.position.set(0, 0.0005, 0);
    group.add(axes);

    group.add(this.createAxisLabelSprite('X', '#ef4444', new THREE.Vector3(size + 0.18, 0.05, 0)));
    group.add(this.createAxisLabelSprite('Y (Cima)', '#22c55e', new THREE.Vector3(0, size + 0.2, 0)));
    group.add(this.createAxisLabelSprite('Z', '#3b82f6', new THREE.Vector3(0, 0.05, size + 0.18)));
    return group;
  }

  private onWindowResize = () => {
    if (this.isDestroyed || !this.container || !this.renderer) return;
    const width = this.container.clientWidth || 800;
    const height = this.container.clientHeight || 600;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  };

  private animate = () => {
    if (this.isDestroyed || !this.renderer) return;
    this.animationFrameId = requestAnimationFrame(this.animate);
    if (this.controls) {
      this.controls.update();
    }
    this.renderer.render(this.scene, this.camera);
  };

  /**
   * MEM-001 (Task 4.1): Descarte recursivo e profundo de geometrias (`BufferGeometry.dispose()`),
   * materiais (`Material.dispose()`, único ou array) e todas as texturas associadas.
   * Protege estritamente helpers permanentes da cena (`permanentHelper: true`) quando `includePermanentHelpers = false`.
   */
  public disposeHierarchy(root: THREE.Object3D, includePermanentHelpers: boolean = false) {
    root.traverse((child) => {
      if (!includePermanentHelpers && child.userData?.permanentHelper) {
        return;
      }

      const anyChild = child as THREE.Mesh | THREE.Line | THREE.Points | THREE.Sprite;
      if ('geometry' in anyChild && anyChild.geometry) {
        anyChild.geometry.dispose();
      }

      if ('material' in anyChild && anyChild.material) {
        const materials = Array.isArray(anyChild.material) ? anyChild.material : [anyChild.material];
        for (const mat of materials) {
          if (!mat) continue;
          const matRecord = mat as unknown as Record<string, unknown>;
          for (const key of TEXTURE_MAP_KEYS) {
            const tex = matRecord[key];
            if (tex && typeof (tex as THREE.Texture).dispose === 'function') {
              (tex as THREE.Texture).dispose();
            }
          }
          if (typeof mat.dispose === 'function') {
            mat.dispose();
          }
        }
      }
    });
  }

  /**
   * Remove e descarta completamente o modelo atual do `currentMeshGroup`,
   * preservando intactos a grade XZ, os eixos Y-up e as luzes da cena.
   */
  public clearCurrentModel() {
    while (this.currentMeshGroup.children.length > 0) {
      const obj = this.currentMeshGroup.children[0];
      this.disposeHierarchy(obj, false);
      this.currentMeshGroup.remove(obj);
    }
  }

  /**
   * Carrega um modelo GLB a partir da URL contextual segura, protegendo contra:
   * - Vazamento de memória WebGL (descarta o modelo anterior via `clearCurrentModel`);
   * - Condições de corrida em trocas rápidas de projeto/modelo (`loadRequestId`);
   * - Dupla rotação de modelos: aplica rotação de compatibilidade Z-up -> Y-up SOMENTE se
   *   `coordinateSystem === 'legacy_z_up'` (modelos nativos `Y-up` são exibidos diretamente).
   */
  public loadModelFromUrl(url: string, coordinateSystem: 'Y-up' | 'legacy_z_up' = 'Y-up') {
    const requestId = ++this.loadRequestId;
    if (this.onError) {
      this.onError(null);
    }

    this.loader.load(
      url,
      (gltf) => {
        // Se o componente foi desmontado ou outro carregamento mais recente foi iniciado,
        // descartar imediatamente a geometria recém-carregada e abortar (evita race condition!)
        if (this.isDestroyed || requestId !== this.loadRequestId) {
          this.disposeHierarchy(gltf.scene, false);
          return;
        }

        // Descartar modelo anterior da memória GPU antes de anexar o novo
        this.clearCurrentModel();

        // Compatibilidade retroativa (Task 3.3 / 4.2):
        // Converter visualmente de Z-up para Y-up SOMENTE se o projeto for explicitamente legado (`legacy_z_up`),
        // sem nunca aplicar rotação duplicada em modelos nativos Y-up.
        if (coordinateSystem === 'legacy_z_up' && !gltf.scene.userData?.convertedFromLegacyZUp) {
          gltf.scene.rotation.x = -Math.PI / 2;
          gltf.scene.updateMatrixWorld(true);
          const preBox = new THREE.Box3().setFromObject(gltf.scene);
          if (Number.isFinite(preBox.min.y) && Math.abs(preBox.min.y) > 1e-5) {
            gltf.scene.position.y -= preBox.min.y;
          }
          gltf.scene.userData = { ...gltf.scene.userData, convertedFromLegacyZUp: true };
        }

        let totalVertices = 0;
        let totalFaces = 0;

        gltf.scene.traverse((child) => {
          if ((child as THREE.Mesh).isMesh) {
            const mesh = child as THREE.Mesh;
            mesh.castShadow = true;
            mesh.receiveShadow = true;

            if (this.isWireframe) {
              const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
              mats.forEach((m) => {
                if (m && 'wireframe' in m) {
                  (m as THREE.MeshStandardMaterial).wireframe = true;
                }
              });
            }

            const geometry = mesh.geometry;
            if (geometry) {
              const pos = geometry.attributes.position;
              if (pos) totalVertices += pos.count;
              if (geometry.index) {
                totalFaces += geometry.index.count / 3;
              } else if (pos) {
                totalFaces += pos.count / 3;
              }
            }
          }
        });

        this.currentMeshGroup.add(gltf.scene);
        gltf.scene.updateMatrixWorld(true);

        const bbox = this.fitCameraToCurrentModel();

        if (this.onMeshLoaded && bbox) {
          const size = bbox.getSize(new THREE.Vector3());
          this.onMeshLoaded({
            vertexCount: totalVertices,
            faceCount: Math.round(totalFaces),
            dimensions: [
              Number(size.x.toFixed(3)),
              Number(size.y.toFixed(3)),
              Number(size.z.toFixed(3)),
            ],
            boundsMin: [
              Number(bbox.min.x.toFixed(3)),
              Number(bbox.min.y.toFixed(3)),
              Number(bbox.min.z.toFixed(3)),
            ],
            boundsMax: [
              Number(bbox.max.x.toFixed(3)),
              Number(bbox.max.y.toFixed(3)),
              Number(bbox.max.z.toFixed(3)),
            ],
            coordinateSystem,
          });
        }
      },
      undefined,
      (error) => {
        if (this.isDestroyed || requestId !== this.loadRequestId) return;
        console.error('Erro ao carregar modelo GLB:', error);
        if (this.onError) {
          this.onError('Falha ao carregar o artefato 3D no visualizador. Verifique se o arquivo GLB é válido e pertence ao projeto ativo.');
        }
      }
    );
  }

  public fitCameraToCurrentModel(): THREE.Box3 | null {
    if (this.currentMeshGroup.children.length === 0) return null;
    const bbox = new THREE.Box3().setFromObject(this.currentMeshGroup);
    if (bbox.isEmpty()) return null;

    const center = bbox.getCenter(new THREE.Vector3());
    const size = bbox.getSize(new THREE.Vector3());

    const maxDim = Math.max(size.x, size.y, size.z, 0.1);
    const fov = this.camera.fov * (Math.PI / 180);
    let cameraDist = Math.abs(maxDim / 2 / Math.tan(fov / 2)) * 1.65;
    cameraDist = Math.max(cameraDist, 1.8);

    this.camera.up.set(0, 1, 0);
    this.camera.position.set(center.x + cameraDist, center.y + cameraDist * 0.8, center.z + cameraDist);
    this.camera.lookAt(center);
    if (this.controls) {
      this.controls.target.copy(center);
      this.controls.update();
    }
    return bbox;
  }

  public setView(view: CameraPresetView) {
    const target = this.controls ? this.controls.target.clone() : new THREE.Vector3(0, 0.5, 0);
    const dist = Math.max(this.camera.position.distanceTo(target) || 4, 1.5);
    this.camera.up.set(0, 1, 0);

    switch (view) {
      case 'front':
        this.camera.position.set(target.x, target.y, target.z + dist);
        break;
      case 'back':
        this.camera.position.set(target.x, target.y, target.z - dist);
        break;
      case 'right':
      case 'side':
        this.camera.position.set(target.x + dist, target.y, target.z);
        break;
      case 'left':
        this.camera.position.set(target.x - dist, target.y, target.z);
        break;
      case 'top':
        this.camera.position.set(target.x, target.y + dist, target.z + 0.001);
        break;
      case 'bottom':
        this.camera.position.set(target.x, target.y - dist, target.z + 0.001);
        break;
      case 'iso':
        this.camera.position.set(target.x + dist * 0.7, target.y + dist * 0.7, target.z + dist * 0.7);
        break;
    }
    this.camera.lookAt(target);
    if (this.controls) {
      this.controls.update();
    }
  }

  public toggleWireframe(): boolean {
    this.isWireframe = !this.isWireframe;
    this.currentMeshGroup.traverse((child) => {
      if ((child as THREE.Mesh).isMesh) {
        const mesh = child as THREE.Mesh;
        if (Array.isArray(mesh.material)) {
          mesh.material.forEach((m) => {
            if (m && 'wireframe' in m) {
              (m as THREE.MeshStandardMaterial).wireframe = this.isWireframe;
            }
          });
        } else if (mesh.material && 'wireframe' in mesh.material) {
          (mesh.material as THREE.MeshStandardMaterial).wireframe = this.isWireframe;
        }
      }
    });
    return this.isWireframe;
  }

  public toggleGrid(visible?: boolean): boolean {
    this.grid.visible = visible !== undefined ? visible : !this.grid.visible;
    return this.grid.visible;
  }

  public toggleAxes(visible?: boolean): boolean {
    this.axesGroup.visible = visible !== undefined ? visible : !this.axesGroup.visible;
    return this.axesGroup.visible;
  }

  /**
   * MEM-001 (Task 4.1): Liberação determinística de todos os recursos WebGL ao desmontar o componente.
   */
  public destroy() {
    if (this.isDestroyed) return;
    this.isDestroyed = true;
    this.loadRequestId++;

    window.removeEventListener('resize', this.onWindowResize);
    if (this.animationFrameId !== null) {
      cancelAnimationFrame(this.animationFrameId);
      this.animationFrameId = null;
    }

    // Descartar modelos e helpers permanentes
    this.clearCurrentModel();
    this.disposeHierarchy(this.scene, true);

    if (this.controls) {
      this.controls.dispose();
      this.controls = null;
    }

    if (this.renderer) {
      this.renderer.dispose();
      if (this.container && this.renderer.domElement && this.container.contains(this.renderer.domElement)) {
        this.container.removeChild(this.renderer.domElement);
      }
      this.renderer = null;
    }
  }
}

