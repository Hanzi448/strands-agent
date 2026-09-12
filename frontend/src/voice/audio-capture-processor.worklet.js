// AudioWorklet processor: converts mic Float32 frames to 16-bit PCM on
// the audio thread. Adapted from the vendored reference sample
// (vendor/sample-nova-sonic-websocket-agentcore/frontend/src/
// audio-processor.worklet.js); the body is unchanged -- only this
// comment and its new home differ. Plain JS by necessity: worklets run
// on the audio thread with no TypeScript support, and vite serves this
// file as-is via the `?url` import.

class AudioCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];

    if (!input || !input[0]) {
      return true;
    }

    const inputData = input[0];

    // Convert Float32Array to Int16Array (PCM 16-bit).
    const pcmData = new Int16Array(inputData.length);
    for (let i = 0; i < inputData.length; i++) {
      const s = Math.max(-1, Math.min(1, inputData[i]));
      pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }

    this.port.postMessage({ type: "audio", data: pcmData });

    return true;
  }
}

registerProcessor("audio-capture-processor", AudioCaptureProcessor);
