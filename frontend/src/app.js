import {api,post} from './api/client.js';import {batches,inspections,reviews,disclosures} from './api/business.js';import {state,refresh} from './stores/business.js';import {shell} from './components/common/shell.js';import {login} from './pages/login.js';import {batchesPage} from './pages/batches.js';import {inspectionsPage} from './pages/inspections.js';import {diagnosisPage} from './pages/diagnosis.js';import {reportsPage} from './pages/reports.js';import {disclosuresPage} from './pages/disclosures.js';import {formData,notify} from './hooks/forms.js';import {route} from './router/router.js';
const app=document.getElementById('app');let timer;
const pages={batches:batchesPage,inspections:inspectionsPage,diagnosis:diagnosisPage,reports:reportsPage,disclosures:disclosuresPage};
const pending=()=>state.reviews.some(x=>['queued','running'].includes(x.status))||state.disclosures.some(x=>['pending','judging'].includes(x.status));
async function render(){clearTimeout(timer);if(!localStorage.getItem('mill-token')){app.innerHTML=login();document.getElementById('login-form').onsubmit=async e=>{e.preventDefault();try{const d=await post('/auth/login',formData(e.target));localStorage.setItem('mill-token',d.access_token);state.user=d.user;await render();}catch(err){document.getElementById('login-error').textContent=err.message;}};return;}
try{state.user=await api('/auth/me');await refresh();const p=route();app.innerHTML=shell(p,state.user,pages[p](state));bind();if(pending())timer=setTimeout(render,1500);}catch(e){app.innerHTML='<div class="fatal">数据暂未加载。<button onclick="location.reload()">重新加载</button></div>';}}
function bind(){document.getElementById('logout').onclick=()=>{localStorage.removeItem('mill-token');state.selected=null;render();};
const bindForm=(id,fn,nums=[])=>{const f=document.getElementById(id);if(f)f.onsubmit=async e=>{e.preventDefault();const btn=f.querySelector('button');btn.disabled=true;try{await fn(formData(f,nums));await render();notify('已保存，数据与复核记录已更新。');}catch(err){notify(err.message,true);btn.disabled=false;}};};
bindForm('batch-form',batches.create,['tonnes']);bindForm('inspection-form',inspections.create,['batch_id','flour_yield','moisture']);bindForm('review-form',async d=>{state.selected=await reviews.create(d);});
bindDisclosure();
const approval=document.getElementById('approve-form');if(approval)bindForm('approve-form',d=>reviews.approve(approval.dataset.id,d.note));
document.querySelectorAll('[data-review]').forEach(b=>b.onclick=async()=>{try{state.selected=await reviews.get(b.dataset.review);await render();}catch(e){notify(e.message,true);}});
const dl=document.getElementById('download');if(dl)dl.onclick=async()=>{try{await reviews.download(dl.dataset.id);notify('CSV 已生成并下载。');}catch(e){notify(e.message,true);}};
}
function bindDisclosure(){
 const form=document.getElementById('disclosure-form');
 const monthSel=document.getElementById('disclosure-month');
 if(monthSel)monthSel.onchange=()=>{document.querySelectorAll('fieldset.disclosure-month').forEach(fs=>fs.classList.toggle('hidden',fs.dataset.month!==monthSel.value));};
 if(form)form.onsubmit=async e=>{
  e.preventDefault();
  const monthEl=document.getElementById('disclosure-month');
  const month=monthEl?monthEl.value:'';
  const fieldset=month?document.querySelector(`fieldset.disclosure-month[data-month="${CSS.escape(month)}"]`):null;
  if(!fieldset){notify('当前到货月暂无可选批次，请先录入检验记录。',true);return;}
  const batch_ids=[...fieldset.querySelectorAll('input[name="batch"]:checked')].map(cb=>Number(cb.value));
  if(!batch_ids.length){notify('请至少勾选一个批次。',true);return;}
  const btn=form.querySelector('button');btn.disabled=true;
  try{const created=await disclosures.create(batch_ids);state.selectedDisclosure=created;await render();notify('申请已提交，正在后台判单。');}
  catch(err){notify(err.message,true);btn.disabled=false;}
 };
 document.querySelectorAll('[data-disclosure]').forEach(b=>b.onclick=async()=>{try{state.selectedDisclosure=await disclosures.get(b.dataset.disclosure);await render();}catch(e){notify(e.message,true);}});
 const retry=document.getElementById('disclosure-retry');if(retry)retry.onclick=async()=>{retry.disabled=true;try{state.selectedDisclosure=await disclosures.retry(retry.dataset.id);await render();notify('已沿原单重新判单。');}catch(e){notify(e.message,true);retry.disabled=false;}};
 const ex=document.getElementById('disclosure-export');if(ex)ex.onclick=async()=>{try{await disclosures.download();notify('已发布汇总 CSV 已下载。');}catch(e){notify(e.message,true);}};
}
window.addEventListener('hashchange',()=>{state.selected=null;state.selectedDisclosure=null;render();});render();
