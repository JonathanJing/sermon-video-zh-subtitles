// Local PCM only. No network, storage, monitoring or speech identity processing.
class FingerprintCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.limit = Math.round(sampleRate * Math.min(12, Math.max(1, options.processorOptions?.seconds || 10)));
    this.pcm = new Float32Array(this.limit); this.used = 0; this.nextFrame = null;
    // Discard startup audio until 150 ms of input has a stable render clock.
    // Some WebKit versions initialize currentFrame at zero before adopting the
    // running context's clock. Rebase only before retaining any query samples.
    const configuredStartup = options.processorOptions?.startupSeconds;
    const startupSeconds = Number.isFinite(configuredStartup) ? Math.min(5, Math.max(.25, configuredStartup)) : 3;
    this.warmupFrames = 0; this.warmupLimit = Math.ceil(sampleRate * startupSeconds);
    this.primingFrames = 0; this.primingLimit = Math.ceil(sampleRate * .15);
    this.finished = false;
  }
  fail(error, captureDetail) {
    this.finished = true;
    this.port.postMessage({ error, captureDetail });
    return false;
  }
  process(inputs, outputs = []) {
    if (this.finished) return false;
    const channels = inputs[0];
    const frames = channels?.[0]?.length || 0;
    if (this.used === 0) {
      // Count rendered work, not differences in the initially unstable clock.
      // The connected output supplies the quantum size even without input.
      // 128 is only a legacy fallback for an absent output, never a PCM length.
      this.warmupFrames += outputs?.[0]?.[0]?.length || frames || 128;
      if (this.warmupFrames > this.warmupLimit) return this.fail('capture_start_timeout');
    }
    if (!channels?.length || !frames) {
      // Empty input means not connected yet (or a later interruption). Actual
      // zero-valued PCM is valid input, including silence, and is never skipped.
      if (this.used === 0) { this.primingFrames = 0; this.nextFrame = null; return true; }
      return this.fail('capture_interrupted', 'empty_input');
    }
    if (channels.some(channel => channel.length !== frames)) return this.fail('capture_interrupted', 'channel_shape');
    if (this.nextFrame !== null && currentFrame !== this.nextFrame) {
      if (this.used !== 0) return this.fail('capture_interrupted', 'frame_gap');
      this.primingFrames = 0;
    }
    this.nextFrame = currentFrame + frames;
    if (this.used === 0) {
      if (this.primingFrames < this.primingLimit) { this.primingFrames += frames; return true; }
      this.port.postMessage({ started: true, startContextTime: currentFrame / sampleRate });
    }
    const count = Math.min(frames, this.limit - this.used);
    for (let i = 0; i < count; i++) {
      let value = 0;
      for (const channel of channels) value += channel[i] || 0;
      this.pcm[this.used + i] = value / channels.length;
    }
    this.used += count;
    if (this.used === this.limit) {
      // Keep the endpoint of the last retained sample, including a partial final
      // quantum. Startup wait is reflected only in the absolute render clock.
      const endContextTime = (currentFrame + count) / sampleRate;
      this.finished = true;
      this.port.postMessage({ samples: this.pcm, sampleRate, endContextTime }, [this.pcm.buffer]);
      return false;
    }
    return true;
  }
}
registerProcessor('fingerprint-capture', FingerprintCaptureProcessor);
