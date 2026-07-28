const {chromium} = require('playwright');
(async () => {
  const b = await chromium.launch({headless:true, args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage']});
  const c = await b.newContext();
  const p = await c.newPage();
  const logs = [];
  p.on('console', m => logs.push('[' + m.type() + '] ' + m.text()));
  p.on('pageerror', e => logs.push('[pageerror] ' + e.message));
  await p.goto('http://127.0.0.1:5173/#/heatmap', {waitUntil: 'load', timeout: 15000});
  await p.waitForTimeout(3000);
  const back = await p.locator('.cockpit-foot a').textContent().catch(() => '(none)');
  console.log('back link:', back);
  const errs = logs.filter(l => l.includes('error') || l.includes('pageerror'));
  console.log('errors:', errs.length);
  errs.slice(0,3).forEach(e => console.log(' ', e.substring(0, 200)));
  await b.close();
})();
