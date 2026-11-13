import React, { useEffect, useRef, useState } from 'react';
import { ThreeViewer, type MeshTelemetryInfo } from './ThreeViewer';
import type { JobMetadata } from '../services/api';

interface ModelViewerProps {
  modelUrl: string | null;
  coordinateSystem?: 'Y-up' | 'legacy_z_up';
  jobMetadata?: JobMetadata | null;
  onMeshLoaded?: (info: MeshTelemetryInfo) => void;
  onViewerError?: (message: string | null) => void;
  viewerRef?: React.MutableRefObject<ThreeViewer | null>;
}

export const ModelViewer: React.FC<ModelViewerProps> = ({
  modelUrl,
  coordinateSystem = 'Y-up',
  jobMetadata,
  onMeshLoaded,
  onViewerError,
  viewerRef,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<ThreeViewer | null>(null);
  const [viewerError, setViewerError] = useState<string | null>(null);

  const onMeshLoadedRef = useRef(onMeshLoaded);
  const onViewerErrorRef = useRef(onViewerError);

  useEffect(() => {
    onMeshLoadedRef.current = onMeshLoaded;
  }, [onMeshLoaded]);

  useEffect(() => {
    onViewerErrorRef.current = onViewerError;
  }, [onViewerError]);

  useEffect(() => {
    if (!containerRef.current) return;

    const viewer = new ThreeViewer({
      container: containerRef.current,
      onMeshLoaded: (mesh) => {
        if (onMeshLoadedRef.current) onMeshLoadedRef.current(mesh);
      },
      onError: (msg) => {
        setViewerError(msg);
        if (onViewerErrorRef.current) onViewerErrorRef.current(msg);
      },
    });

    instanceRef.current = viewer;
    if (viewerRef) {
      viewerRef.current = viewer;
    }

    return () => {
      viewer.destroy();
      instanceRef.current = null;
      if (viewerRef) viewerRef.current = null;
    };
  }, [viewerRef]);

  useEffect(() => {
    if (!instanceRef.current) return;
    if (modelUrl) {
      instanceRef.current.loadModelFromUrl(modelUrl, coordinateSystem);
    } else {
      instanceRef.current.clearCurrentModel();
    }
  }, [modelUrl, coordinateSystem]);

  const parsedIntent = typeof jobMetadata?.parsed_intent === 'string' ? jobMetadata.parsed_intent : null;
  const imageMode = typeof jobMetadata?.image_to_3d_mode === 'string' ? jobMetadata.image_to_3d_mode : null;
  const componentsCount =
    typeof jobMetadata?.detected_components_count === 'number' ? jobMetadata.detected_components_count : null;

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        minHeight: '450px',
        position: 'relative',
        borderRadius: '8px',
        overflow: 'hidden',
      }}
    >
      <div
        ref={containerRef}
        style={{
          width: '100%',
          height: '100%',
          minHeight: '450px',
        }}
      />
      {(parsedIntent || imageMode) && (
        <div
          style={{
            position: 'absolute',
            bottom: '16px',
            left: '16px',
            padding: '6px 10px',
            background: '#18181bcc',
            backdropFilter: 'blur(4px)',
            border: '1px solid #3f3f46',
            borderRadius: '6px',
            color: '#e4e4e7',
            fontSize: '11px',
            zIndex: 15,
            display: 'flex',
            gap: '8px',
            alignItems: 'center',
          }}
        >
          {parsedIntent && (
            <span>
              <strong>Text-to-3D:</strong> {parsedIntent}
              {componentsCount !== null ? ` (${componentsCount} comp.)` : ''}
            </span>
          )}
          {imageMode && (
            <span>
              <strong>Image-to-3D:</strong> {imageMode === 'heightmap' ? 'Relevo (Heightmap)' : 'Silhueta 2D'}
            </span>
          )}
        </div>
      )}
      {viewerError && (
        <div
          style={{
            position: 'absolute',
            bottom: '16px',
            left: '16px',
            right: '16px',
            padding: '10px 14px',
            background: '#450a0aee',
            border: '1px solid #dc2626',
            borderRadius: '6px',
            color: '#fecaca',
            fontSize: '12px',
            zIndex: 20,
          }}
        >
          <strong>Erro no Visualizador 3D:</strong> {viewerError}
        </div>
      )}
    </div>
  );
};
