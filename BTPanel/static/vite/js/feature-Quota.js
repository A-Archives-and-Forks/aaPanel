;(() => {
	const stylesheetSelector = "link[rel=stylesheet]"
	const loaded = new Set(Array.from(document.querySelectorAll(stylesheetSelector)).map(link => link.href))
	const version = "1786507437784"
	const findLoadedLink = href => Array.from(document.querySelectorAll(stylesheetSelector)).find(link => link.href === href)
	const removeAfterLoad = (freshLink, staleLink) => {
		const remove = () => staleLink.remove()
		if (freshLink.sheet) {
			requestAnimationFrame(remove)
			return
		}
		freshLink.addEventListener("load", remove, { once: true })
	}
	for (const link of Array.from(document.querySelectorAll(stylesheetSelector))) {
		const url = new URL(link.href, location.href)
		if (url.origin !== location.origin || url.searchParams.get("v") === version) continue
		url.searchParams.set("v", version)
		if (loaded.has(url.href)) {
			const freshLink = findLoadedLink(url.href)
			if (freshLink && freshLink !== link) removeAfterLoad(freshLink, link)
			continue
		}
		const freshLink = document.createElement("link")
		freshLink.rel = "stylesheet"
		freshLink.href = url.href
		link.parentNode?.insertBefore(freshLink, link.nextSibling)
		loaded.add(url.href)
		removeAfterLoad(freshLink, link)
	}
})();
import{r as e}from"./rolldown-runtime.js?v=1786507437784";import{Cn as t,Dn as n,En as r,Ft as i,Jn as a,On as o,Or as s,Sn as c,bn as l,br as u,cr as d,ei as f,kn as p,nn as m,vr as h,xn as g,yn as _}from"./vendor-utils.js?v=1786507437784";import{l as v}from"./vendor-vue.js?v=1786507437784";import{A as y,F as b,St as x,T as S,Tt as C,bt as w,xt as T}from"./vendor-naive.js?v=1786507437784";import{Pf as E,cp as D,ln as O,mn as k}from"./app.js?v=1786507437784";import{Ki as A}from"./app-components.js?v=1786507437784";import{bf as j,xf as M}from"./app-shared.js?v=1786507437784";import{n as N,r as P}from"./vendor-pdf.js?v=1786507437784";m(),P();var F={class:`leading-20px`},I=p({__name:`index`,props:{type:{default:`site`},data:{},callback:{}},setup(e){let{t:c}=v(),u=e,p=_(()=>{let{data:e}=u,{quota:t}=e;return!t.size}),m=_(()=>{if(p.value)return 0;let{data:e}=u,t=i(e,`quota.used`,0),n=i(e,`quota.size`,0);return n=n*1024*1024,n===0?0:t/n*100}),h=_(()=>{let{data:e}=u;return D(i(e,`quota.used`,0))}),y=_(()=>{let{data:e}=u;return`${i(e,`quota.size`,0).toFixed(2)} MB`}),b=_(()=>m.value<90?`success`:`error`),x=new Map([[`site`,`Site`],[`ftp`,`FTP`],[`database`,`Database`]]),w=()=>{E({title:`${c(`Component.Quota.index_5`,[u.data.name,x.get(u.type)||`--`])}`,width:480,minHeight:222,footer:!0,data:{type:u.type,info:u.data,callback:u.callback},component:o(()=>N(()=>Promise.resolve().then(()=>G),void 0))})};return(e,i)=>{let o=k,c=S,u=C;return s(p)?(a(),g(o,{key:0,onClick:w},{default:d(()=>[r(f(e.$t(`Component.Quota.index_2`)),1)]),_:1})):(a(),t(`div`,{key:1,class:`cursor-pointer`,onClick:w},[n(u,{placement:`bottom-start`,"arrow-point-to-center":!0},{trigger:d(()=>[n(c,{type:`line`,status:s(b),percentage:s(m),height:12,"border-radius":2,"show-indicator":!1},null,8,[`status`,`percentage`])]),default:d(()=>[l(`div`,F,[l(`p`,null,f(e.$t(`Component.Quota.index_3`,[s(h)])),1),l(`p`,null,f(e.$t(`Component.Quota.index_12`,[s(y)])),1),l(`p`,null,f(e.$t(`Component.Quota.index_4`)),1)])]),_:1})]))}}}),L=e({default:()=>R}),R=I;m();var z={class:`px-20px py-24px`},B={class:`w-160px`},V={class:`w-160px`},H={class:`text-error`},U={key:0},W=p({__name:`quota-config`,props:{data:{}},setup(e,{expose:o}){let{type:p,info:m,callback:g}=e.data,_=h({used:`0`,size:0}),v=u(`MB`);return(()=>{let e=i(m,`quota.used`,0);if(e>0){let t=D(e).split(` `);_.used=t[0],v.value=t[1]}_.size=i(m,`quota.size`,0)})(),o({onConfirm:async({hide:e})=>{(p===`site`||p===`ftp`)&&await M({size:_.size,quota_type:p,path:i(m,`path`,``)}),p===`database`&&await j({size:_.size,db_name:i(m,`name`,``)}),g==null||g(),e()}}),(e,i)=>{let o=x,u=w,m=T,h=b,g=y,S=A,C=O;return a(),t(`div`,z,[n(S,{"label-width":`180`},{default:d(()=>[n(h,{label:e.$t(`Component.Quota.index_6`)},{default:d(()=>[l(`div`,B,[n(m,null,{default:d(()=>[n(o,{value:s(_).used,"onUpdate:value":i[0]||(i[0]=e=>s(_).used=e),disabled:!0},null,8,[`value`]),n(u,{class:`w-44px text-center`},{default:d(()=>[r(f(s(v)),1)]),_:1})]),_:1})])]),_:1},8,[`label`]),n(h,{label:e.$t(`Component.Quota.index_7`)},{default:d(()=>[l(`div`,V,[n(m,null,{default:d(()=>[n(g,{value:s(_).size,"onUpdate:value":i[1]||(i[1]=e=>s(_).size=e),min:0,"show-button":!1},null,8,[`value`]),n(u,{class:`w-44px text-center`},{default:d(()=>[...i[2]||(i[2]=[r(`MB`,-1)])]),_:1})]),_:1})])]),_:1},8,[`label`])]),_:1}),n(C,{class:`mt-8px`},{default:d(()=>[l(`li`,H,f(e.$t(`Component.Quota.index_8`)),1),l(`li`,null,f(e.$t(`Component.Quota.index_9`)),1),s(p)===`database`?c(``,!0):(a(),t(`li`,U,f(e.$t(`Component.Quota.index_10`)),1)),l(`li`,null,f(e.$t(`Component.Quota.index_11`)),1)]),_:1})])}}}),G=e({default:()=>K}),K=W;export{L as t};