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
import{r as e}from"./rolldown-runtime.js?v=1786507437784";import{Cn as t,Gn as n,Hn as r,Jn as i,Or as a,Zr as o,br as s,f as c,kn as l,n as u,nn as d,or as f,y as p,zn as m}from"./vendor-utils.js?v=1786507437784";import{in as h}from"./vendor-naive.js?v=1786507437784";import{zf as g}from"./app.js?v=1786507437784";import{A as _,D as v,E as y,N as b,O as x,S,_ as C,a as w,c as T,d as E,f as D,h as O,i as k,k as A,l as j,m as M,o as N,p as P,s as F,u as I}from"./vendor-charts.js?v=1786507437784";d(),b([P,C,j,O,N,F,I,v,_,w,k]);var L=A,R=l({__name:`index`,props:{width:{type:[Number,String],default:`100%`},height:{type:[Number,String],default:`200px`},dataZoom:{type:Boolean,default:!1},option:{type:Object,required:!0}},setup(e,{expose:c}){let l=e,u=s(null),d=null;function g(){u.value!==null&&(d=L.getInstanceByDom(u.value),d==null&&(d=L.init(u.value)),d.setOption(l.option,!0))}function _(){var e;u.value!==null&&((e=L.getInstanceByDom(u.value))==null||e.resize())}f(()=>l.option,e=>{e&&m(()=>{g()})},{immediate:!0,deep:!0});let v=p(_,300,{maxWait:800});return n(()=>{g(),window.addEventListener(`resize`,v)}),r(()=>{var e;u.value&&((e=L.getInstanceByDom(u.value))==null||e.dispose(),window.removeEventListener(`resize`,v))}),c({getChart:()=>d}),(n,r)=>(i(),t(`div`,{ref_key:`chartRef`,ref:u,style:o({width:a(h)(e.width),height:a(h)(e.height)})},null,4))}}),z=e({default:()=>B}),B=R;b([P,C,j,O,N,F,I,M,x,_,w,k]);var V=A;d();var H=l({__name:`index`,props:{width:{type:[Number,String],default:`100%`},height:{type:[Number,String],default:`200px`},dataZoom:{type:Boolean,default:!1},option:{type:Object,required:!0}},setup(e,{expose:l}){let u=e,d=s(null);function g(){if(d.value===null)return;let e=V.getInstanceByDom(d.value);e==null&&(e=V.init(d.value)),e.setOption(u.option,!0),requestAnimationFrame(()=>e.resize())}function _(){var e;d.value!==null&&((e=V.getInstanceByDom(d.value))==null||e.resize())}f(()=>u.option,e=>{e&&m(()=>{g()})},{immediate:!0,deep:!0});let v=p(_,80,{maxWait:240});return c(d,()=>{v()}),n(()=>{m(()=>{g(),window.addEventListener(`resize`,v)})}),r(()=>{var e;d.value&&((e=V.getInstanceByDom(d.value))==null||e.dispose(),window.removeEventListener(`resize`,v))}),l({resize:_,getChart:()=>V.getInstanceByDom(d.value)}),(n,r)=>(i(),t(`div`,{ref_key:`chartRef`,ref:d,class:`bt-line-chart`,style:o({width:a(h)(e.width),height:a(h)(e.height)})},null,4))}}),U=e({default:()=>W}),W=g(H,[[`__scopeId`,`data-v-ba6e3b19`]]);b([D,P,C,j,O,N,F,I,T,S,_,w,k,E]);var G=A;d();var K=l({__name:`index`,props:{width:{type:[Number,String],default:`100%`},height:{type:[Number,String],default:`200px`},dataZoom:{type:Boolean,default:!1},option:{type:Object,required:!0}},setup(e,{expose:l}){let d=e,g=s(null),_=!0;async function v(){if(_){let{data:e}=await u.get(`/static/vite/data/world.json`);G.registerMap(`world`,e),_=!1}if(g.value===null)return;let e=G.getInstanceByDom(g.value);e==null&&(e=G.init(g.value)),e.setOption(d.option,!0),requestAnimationFrame(()=>e.resize())}function y(){var e;g.value!==null&&((e=G.getInstanceByDom(g.value))==null||e.resize())}f(()=>d.option,e=>{e&&m(()=>{v()})},{immediate:!0,deep:!0});let b=p(y,80,{maxWait:240});return c(g,()=>{b()}),n(async()=>{window.addEventListener(`resize`,b)}),r(()=>{var e;g.value&&((e=G.getInstanceByDom(g.value))==null||e.dispose(),window.removeEventListener(`resize`,b))}),l({resize:y}),(n,r)=>(i(),t(`div`,{ref_key:`chartRef`,ref:g,class:`bt-map-chart`,style:o({width:a(h)(e.width),height:a(h)(e.height)})},null,4))}}),q=e({default:()=>J}),J=g(K,[[`__scopeId`,`data-v-4b805b22`]]);b([D,P,C,j,O,N,F,I,y,_,w,k]);var Y=A;d();var X=l({__name:`index`,props:{width:{type:[Number,String],default:`100%`},height:{type:[Number,String],default:`200px`},dataZoom:{type:Boolean,default:!1},option:{type:Object,required:!0}},setup(e){let c=e,l=s(null);function u(){if(l.value===null)return;let e=Y.getInstanceByDom(l.value);e==null&&(e=Y.init(l.value)),e.setOption(c.option,!0)}function d(){var e;l.value!==null&&((e=Y.getInstanceByDom(l.value))==null||e.resize())}f(()=>c.option,e=>{e&&m(()=>{u()})},{immediate:!0,deep:!0});let g=p(d,300,{maxWait:800});return n(()=>{m(()=>{u(),window.addEventListener(`resize`,g)})}),r(()=>{var e;l.value&&((e=Y.getInstanceByDom(l.value))==null||e.dispose(),window.removeEventListener(`resize`,g))}),(n,r)=>(i(),t(`div`,{ref_key:`chartRef`,ref:l,style:o({width:a(h)(e.width),height:a(h)(e.height)})},null,4))}}),Z=e({default:()=>Q}),Q=X;export{z as a,U as i,q as n,G as r,Z as t};