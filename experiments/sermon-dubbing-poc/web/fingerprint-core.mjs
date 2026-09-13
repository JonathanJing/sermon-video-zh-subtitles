/** Pure DSP spectral-landmark fingerprints. No media, network, or browser globals. */
export const CONFIG = Object.freeze({sampleRate:8000,fftSize:1024,hopSize:256,algorithmVersion:'spectral-landmarks-v1'});
const N=CONFIG.fftSize, H=CONFIG.hopSize, SR=CONFIG.sampleRate;
function resample(input, rate) {
  if (!(input instanceof Float32Array) || !(rate >= 4000 && rate <= 192000)) throw new TypeError('Expected Float32Array and a valid sample rate');
  if (rate === SR) return input;
  const out=new Float32Array(Math.floor(input.length*SR/rate));
  // Windowed sinc suppresses aliases; recording is downsampled only in memory.
  const ratio=rate/SR, cutoff=Math.min(1,1/ratio)*.94, radius=Math.ceil(12/cutoff);
  for(let i=0;i<out.length;i++) { const p=i*ratio, base=Math.floor(p); let sum=0, norm=0;
    for(let j=base-radius;j<=base+radius;j++) { if(j<0||j>=input.length) continue;
      const d=p-j, x=Math.PI*d*cutoff, w=(Math.abs(x)<1e-8?1:Math.sin(x)/x)*(.5+.5*Math.cos(Math.PI*d/(radius+1)));
      sum+=input[j]*w; norm+=w;
    } out[i]=sum/norm;
  } return out;
}
function fft(re, im) {
  for(let i=1,j=0;i<N;i++) {let b=N>>1; for(;j&b;b>>=1)j^=b;j^=b;if(i<j){[re[i],re[j]]=[re[j],re[i]];}}
  for(let size=2;size<=N;size<<=1){const a=-2*Math.PI/size, wr=Math.cos(a),wi=Math.sin(a);
    for(let base=0;base<N;base+=size){let ur=1,ui=0;for(let j=0;j<size/2;j++){
      const k=base+j,l=k+size/2,tr=ur*re[l]-ui*im[l],ti=ur*im[l]+ui*re[l];
      re[l]=re[k]-tr;im[l]=im[k]-ti;re[k]+=tr;im[k]+=ti;
      const nr=ur*wr-ui*wi;ui=ur*wi+ui*wr;ur=nr;
    }}
  }
}
function hash(f1,f2,dt){return (f1<<14)|(f2<<6)|dt;}
export function fingerprint(samples,sampleRate) {
  const x=resample(samples,sampleRate), frames=Math.max(0,Math.floor((x.length-N)/H)+1), candidates=[];
  let energy=0;for(const v of x){if(!Number.isFinite(v))throw new TypeError('Non-finite sample');energy+=v*v;}
  const rms=Math.sqrt(energy/Math.max(1,x.length)), re=new Float64Array(N), im=new Float64Array(N), log=new Float64Array(N/2), win=Float64Array.from({length:N},(_,i)=>.5-.5*Math.cos(2*Math.PI*i/(N-1)));
  for(let t=0;t<frames;t++){
    for(let i=0;i<N;i++){re[i]=x[t*H+i]*win[i];im[i]=0;}fft(re,im);
    let avg=0;for(let b=24;b<440;b++){log[b]=Math.log(1e-16+re[b]*re[b]+im[b]*im[b]);avg+=log[b];}avg/=416;
    const peaks=[];
    for(let b=27;b<436;b++)if(log[b]>log[b-1]&&log[b]>=log[b+1]&&log[b]>avg+1.2){
      let local=0;for(let k=-10;k<=10;k++)local+=log[Math.max(24,Math.min(439,b+k))];
      peaks.push({t,b,score:log[b]-.65*local/21-.35*avg});
    }
    peaks.sort((a,b)=>b.score-a.score);candidates.push(peaks.slice(0,5));
  }
  const bySecond=new Map();
  for(let t=0;t<frames;t++)for(const p of candidates[t]){
    let strongest=true;
    for(let d=-3;d<=3&&strongest;d++)if(t+d>=0&&t+d<frames)for(const q of candidates[t+d])if(q!==p&&Math.abs(q.b-p.b)<=3&&q.score>p.score){strongest=false;break;}
    if(strongest){const s=Math.floor(t*H/SR);if(!bySecond.has(s))bySecond.set(s,[]);bySecond.get(s).push(p);}
  }
  const peaks=[];for(const group of bySecond.values()){group.sort((a,b)=>b.score-a.score);peaks.push(...group.slice(0,14));}peaks.sort((a,b)=>a.t-b.t||a.b-b.b);
  const landmarks=[];
  for(let i=0;i<peaks.length;i++){const p=peaks[i];let count=0;for(let j=i+1;j<peaks.length;j++){
    const q=peaks[j],dt=q.t-p.t;if(dt<5)continue;if(dt>44)break;
    landmarks.push([hash(Math.round(p.b/2),Math.round(q.b/2),dt),p.t]);if(++count>=8)break;
  }}
  return {schemaVersion:'sermon-fingerprint-query-v1',algorithmVersion:CONFIG.algorithmVersion,sampleRate:SR,hopSize:H,durationSeconds:samples.length/sampleRate,rms,peakCount:peaks.length,landmarks};
}
export function matchFingerprint(features,index) {
  const fail=(reason,more={})=>({matched:false,queryStartSeconds:null,confidence:0,diagnostics:{reason,...more}});
  if(index?.schemaVersion!=='sermon-landmark-index-v1'||index.algorithmVersion!==CONFIG.algorithmVersion||index.sampleRate!==SR||index.hopSize!==H||!index.postings) return fail('incompatible_index');
  if(features?.schemaVersion!=='sermon-fingerprint-query-v1'||features.algorithmVersion!==CONFIG.algorithmVersion||features.sampleRate!==SR||features.hopSize!==H)return fail('incompatible_query');
  if(features.rms<.0001)return fail('silence');
  if(features.durationSeconds<7||features.durationSeconds>20||features.landmarks.length<80)return fail('insufficient_audio');
  const votes=new Map();
  for(let qi=0;qi<features.landmarks.length;qi++){
    const [h,t]=features.landmarks[qi],f1=h>>>14,f2=(h>>>6)&255,dt=h&63,seen=new Set();
    for(let a=-1;a<=1;a++)for(let b=-1;b<=1;b++)for(let d=-1;d<=1;d++){
      const positions=index.postings[hash(f1+a,f2+b,dt+d)];if(!positions||positions.length>80)continue;
      for(const pos of positions){const offset=pos-t;if(offset < -2 || offset*H/SR+features.durationSeconds>index.durationSeconds+.15)continue;
        const bin=Math.round(offset/2);if(seen.has(bin))continue;seen.add(bin);
        if(!votes.has(bin))votes.set(bin,[]);votes.get(bin).push([qi,t,offset]);
      }
    }
  }
  const ranked=[...votes.entries()].map(([bin,items])=>({bin,items,score:items.length})).sort((a,b)=>b.score-a.score);
  if(!ranked.length)return fail('no_consensus');
  const best=ranked[0], runners=ranked.filter(v=>Math.abs(v.bin-best.bin)>6),second=runners[0]?.score||0;
  const offsets=best.items.map(v=>v[2]).sort((a,b)=>a-b),offset=offsets[Math.floor(offsets.length/2)],anchors=new Set(best.items.map(v=>v[1])), times=[...anchors],span=(Math.max(...times)-Math.min(...times))*H/SR;
  const fraction=best.score/features.landmarks.length,ratio=best.score/Math.max(1,second),confidence=Math.min(1,Math.min(best.score/65,anchors.size/18,span/6,ratio/2.5,fraction/.10));
  const subwindowAnchors=[0,1,2].map(k=>new Set(best.items.filter(v=>Math.min(2,Math.floor(v[1]*H/SR/features.durationSeconds*3))===k).map(v=>v[1])).size);
  const diagnostics={reason:'matched',subwindowAnchors,votes:best.score,distinctAnchors:anchors.size,queryLandmarks:features.landmarks.length,matchFraction:fraction,runnerUpVotes:second,peakRatio:ratio,coveredSeconds:span,offsetResolutionSeconds:H/SR};
  if(best.score<35||anchors.size<12||span<4.5||ratio<1.8||fraction<.055||subwindowAnchors.some(n=>n<3))return fail(ratio<1.8?'ambiguous':'low_confidence',{...diagnostics,reason:ratio<1.8?'ambiguous':'low_confidence'});
  return {matched:true,queryStartSeconds:Math.max(0,offset*H/SR),confidence,diagnostics};
}
