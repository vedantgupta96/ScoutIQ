const { chromium } = require('/Users/vedantgupta/Documents/Claude/Projects/Nexus AI/frontend/node_modules/playwright');

const BASE = 'http://127.0.0.1:3020';
const routes = [
  { name: 'team', path: '/teams' },
  { name: 'fa', path: '/free-agency?tab=targets' },
  { name: 'offseason', path: '/offseason' },
  { name: 'model', path: '/model' },
];

(async () => {
  const browser = await chromium.launch();

  // --- 1) 200% zoom at 720px viewport: no horizontal document overflow ---
  console.log('== 200% zoom @720px ==');
  {
    const ctx = await browser.newContext({ viewport: { width: 720, height: 900 } });
    await ctx.addInitScript(() => { try { localStorage.setItem('siq-theme', 'dark'); } catch {} });
    for (const route of routes) {
      const page = await ctx.newPage();
      await page.goto(BASE + route.path, { waitUntil: 'domcontentloaded', timeout: 60000 });
      await page.waitForSelector('.siq-decision-strip', { timeout: 90000 });
      await page.evaluate(() => { document.body.style.zoom = '200%'; });
      await page.waitForTimeout(800);
      const o = await page.evaluate(() => {
        const d = document.documentElement;
        return { scrollW: d.scrollWidth, clientW: d.clientWidth };
      });
      console.log(JSON.stringify({ route: route.name, ...o, overflow: o.scrollW > o.clientW + 1 }));
      await page.close();
    }
    await ctx.close();
  }

  // --- 2) Keyboard order desktop (1440): skip link first, controls reachable, focus visible ---
  console.log('== keyboard desktop 1440 ==');
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await ctx.addInitScript(() => { try { localStorage.setItem('siq-theme', 'dark'); } catch {} });
    for (const route of routes) {
      const page = await ctx.newPage();
      await page.goto(BASE + route.path, { waitUntil: 'domcontentloaded', timeout: 60000 });
      await page.waitForSelector('.siq-decision-strip', { timeout: 90000 });
      await page.keyboard.press('Tab');
      const first = await page.evaluate(() => {
        const el = document.activeElement;
        return { text: (el.textContent || '').trim().slice(0, 30), cls: el.className };
      });
      // walk up to 60 tab stops; record whether we reach a control inside <main>
      const seen = [];
      let reachedMainControl = false;
      let missingFocusStyle = [];
      for (let i = 0; i < 60; i++) {
        await page.keyboard.press('Tab');
        const info = await page.evaluate(() => {
          const el = document.activeElement;
          if (!el || el === document.body) return null;
          const inMain = !!el.closest('main');
          const tag = el.tagName.toLowerCase();
          const st = getComputedStyle(el);
          const focusStyled =
            (st.outlineStyle !== 'none' && parseFloat(st.outlineWidth) > 0) ||
            st.boxShadow !== 'none';
          return { tag, inMain, focusStyled, label: (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 25) };
        });
        if (!info) break;
        seen.push(info.tag + (info.inMain ? '@main' : '') + ':' + info.label);
        if (info.inMain && ['select', 'button', 'a', 'input'].includes(info.tag)) reachedMainControl = true;
        if (!info.focusStyled) missingFocusStyle.push(info.tag + ':' + info.label);
      }
      console.log(JSON.stringify({
        route: route.name,
        firstTab: first,
        skipLinkFirst: first.cls.includes('siq-skip-link'),
        reachedMainControl,
        missingFocusStyle: [...new Set(missingFocusStyle)].slice(0, 5),
      }));
      await page.close();
    }
    await ctx.close();
  }

  // --- 3) Mobile (390): desktop sidebar must not receive focus ---
  console.log('== keyboard mobile 390 ==');
  {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
    await ctx.addInitScript(() => { try { localStorage.setItem('siq-theme', 'dark'); } catch {} });
    for (const route of routes) {
      const page = await ctx.newPage();
      await page.goto(BASE + route.path, { waitUntil: 'domcontentloaded', timeout: 60000 });
      await page.waitForSelector('.siq-decision-strip', { timeout: 90000 });
      let sidebarFocused = false;
      const firstStops = [];
      for (let i = 0; i < 25; i++) {
        await page.keyboard.press('Tab');
        const info = await page.evaluate(() => {
          const el = document.activeElement;
          if (!el || el === document.body) return null;
          return {
            inSidebar: !!el.closest('#primary-sidebar'),
            desc: el.tagName.toLowerCase() + ':' + (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 20),
          };
        });
        if (!info) break;
        if (info.inSidebar) sidebarFocused = true;
        if (i < 6) firstStops.push(info.desc);
      }
      console.log(JSON.stringify({ route: route.name, sidebarFocused, firstStops }));
      await page.close();
    }
    await ctx.close();
  }

  // --- 4) DecisionStrip reading order / accessible name ---
  console.log('== decision strip semantics ==');
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await ctx.addInitScript(() => { try { localStorage.setItem('siq-theme', 'dark'); } catch {} });
    for (const route of routes) {
      const page = await ctx.newPage();
      await page.goto(BASE + route.path, { waitUntil: 'domcontentloaded', timeout: 60000 });
      await page.waitForSelector('.siq-decision-strip', { timeout: 90000 });
      const sem = await page.evaluate(() => {
        const s = document.querySelector('.siq-decision-strip');
        const items = [...s.querySelectorAll('.siq-decision-strip__item')].map((it) => ({
          lead: it.classList.contains('siq-decision-strip__item--lead'),
          label: it.querySelector('.siq-decision-strip__label')?.textContent.trim(),
          value: it.querySelector('.siq-decision-strip__value')?.textContent.trim().slice(0, 40),
        }));
        return { role: s.tagName.toLowerCase(), ariaLabel: s.getAttribute('aria-label'), items };
      });
      console.log(JSON.stringify({ route: route.name, ...sem }));
      await page.close();
    }
    await ctx.close();
  }

  await browser.close();
})();
