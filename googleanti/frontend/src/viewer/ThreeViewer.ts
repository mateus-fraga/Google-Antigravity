import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

export interface ViewerOptions {
  container: HTMLDivElement;
  onMeshLoaded?: (info: { vertexCount: number; faceCount: number; dimensions: [number, number, number] }) => void;
}

export class ThreeViewer {
  private container: HTMLDivElement;
  private scene: THREE.Scene;
  private camera: THREE.PerspectiveCamera;
  private renderer: THREE.WebGLRenderer;
  private controls: OrbitControls;
  private grid: THREE.GridHelper;
  private axes: THREE.AxesHelper;
  private currentMeshGroup: THREE.Group;
  private loader: GLTFLoader;
  private animationFrameId: number | null = null;
  private isWireframe: boolean = false;
  private onMeshLoaded?: (info: { vertexCount: number; faceCount: number; dimensions: [number, number, number] }) => void;

  constructor(options: ViewerOptions) {
    this.container = options.container;
    this.onMeshLoaded = options.onMeshLoaded;

    // Cena
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x18181b); // Zinc-900

    // Câmera
    const width = this.container.clientWidth || 800;
    const height = this.container.clientHeight || 600;
    this.camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
    this.camera.position.set(3, 3, 4);

    // Renderer
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setSize(width, height);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.container.appendChild(this.renderer.domElement);

    // Controles Orbitais
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.05;

    // Iluminação
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
    this.scene.add(ambientLight);

    const dirLight1 = new THREE.DirectionalLight(0xffffff, 1.2);
    dirLight1.position.set(5, 10, 7);
    dirLight1.castShadow = true;
    this.scene.add(dirLight1);

    const dirLight2 = new THREE.DirectionalLight(0x90b0ef, 0.6);
    dirLight2.position.set(-5, -2, -5);
    this.scene.add(dirLight2);

    // Grid e Eixos
    this.grid = new THREE.GridHelper(10, 20, 0x3f3f46, 0x27272a);
    this.scene.add(this.grid);

    this.axes = new THREE.AxesHelper(1.5);
    this.scene.add(this.axes);

    this.currentMeshGroup = new THREE.Group();
    this.scene.add(this.currentMeshGroup);

    this.loader = new GLTFLoader();

    // Eventos e Loop
    window.addEventListener('resize', this.onWindowResize);
    this.animate();
  }

  private onWindowResize = () => {
    if (!this.container) return;
    const width = this.container.clientWidth;
    const height = this.container.clientHeight;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  };

  private animate = () => {
    this.animationFrameId = requestAnimationFrame(this.animate);
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  };

  public loadModelFromUrl(url: string) {
    this.loader.load(
      url,
      (gltf) => {
        // Limpar modelo anterior
        while (this.currentMeshGroup.children.length > 0) {
          const obj = this.currentMeshGroup.children[0];
          this.currentMeshGroup.remove(obj);
        }

        let totalVertices = 0;
        let totalFaces = 0;

        gltf.scene.traverse((child) => {
          if ((child as THREE.Mesh).isMesh) {
            const mesh = child as THREE.Mesh;
            mesh.castShadow = true;
            mesh.receiveShadow = true;

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

        // Enquadramento automático
        const bbox = new THREE.Box3().setFromObject(gltf.scene);
        const center = bbox.getCenter(new THREE.Vector3());
        const size = bbox.getSize(new THREE.Vector3());

        const maxDim = Math.max(size.x, size.y, size.z);
        const fov = this.camera.fov * (Math.PI / 180);
        let cameraZ = Math.abs(maxDim / 2 / Math.tan(fov / 2)) * 1.5;
        cameraZ = Math.max(cameraZ, 2);

        this.camera.position.set(center.x + cameraZ, center.y + cameraZ * 0.8, center.z + cameraZ);
        this.camera.lookAt(center);
        this.controls.target.copy(center);
        this.controls.update();

        if (this.onMeshLoaded) {
          this.onMeshLoaded({
            vertexCount: totalVertices,
            faceCount: Math.round(totalFaces),
            dimensions: [Number(size.x.toFixed(3)), Number(size.y.toFixed(3)), Number(size.z.toFixed(3))]
          });
        }
      },
      undefined,
      (error) => {
        console.error('Erro ao carregar modelo GLB:', error);
      }
    );
  }

  public setView(view: 'front' | 'top' | 'side' | 'iso') {
    const target = this.controls.target.clone();
    const dist = this.camera.position.distanceTo(target) || 5;

    switch (view) {
      case 'front':
        this.camera.position.set(target.x, target.y, target.z + dist);
        break;
      case 'top':
        this.camera.position.set(target.x, target.y + dist, target.z + 0.001);
        break;
      case 'side':
        this.camera.position.set(target.x + dist, target.y, target.z);
        break;
      case 'iso':
        this.camera.position.set(target.x + dist * 0.7, target.y + dist * 0.7, target.z + dist * 0.7);
        break;
    }
    this.camera.lookAt(target);
    this.controls.update();
  }

  public toggleWireframe(): boolean {
    this.isWireframe = !this.isWireframe;
    this.currentMeshGroup.traverse((child) => {
      if ((child as THREE.Mesh).isMesh) {
        const mesh = child as THREE.Mesh;
        if (Array.isArray(mesh.material)) {
          mesh.material.forEach((m) => {
            if ('wireframe' in m) {
              (m as any).wireframe = this.isWireframe;
            }
          });
        } else if (mesh.material && 'wireframe' in mesh.material) {
          (mesh.material as any).wireframe = this.isWireframe;
        }
      }
    });
    return this.isWireframe;
  }

  public toggleGrid(visible?: boolean): boolean {
    this.grid.visible = visible !== undefined ? visible : !this.grid.visible;
    return this.grid.visible;
  }

  public destroy() {
    window.removeEventListener('resize', this.onWindowResize);
    if (this.animationFrameId !== null) {
      cancelAnimationFrame(this.animationFrameId);
    }
    this.controls.dispose();
    this.renderer.dispose();
    if (this.container && this.renderer.domElement) {
      this.container.removeChild(this.renderer.domElement);
    }
  }
}
