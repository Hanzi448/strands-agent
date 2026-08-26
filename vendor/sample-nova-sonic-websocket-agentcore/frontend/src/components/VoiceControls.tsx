import { useState } from 'react';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Toggle from '@cloudscape-design/components/toggle';

interface VoiceControlsProps {
  isConnected: boolean;
  isRecording: boolean;
  isSpeaking: boolean;
  onConnect: () => void;
  onDisconnect: () => void;
  onStartRecording: () => void;
  onStopRecording: () => void;
}

export default function VoiceControls({
  isConnected,
  isRecording,
  isSpeaking,
  onConnect,
  onDisconnect,
  onStartRecording,
  onStopRecording
}: VoiceControlsProps) {
  const getStatusIndicator = () => {
    if (!isConnected) {
      return <StatusIndicator type="stopped">Disconnected</StatusIndicator>;
    }
    if (isRecording) {
      return <StatusIndicator type="in-progress">Listening...</StatusIndicator>;
    }
    if (isSpeaking) {
      return <StatusIndicator type="in-progress">Speaking...</StatusIndicator>;
    }
    return <StatusIndicator type="success">Connected</StatusIndicator>;
  };

  return (
    <Box padding={{ vertical: 'm', horizontal: 'l' }}>
      <SpaceBetween size="m" direction="horizontal" alignItems="center">
        {/* Connection Status */}
        {getStatusIndicator()}

        {/* Connect/Disconnect Button */}
        {!isConnected ? (
          <Button
            variant="primary"
            iconName="call"
            onClick={onConnect}
          >
            Connect Voice
          </Button>
        ) : (
          <Button
            variant="normal"
            iconName="call-end"
            onClick={onDisconnect}
          >
            Disconnect
          </Button>
        )}

        {/* Microphone Button */}
        {isConnected && (
          <Button
            variant={isRecording ? 'primary' : 'normal'}
            iconName={isRecording ? 'microphone-off' : 'microphone'}
            onClick={isRecording ? onStopRecording : onStartRecording}
            disabled={isSpeaking}
            ariaLabel={isRecording ? 'Stop recording' : 'Start recording'}
          >
            {isRecording ? 'Stop' : 'Push to Talk'}
          </Button>
        )}

        {/* Visual Feedback */}
        {isRecording && (
          <Box color="text-status-error" fontSize="body-m">
            🔴 Recording
          </Box>
        )}
        {isSpeaking && (
          <Box color="text-status-info" fontSize="body-m">
            🔊 Agent Speaking
          </Box>
        )}
      </SpaceBetween>
    </Box>
  );
}
