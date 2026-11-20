import {table} from '../components/common/table.js';
import {esc,fmt,canEdit} from '../utils/format.js';
import {disclosureStatuses} from '../constants/enums.js';

function dbadge(status){return `<span class="badge ${esc(status)}">${esc(disclosureStatuses[status]||status)}</span>`;}
function monthOf(date){return (date||'').slice(0,7);}

export function disclosuresPage(s){
 const frozenIds=new Set(s.frozenMeans.map(f=>f.batch_id));
 const withSamples=s.batches.filter(b=>b.samples>0);
 const groups={};
 for(const b of withSamples){(groups[monthOf(b.received_date)]??=[]).push(b);}
 const months=Object.keys(groups).sort().reverse();
 const activeMonth=months[0]||'';
 const sel=s.selectedDisclosure;
 return `<header><p class="eyebrow">05 / OUTBOUND DISCLOSURE</p><h1>外发复核</h1><p>各单只看到汇总，但多份汇总联立可能反推单批。申请公布所选批次出粉率均值的加总值，系统按到货月与已发布等式联立判单。</p></header>
 <div class="workspace">
  <section class="paper">
   <h2>提交外发申请</h2>
   <form id="disclosure-form">
    <label>到货月<select name="month" id="disclosure-month">${months.map(m=>`<option value="${esc(m)}">${esc(m)}（${groups[m].length} 批）</option>`).join('')}</label>
    <div class="disclosure-batches">
     ${months.map((m,mi)=>`<fieldset class="disclosure-month ${mi===0?'':'hidden'}" data-month="${esc(m)}">
       <legend>${esc(m)} 到货批次（勾选，可多选）</legend>
       ${groups[m].map(b=>`<label class="check"><input type="checkbox" name="batch" value="${b.id}"> <span><strong>${esc(b.code)}</strong><small>${esc(b.line)} · ${b.samples} 个样本${frozenIds.has(b.id)?' · 均值已冻结':''}</small></span></label>`).join('')}
     </fieldset>`).join('')}
    </div>
    <button class="primary" ${canEdit(s.user)?'':'disabled'}>提交判单 →</button>
   </form>
   <p class="hint">均值在该月首次受理时冻结，之后录入不改写。仅含一个批次的申请必然拒发；与本月已发布等式联立后若能解出任一单批，整单拒发。观察员仅可查看。</p>
   <button class="outline" id="disclosure-export">导出已发布汇总 CSV ↓</button>
  </section>
  <section>
   <div class="section-head"><h2>外发判单台账</h2><span>${s.disclosures.length} 单 / 月份 ${activeMonth||'—'}</span></div>
   ${disclosureList(s)}
   ${sel?disclosureDetail(s,sel):'<div class="empty">选择左侧任一申请查看判单结果。数值仅在“已发布”后对外可见。</div>'}
  </section>
 </div>`;
}

function disclosureList(s){
 if(!s.disclosures.length)return '<div class="empty">还没有外发申请。</div>';
 return table(
  ['单号 / 到货月','所含批次','状态','加总值(%)','发起 / 判单'],
  s.disclosures.map(a=>[
   `<button class="review-choice" data-disclosure="${a.id}"><strong>#${a.id} · ${esc(a.month_key)}</strong><small>${esc(a.created_by)} · 第 ${a.attempts} 次</small></button>`,
   esc(a.batch_codes.join('；')),
   dbadge(a.status),
   a.status==='published'?fmt(a.published_sum):'—',
   esc(a.judged_at?a.judged_at.slice(0,16).replace('T',' '):'—')
  ])
 );
}

function disclosureDetail(s,a){
 const internal=s.user.role==='admin';
 return `<div class="report-note">
  <div class="section-head"><h2>申请 #${a.id}</h2>${dbadge(a.status)}</div>
  <p><strong>到货月：</strong>${esc(a.month_key)}　<strong>批次：</strong>${esc(a.batch_codes.join('；'))}</p>
  ${a.status==='published'
    ? `<p class="signed">获准公布的均值加总值：<strong>${fmt(a.published_sum)}%</strong></p><small>该数值与所含批号可进入外发导出。</small>`
    : `<p>当前对外不提供任何数值。${a.status==='rejected'?'本单未通过联立可解性复核。':a.status==='failed'?'落账失败，未对外发出数值，可沿原单重试。':'判单进行中，请稍候。'}</p>`}
  ${internal&&a.status==='rejected'?`
   <h3>内部留痕（仅质量负责人可见）</h3>
   <p>${esc(a.reject_reason)}</p>
   ${table(['涉及批次编号'],(a.solvable_batches||[]).map(b=>[esc(b.batch_code)]))}`:''}
  ${internal&&a.ledger_key?`<p class="checksum">发布账键：${esc(a.ledger_key)}</p>`:''}
  ${a.status==='failed'&&canEdit(s.user)?`<button class="outline" id="disclosure-retry" data-id="${a.id}">沿原单重试</button>`:''}
 </div>`;
}
