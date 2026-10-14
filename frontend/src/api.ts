
const BASE=import.meta.env.VITE_API_URL||'';
export const token=()=>localStorage.getItem('bca_token');
export async function api(path:string,opts:RequestInit={}){
 const r=await fetch(BASE+path,{...opts,headers:{'Content-Type':'application/json',...(token()?{Authorization:`Bearer ${token()}`}:{}) ,...(opts.headers||{})}});
 if(!r.ok){let m=r.statusText; try{m=(await r.json()).detail||m}catch{} throw new Error(`${r.status}: ${m}`)}
 return r.json();
}
export type Project={id:number;name:string;description:string;status:string;ecosystem:string;area_ha:number;country:string;region:string;latitude?:number;longitude?:number;boundary?:any;owner_id:number;reporting_years:number};
