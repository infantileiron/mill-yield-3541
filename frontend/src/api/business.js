import {api,post,download} from './client.js';
export const batches={list:()=>api('/batches'),create:d=>post('/batches',d)};
export const inspections={list:()=>api('/inspections'),create:d=>post('/inspections',d)};
export const reviews={list:()=>api('/reviews'),get:id=>api('/reviews/'+id),create:d=>post('/reviews',d),approve:(id,note)=>post(`/reviews/${id}/approve`,{note}),download};
export const disclosures={
  list:()=>api('/disclosures'),
  get:id=>api('/disclosures/'+id),
  create:batch_ids=>post('/disclosures',{batch_ids}),
  retry:id=>post(`/disclosures/${id}/retry`,{}),
  frozen:()=>api('/disclosures/frozen-means'),
  download:()=>fetch('/api/disclosures-export',{headers:{Authorization:'Bearer '+localStorage.getItem('mill-token')}}).then(r=>{if(!r.ok)throw Error('暂无可导出的已发布数据或请求被拒绝');return r.blob();}).then(blob=>{const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='mill-disclosure-published.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),5000);})
};
