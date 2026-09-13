class ProbePlayback extends AudioWorkletProcessor {
  constructor() {
    super();
    this.epoch = 0;
    this.queue = [];
    this.playing = false;
    this.ratio = 16000 / sampleRate;
    this.port.onmessage = ({ data }) => {
      if (data.type === "reset") {
        this.epoch = Number.isInteger(data.epoch) ? data.epoch : 0;
        this.queue = [];
        this.playing = false;
        return;
      }
      if (data.type !== "frame" || !this.epoch || data.epoch !== this.epoch
          || !(data.pcm instanceof Float32Array) || data.pcm.length !== 1600) return;
      if (this.queue.length >= 8) {
        const dropped = this.queue.shift();
        this.port.postMessage({ type: "dropped", epoch: this.epoch, sequence: dropped.sequence });
      }
      this.queue.push({ sequence: data.sequence, pcm: data.pcm, cursor: 0, entered: false });
    };
  }

  process(_inputs, outputs) {
    const output = outputs[0]?.[0];
    if (!output) return true;
    output.fill(0);
    if (!this.epoch) return true;
    // Two 100 ms frames form a small, explicit initial jitter buffer.
    if (!this.playing && this.queue.length >= 2) this.playing = true;
    if (!this.playing) return true;
    for (let index = 0; index < output.length; index += 1) {
      const frame = this.queue[0];
      if (!frame) {
        this.playing = false;
        this.port.postMessage({ type: "underrun", epoch: this.epoch });
        break;
      }
      if (!frame.entered) {
        frame.entered = true;
        this.port.postMessage({ type: "played", epoch: this.epoch, sequence: frame.sequence,
          renderedAudioTime: currentTime + index / sampleRate });
      }
      const left = Math.floor(frame.cursor), fraction = frame.cursor - left;
      const a = frame.pcm[Math.min(left, 1599)], b = frame.pcm[Math.min(left + 1, 1599)];
      output[index] = a + (b - a) * fraction;
      frame.cursor += this.ratio;
      if (frame.cursor >= 1600) {
        const carry = frame.cursor - 1600;
        this.queue.shift();
        if (this.queue[0]) this.queue[0].cursor = carry;
      }
    }
    return true;
  }
}
registerProcessor("media-probe-playback", ProbePlayback);
