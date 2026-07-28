const {chromium} = require('playwright');
(async () => {
  const b = await chromium.launch({headless:true, args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage']});
  const c = await b.newContext();
  const p = await c.newPage();
  for (const path of ['/#/stations','/#/heatmap','/#/history']) {
    await p.goto('http://127.0.0.1:5173' + path, {waitUntil: 'load', timeout: 15000});
    await p.waitForTimeout(2000);
    const back = await p.locator('.cockpit-foot a').textContent().catch(() => '(none)');
    console.log(path, '| back link:', back.replace(/\s+/g,' ').trim());
    await p.locator('.cockpit-foot a').click();
    await p.waitForTimeout(1500);
    console.log('  → url:', p.url());
  }
  await b.close();
})();
