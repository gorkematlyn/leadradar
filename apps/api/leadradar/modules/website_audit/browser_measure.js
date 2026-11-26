// Deterministic DOM measurements executed inside the audited page (read-only; no clicks, no input).
() => {
  const de = document.documentElement;
  const vw = de.clientWidth;
  const vh = window.innerHeight;
  const sw = de.scrollWidth;
  const MAX = 4000;
  const vis = (el) => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity || '1') > 0.05 && r.width > 0 && r.height > 0;
  };
  const sel = (el) => {
    if (el.id) return el.tagName.toLowerCase() + '#' + CSS.escape(el.id);
    let p = el.tagName.toLowerCase();
    const cls = [...el.classList].slice(0, 2).map((c) => '.' + CSS.escape(c)).join('');
    const parent = el.parentElement ? el.parentElement.tagName.toLowerCase() : '';
    return (parent ? parent + ' > ' : '') + p + cls;
  };
  const all = document.body ? [...document.body.querySelectorAll('*')].slice(0, MAX) : [];
  const visible = all.filter(vis);

  const overflow = [];
  for (const el of visible) {
    const r = el.getBoundingClientRect();
    const pos = getComputedStyle(el).position;
    if (r.right > vw + 2 && pos !== 'fixed') {
      overflow.push({ selector: sel(el), right: Math.round(r.right), width: Math.round(r.width) });
      if (overflow.length >= 10) break;
    }
  }

  let textEls = 0, small = 0; const smallExamples = [];
  for (const el of visible) {
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim().length > 2);
    if (!own) continue;
    textEls++;
    const fs = parseFloat(getComputedStyle(el).fontSize);
    if (fs < 12) { small++; if (smallExamples.length < 6) smallExamples.push({ selector: sel(el), fontSize: fs }); }
  }

  const interactive = [...document.querySelectorAll('a[href], button, input:not([type=hidden]), select, textarea, [role=button]')]
    .filter(vis).slice(0, 600);
  const smallTargets = [];
  for (const el of interactive) {
    const r = el.getBoundingClientRect();
    const inline = getComputedStyle(el).display === 'inline' && el.closest('p, li, td');
    if (!inline && (r.width < 24 || r.height < 24)) smallTargets.push({ selector: sel(el), w: Math.round(r.width), h: Math.round(r.height) });
  }

  const overlaps = [];
  const rects = interactive.slice(0, 150).map((el) => [el, el.getBoundingClientRect()]);
  outer: for (let i = 0; i < rects.length; i++) {
    for (let j = i + 1; j < rects.length; j++) {
      const [a, ra] = rects[i]; const [b, rb] = rects[j];
      if (a.contains(b) || b.contains(a)) continue;
      const ix = Math.max(0, Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left));
      const iy = Math.max(0, Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top));
      const minArea = Math.min(ra.width * ra.height, rb.width * rb.height);
      if (minArea > 0 && (ix * iy) / minArea > 0.3) { overlaps.push({ a: sel(a), b: sel(b) }); if (overlaps.length >= 10) break outer; }
    }
  }

  const clipped = [];
  for (const el of visible) {
    if (el.children.length) continue;
    const s = getComputedStyle(el);
    const hides = s.overflow === 'hidden' || s.overflowX === 'hidden' || s.textOverflow === 'ellipsis';
    if (hides && el.scrollWidth > el.clientWidth + 4 && el.textContent.trim().length > 3) {
      clipped.push(sel(el)); if (clipped.length >= 10) break;
    }
  }

  const offscreen = [];
  for (const el of visible) {
    const s = getComputedStyle(el);
    if (s.position === 'fixed') continue;
    const r = el.getBoundingClientRect();
    if (r.left < -5 && r.right > 5 && el.textContent.trim().length > 2 && el.children.length === 0) {
      offscreen.push({ selector: sel(el), left: Math.round(r.left) }); if (offscreen.length >= 10) break;
    }
  }

  const overlays = [];
  for (const el of visible) {
    const s = getComputedStyle(el);
    if (s.position !== 'fixed' && s.position !== 'sticky') continue;
    const r = el.getBoundingClientRect();
    const ix = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0));
    const iy = Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0));
    const cover = (ix * iy) / (vw * vh);
    if (cover > 0.35) {
      const text = (el.innerText || '').slice(0, 300).toLowerCase();
      overlays.push({ selector: sel(el), cover: Math.round(cover * 100) / 100,
        cookie: /cookie|çerez|consent|gdpr|kvkk|privacy|datenschutz|toestemming/.test(text) });
      if (overlays.length >= 5) break;
    }
  }

  const navs = [...document.querySelectorAll('header nav, nav, [role=navigation]')].filter(vis).slice(0, 3);
  const toggle = !!document.querySelector('button[aria-expanded], [aria-controls*=menu i], .hamburger, .menu-toggle, .navbar-toggler, [class*=burger], [class*=mobile-menu]');
  const nav = navs.map((n) => {
    const r = n.getBoundingClientRect();
    const links = [...n.querySelectorAll('a')].filter(vis);
    const tops = new Set(links.map((l) => Math.round(l.getBoundingClientRect().top)));
    return { selector: sel(n), width: Math.round(r.width), visibleLinks: links.length, rows: tops.size };
  });

  let fontErrors = 0, fontsLoaded = 0;
  try { document.fonts.forEach((f) => { if (f.status === 'error') fontErrors++; if (f.status === 'loaded') fontsLoaded++; }); } catch (e) {}

  const brokenImages = [...document.images].filter((i) => i.complete && i.naturalWidth === 0 && vis(i) && i.src && !i.src.startsWith('data:'))
    .slice(0, 20).map((i) => ({ selector: sel(i), src: i.currentSrc || i.src }));

  const globals = ['fbq', 'ttq', 'uetq', 'pintrk', 'clarity', 'hj', 'google_tag_manager', 'gtag', 'dataLayer',
    '_linkedin_data_partner_ids', 'Cookiebot', 'OneTrust', 'UC_UI', '__tcfapi', 'Didomi'].filter((g) => typeof window[g] !== 'undefined');

  return {
    viewport: { width: vw, height: vh, scrollWidth: sw, scrollHeight: de.scrollHeight },
    overflow, textElements: textEls, smallText: small, smallTextExamples: smallExamples,
    interactiveCount: interactive.length, smallTargets: smallTargets.slice(0, 15), smallTargetCount: smallTargets.length,
    overlaps, clipped, offscreen, overlays, nav, navToggle: toggle, fontErrors, fontsLoaded, brokenImages, globals,
    cls: window.__lrCLS || 0,
  };
}
