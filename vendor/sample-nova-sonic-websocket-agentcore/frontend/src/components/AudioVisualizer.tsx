import { useEffect, useRef } from 'react';
import Box from '@cloudscape-design/components/box';

interface AudioVisualizerProps {
  isActive: boolean;
  type: 'recording' | 'speaking';
}

export default function AudioVisualizer({ isActive, type }: AudioVisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationRef = useRef<number>();

  useEffect(() => {
    if (!isActive || !canvasRef.current) {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
      return;
    }

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const width = canvas.width;
    const height = canvas.height;
    const barCount = 40;
    const barWidth = width / barCount;

    let phase = 0;

    const draw = () => {
      ctx.clearRect(0, 0, width, height);

      // Color based on type
      const color = type === 'recording' ? '#d91515' : '#0972d3'; // Red for recording, blue for speaking

      for (let i = 0; i < barCount; i++) {
        // Create wave effect
        const amplitude = Math.sin(phase + i * 0.3) * 0.5 + 0.5;
        const barHeight = amplitude * height * 0.8;
        const x = i * barWidth;
        const y = (height - barHeight) / 2;

        ctx.fillStyle = color;
        ctx.fillRect(x, y, barWidth - 2, barHeight);
      }

      phase += 0.1;
      animationRef.current = requestAnimationFrame(draw);
    };

    draw();

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [isActive, type]);

  if (!isActive) {
    return null;
  }

  return (
    <Box padding={{ vertical: 's' }}>
      <canvas
        ref={canvasRef}
        width={600}
        height={60}
        style={{
          width: '100%',
          height: '60px',
          borderRadius: '8px',
          backgroundColor: '#f4f4f4'
        }}
      />
    </Box>
  );
}
