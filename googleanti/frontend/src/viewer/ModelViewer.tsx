import React, { useEffect, useRef } from 'react';
import { ThreeViewer } from './ThreeViewer';

interface ModelViewerProps {
  modelUrl: string | null;
  onMeshLoaded?: (info: { vertexCount: number; faceCount: number; dimensions: [number, number, number] }) => void;
  viewerRef?: React.MutableRefObject<ThreeViewer | null>;
}

export const ModelViewer: React.FC<ModelViewerProps> = ({ modelUrl, onMeshLoaded, viewerRef }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<ThreeViewer | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const viewer = new ThreeViewer({
      container: containerRef.current,
      onMeshLoaded
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
  }, []);

  useEffect(() => {
    if (instanceRef.current && modelUrl) {
      instanceRef.current.loadModelFromUrl(modelUrl);
    }
  }, [modelUrl]);

  return (
    <div
      ref={containerRef}
      style={{
        width: '100%',
        height: '100%',
        minHeight: '450px',
        position: 'relative',
        borderRadius: '8px',
        overflow: 'hidden'
      }}
    />
  );
};
