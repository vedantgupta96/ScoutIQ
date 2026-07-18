const { chromium } = require('/Users/vedantgupta/Documents/Claude/Projects/Nexus AI/frontend/node_modules/playwright');
const fs = require('fs');

const BASE = 'http://127.0.0.1:3020';
const SHOTS = process.env.SHOTS_DIR;
const routes = [
  { name: 'team', path: '/teams' },
  { name: 'fa', path: '/free-agency?tab=targets' },
  { name: 'offseason', path: '/offseason' },
  { name: 'model', path: '/model' },
];
const viewports = [
  { name: '1440', width: 1440, height: 900 },
  { name: '390', width: 390, height: 844 },
  { name: '320', width: 320, height: 680 },
];
const themes = ['dark', 'light'];

(async () => {
  const browser = await chromium.launch();
  const results = [];
  for (const theme of themes) {
    for (const vp of viewports) {
      const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
      await context.addInitScript((t) => {
        try { localStorage.setItem('siq-theme', t); } catch {}
      }, theme);
      for (const route of routes) {
        const page = await context.newPage();
        const errors = [];
        page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
        page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
        const r = { theme, vp: vp.name, route: route.name, ok: false, strips: 0, overflow: null, errors };
        try {
          await page.goto(BASE + route.path, { waitUntil: 'domcontentloaded', timeout: 60000 });
          await page.waitForSelector('.siq-decision-strip', { timeout: 90000 });
          await page.waitForTimeout(1200); // let late data/paint settle
          r.strips = await page.locator('.siq-decision-strip').count();
          r.overflow = await page.evaluate(() => {
            const d = document.documentElement;
            return { scrollW: d.scrollWidth, clientW: d.clientWidth, bodyScrollW: document.body.scrollWidth };
          });
          r.hasOverflow = r.overflow.scrollW > r.overflow.clientW + 1 || r.overflow.bodyScrollW > r.overflow.clientW + 1;
          r.themeAttr = await page.evaluate(() => document.documentElement.getAttribute('data-theme') || 'light');
          await page.screenshot({ path: `${SHOTS}/${route.name}-${vp.name}-${theme}.png` });
          r.ok = r.strips === 1 && !r.hasOverflow;
        } catch (e) {
          r.fail = e.message.split('\n')[0];
        }
        results.push(r);
        console.log(JSON.stringify({ theme, vp: vp.name, route: route.name, ok: r.ok, strips: r.strips, hasOverflow: r.hasOverflow, themeAttr: r.themeAttr, fail: r.fail, errCount: errors.length }));
        await page.close();
      }
      await context.close();
    }
  }
  await browser.close();
  const bad = results.filter((r) => !r.ok || r.errors.length);
  fs.writeFileSync(`${SHOTS}/results.json`, JSON.stringify(results, null, 2));
  console.log('\nSUMMARY: ' + results.filter((r) => r.ok).length + '/' + results.length + ' passed');
  for (const b of bad) console.log('ISSUE: ' + JSON.stringify(b));
})();
