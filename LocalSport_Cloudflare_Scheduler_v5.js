const OWNER = 'skaterbosse', REPO = 'hockey', WORKFLOW = 'StatsByDate.yml';
const STATE_URL = `https://raw.githubusercontent.com/${OWNER}/${REPO}/main/statsByDate/data/updateSchedule.json`;
function stockholmParts(date) {
  return Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
    timeZone:'Europe/Stockholm', hour:'2-digit', minute:'2-digit', hourCycle:'h23',
    year:'numeric', month:'2-digit', day:'2-digit'
  }).formatToParts(date).filter(p=>p.type!=='literal').map(p=>[p.type,p.value]));
}
export function fixedMode(at) {
  const p=stockholmParts(at), h=+p.hour,m=+p.minute;
  if(h===4 && m===50) return 'daily';
  if((h>=19 || h<10) && m%30===0) return 'regular';
  if(h>=5 && h<10 && m%10===0) return 'regular';
  return null;
}
const DEFAULT_NIGHT = {enabled:true,timezone:'Europe/Stockholm',start:'01:30',end:'05:00',minimum_interval_minutes:30};
export function dynamicMode(at,state) {
  if(fixedMode(at)==='daily') return 'daily';
  const now=+at, generated=Date.parse(state.generatedUTC), valid=Date.parse(state.validUntilUTC);
  if(state.schemaVersion!==2 || !Number.isFinite(generated) || !Number.isFinite(valid) || now>valid || generated>now+300000 || !Array.isArray(state.windows)) throw Error('Invalid or stale schedule');
  const policy=state.nightMode??DEFAULT_NIGHT;
  const clock=/^([01]\d|2[0-3]):[0-5]\d$/;
  if(typeof policy.enabled!=='boolean'||policy.timezone!=='Europe/Stockholm'||!clock.test(policy.start)||!clock.test(policy.end)||policy.start>=policy.end||!Number.isInteger(policy.minimum_interval_minutes)||policy.minimum_interval_minutes<10||policy.minimum_interval_minutes%5!==0) throw Error('Invalid night policy');
  const local=stockholmParts(at), hm=`${local.hour}:${local.minute}`;
  const night=policy.enabled && hm>=policy.start && hm<policy.end;
  const last=Date.parse(state.lastRegularUTC);
  if(night && !Number.isFinite(last)) throw Error('Invalid lastRegularUTC');
  // Global cadence, not per-match: overlapping windows cannot bypass the night limit.
  const nightPeriod=policy.minimum_interval_minutes*60000;
  const anchor=Math.ceil(last/300000)*300000;
  let requested=false;
  for(const w of state.windows) {
    const due=Date.parse(w.dueUTC), end=Date.parse(w.expiresUTC);
    const interval=w.intervalMinutes;
    if(!Number.isFinite(due)||!Number.isFinite(end)||due>=end||!((w.kind==='live'&&interval===10)||(w.kind==='highlights'&&interval===30))) throw Error('Invalid schedule window');
    const slot=Math.ceil(due/300000)*300000;
    if(now>=slot && now<end) {
      if(night ? now>=anchor+nightPeriod && (now-anchor)%nightPeriod===0 : (now-slot)%(interval*60000)===0) requested=true;
    }
  }
  return requested?'regular':null;
}
async function dispatch(mode,env,scheduledTime) {
  if(env.ENABLE_DISPATCH!=='true') {console.log(`DRY RUN: ${WORKFLOW}, mode=${mode}`);return;}
  if(!env.GITHUB_TOKEN) throw Error('Missing GITHUB_TOKEN secret');
  if(env.SCHEDULER_MODE==='dynamic' && mode==='regular') {
    const r=await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/runs?branch=main&per_page=10`,{headers:{Accept:'application/vnd.github+json',Authorization:`Bearer ${env.GITHUB_TOKEN}`,'User-Agent':'LocalSport-Cloudflare-Scheduler'}});
    if(!r.ok) throw Error(`Cannot verify running workflows: ${r.status}`);
    if((await r.json()).workflow_runs.some(run=>run.status!=='completed')) {console.log('Skip: workflow already pending or running');return;}
  }
  const requestTime=Date.now();
  const response=await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,{
    method:'POST',headers:{Accept:'application/vnd.github+json',Authorization:`Bearer ${env.GITHUB_TOKEN}`,'X-GitHub-Api-Version':'2022-11-28','User-Agent':'LocalSport-Cloudflare-Scheduler'},body:JSON.stringify({ref:'main',inputs:{mode}})
  });
  const acceptedTime=Date.now();
  console.log(JSON.stringify({event:'github_dispatch',workflow:WORKFLOW,mode,scheduledUTC:new Date(scheduledTime).toISOString(),requestUTC:new Date(requestTime).toISOString(),acceptedUTC:new Date(acceptedTime).toISOString(),cloudflareDelayMs:requestTime-scheduledTime,apiResponseMs:acceptedTime-requestTime,totalDispatchDelayMs:acceptedTime-scheduledTime,githubHttpStatus:response.status}));
  if(!response.ok) throw Error(`GitHub dispatch failed: HTTP ${response.status} ${(await response.text()).slice(0,300)}`);
}
export default {
  async scheduled(controller,env) {
    // Replace all old triggers with one */5 trigger before enabling dispatch.
    if(controller.cron!=='*/5 * * * *') {console.log('Ignored legacy trigger');return;}
    const at=new Date(controller.scheduledTime), fixed=fixedMode(at);
    const setting=env.SCHEDULER_MODE||'fixed';
    let dynamic=null,error=null;
    if(setting==='dynamic'||setting==='shadow') {
      try {
        const r=await fetch(`${STATE_URL}?slot=${controller.scheduledTime}`,{cache:'no-store'});
        if(!r.ok) throw Error(`Schedule HTTP ${r.status}`);
        dynamic=dynamicMode(at,await r.json());
      } catch(e) {error=String(e);dynamic=fixed;}
    }
    const mode=setting==='dynamic'?dynamic:fixed;
    console.log(JSON.stringify({scheduledUTC:at.toISOString(),stockholm:stockholmParts(at),setting,fixed,dynamic,error,mode:mode||'skip'}));
    if(mode) await dispatch(mode,env,controller.scheduledTime);
  },
  async fetch(){return new Response('LocalSport scheduler is running. Manual HTTP dispatch is disabled.');}
};
