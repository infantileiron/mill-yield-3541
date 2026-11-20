/** @typedef {{id:number,code:string,line:string,supplier:string,tonnes:number,received_date:string,samples:number}} Batch */
/** @typedef {{sample_code:string,batch_id:number,flour_yield:number,moisture:number,inspector:string}} Inspection */
/** @typedef {{id:number,title:string,line:string,status:string,result:object,note:string}} Review */
/** @typedef {{id:number,month_key:string,batch_ids:number[],batch_codes:string[],status:'pending'|'judging'|'rejected'|'published'|'failed',published_sum:number|null,requested_sum:number|null,reject_reason:string,solvable_batches:Array<{batch_id:number,batch_code:string}>,ledger_key:string|null,attempts:number,created_by:string,created_at:string,judged_at:string|null}} DisclosureApplication */
/** @typedef {{batch_id:number,batch_code:string,month_key:string,sample_count:number,frozen_at:string}} FrozenBatchMean */
export const API_VERSION='1';
