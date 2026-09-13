/**
 * React hook owning one voice call: WebSocket connection, mic capture,
 * audio playback, and the state the voice screen renders.
 *
 * Adapted from the vendored sample's `useVoiceAgent.ts`, strictly
 * typed, with deliberate changes: a RecordingHandle replaces the
 * sample's `as any` MediaRecorder stand-in, connect takes a clinicId
 * for the guest flow, transcript state flows through the pure
 * reducer, playback is PCM-only (this runtime emits pcm), and the
 * mic auto-starts on connect — Nova Sonic times a call out at 55s
 * without patient audio, so the caller is heard for the whole call
 * (the vendored sample's shape).
 */

import { useCallback, useEffect, useRef, useState } from "react";

import workletUrl from "./audio-capture-processor.worklet.js?url";
import { describeClose } from "./lib/agentEvents";
import {
  connectToAgent,
  type BidiAudioInputEvent,
  type VoiceAgentConnection,
} from "./lib/agentSocket";
import { base64ToInt16, int16ToFloat32, int16ToBase64 } from "./lib/pcm";
import {
  applyToTranscript,
  initialTranscript,
  type TranscriptState,
} from "./lib/transcriptReducer";

const SAMPLE_RATE = 16000;

interface RecordingHandle {
  stop(): void;
}

export interface UseVoiceCallReturn {
  isConnected: boolean;
  isRecording: boolean;
  isSpeaking: boolean;
  errorMessage: string | null;
  transcript: TranscriptState;
  connect: () => Promise<void>;
  disconnect: () => void;
  startRecording: () => Promise<void>;
  stopRecording: () => void;
  clearError: () => void;
}

export function useVoiceCall(clinicId: string): UseVoiceCallReturn {
  const [isConnected, setIsConnected] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<TranscriptState>(initialTranscript);

  const connectionRef = useRef<VoiceAgentConnection | null>(null);
  const recordingRef = useRef<RecordingHandle | null>(null);
  const playbackContextRef = useRef<AudioContext | null>(null);
  const audioQueueRef = useRef<AudioBuffer[]>([]);
  const isPlayingRef = useRef(false);

  const playNextAudio = useCallback(() => {
    const context = playbackContextRef.current;
    if (!context || context.state === "closed" || audioQueueRef.current.length === 0) {
      isPlayingRef.current = false;
      setIsSpeaking(false);
      return;
    }
    isPlayingRef.current = true;
    setIsSpeaking(true);

    const buffer = audioQueueRef.current.shift()!;
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    source.onended = () => playNextAudio();
    source.start();
  }, []);

  const queueAudio = useCallback(
    (base64Audio: string, sampleRate: number) => {
      try {
        if (!playbackContextRef.current || playbackContextRef.current.state === "closed") {
          playbackContextRef.current = new AudioContext({ sampleRate });
        }
        const context = playbackContextRef.current;

        const floats = int16ToFloat32(base64ToInt16(base64Audio));
        const buffer = context.createBuffer(1, floats.length, sampleRate);
        buffer.getChannelData(0).set(floats);

        audioQueueRef.current.push(buffer);
        if (!isPlayingRef.current) playNextAudio();
      } catch (error) {
        console.error("Failed to queue audio for playback", error);
      }
    },
    [playNextAudio],
  );

  const startRecording = useCallback(async () => {
    if (recordingRef.current !== null || !connectionRef.current?.isConnected()) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: SAMPLE_RATE,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });

      const context = new AudioContext({ sampleRate: SAMPLE_RATE });
      await context.audioWorklet.addModule(workletUrl);
      const source = context.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(context, "audio-capture-processor");

      node.port.onmessage = (event: MessageEvent) => {
        const connection = connectionRef.current;
        if (!connection?.isConnected() || recordingRef.current === null) return;
        const payload = event.data as { type?: unknown; data?: unknown };
        if (payload.type !== "audio" || !(payload.data instanceof Int16Array)) return;

        const audioEvent: BidiAudioInputEvent = {
          type: "bidi_audio_input",
          audio: int16ToBase64(payload.data),
          format: "pcm",
          sample_rate: SAMPLE_RATE,
          channels: 1,
        };
        connection.send(audioEvent);
      };

      source.connect(node);
      // The worklet writes no output, but the graph must reach the
      // destination for the audio thread to be driven at all.
      node.connect(context.destination);

      recordingRef.current = {
        stop: () => {
          node.disconnect();
          source.disconnect();
          void context.close();
          stream.getTracks().forEach((track) => track.stop());
        },
      };
      setIsRecording(true);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setErrorMessage(`Microphone error: ${detail}`);
    }
  }, []);

  const connect = useCallback(async () => {
    try {
      setErrorMessage(null);
      const connection = await connectToAgent({
        clinicId,
        onConnected: () => setIsConnected(true),
        onDisconnected: (code, reason) => {
          setIsConnected(false);
          setIsRecording(false);
          setIsSpeaking(false);
          // 1000 is a normal close (we or the agent hung up); anything
          // else deserves an explanation.
          if (code !== 1000) setErrorMessage(describeClose(code, reason));
        },
        onAudioChunk: (audio, _format, sampleRate) => queueAudio(audio, sampleRate),
        onTranscript: (text, isFinal, role) => {
          setTranscript((prev) =>
            applyToTranscript(prev, { kind: "transcript", text, isFinal, role }),
          );
        },
        onInterruption: () => {
          // The patient talked over the agent: drop whatever was queued
          // or playing, and drop the in-flight partial.
          audioQueueRef.current = [];
          isPlayingRef.current = false;
          setIsSpeaking(false);
          setTranscript((prev) => applyToTranscript(prev, { kind: "interruption" }));
        },
        onError: (message) => setErrorMessage(message),
      });
      connectionRef.current = connection;
      // The mic opens the moment the connection does: Nova Sonic drops
      // a call with no patient audio after 55s, and a patient who
      // hesitates through the greeting must not be timed out for it.
      // The orb stays tappable, so the mic can still be paused; a
      // denied permission surfaces as an error the patient can retry.
      void startRecording();
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setErrorMessage(detail);
    }
  }, [clinicId, queueAudio, startRecording]);

  const stopRecording = useCallback(() => {
    recordingRef.current?.stop();
    recordingRef.current = null;
    setIsRecording(false);
  }, []);

  const disconnect = useCallback(() => {
    stopRecording();
    connectionRef.current?.close();
    connectionRef.current = null;

    audioQueueRef.current = [];
    isPlayingRef.current = false;
    if (playbackContextRef.current && playbackContextRef.current.state !== "closed") {
      void playbackContextRef.current.close();
    }

    setIsConnected(false);
    setIsRecording(false);
    setIsSpeaking(false);
    setErrorMessage(null);
    setTranscript(initialTranscript);
  }, [stopRecording]);

  const clearError = useCallback(() => setErrorMessage(null), []);

  // Tear the whole call down on unmount.
  useEffect(() => disconnect, [disconnect]);

  return {
    isConnected,
    isRecording,
    isSpeaking,
    errorMessage,
    transcript,
    connect,
    disconnect,
    startRecording,
    stopRecording,
    clearError,
  };
}
