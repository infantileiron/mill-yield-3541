import {batches,inspections,reviews,disclosures} from '../api/business.js';
export const state={user:null,batches:[],inspections:[],reviews:[],disclosures:[],frozenMeans:[],selected:null,selectedDisclosure:null};
export async function refresh(){
 [state.batches,state.inspections,state.reviews,state.disclosures,state.frozenMeans]=await Promise.all([batches.list(),inspections.list(),reviews.list(),disclosures.list(),disclosures.frozen()]);
 if(state.selected)state.selected=await reviews.get(state.selected.id);
 if(state.selectedDisclosure)state.selectedDisclosure=await disclosures.get(state.selectedDisclosure.id);
}
