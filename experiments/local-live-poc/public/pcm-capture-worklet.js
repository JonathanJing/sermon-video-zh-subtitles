class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetRate = 16000;
    this.frameSamples = 1600;
    this.phase = 0;
    this.sum = 0;
    this.sampleCount = 0;
    this.frame = new Int16Array(this.frameSamples);
    this.frameOffset = 0;
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true;
    for (let index = 0; index < channel.length; index += 1) {
      this.sum += channel[index];
      this.sampleCount += 1;
      this.phase += this.targetRate;
      if (this.phase < sampleRate) continue;
      this.phase -= sampleRate;
      const averaged = this.sum / this.sampleCount;
      const clamped = Math.max(-1, Math.min(1, averaged));
      this.frame[this.frameOffset] = clamped < 0 ? clamped * 32768 : clamped * 32767;
      this.frameOffset += 1;
      this.sum = 0;
      this.sampleCount = 0;
      if (this.frameOffset !== this.frameSamples) continue;
      const complete = this.frame;
      this.port.postMessage(complete.buffer, [complete.buffer]);
      this.frame = new Int16Array(this.frameSamples);
      this.frameOffset = 0;
    }
    return true;
  }
}

registerProcessor("pcm-capture-processor", PcmCaptureProcessor);
