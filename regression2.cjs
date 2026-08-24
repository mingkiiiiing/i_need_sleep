const {chromium} = require('playwright');
(async () => {
  const b = await chromium.launch({headless:true, args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage']});
  const c = await b.newContext();
  const p = await c.newPage();
  const allLogs = [];
  p.on('console', m => allLogs.push('[' + m.type() + '] ' + m.text()));
  p.on('pageerror', e => allLogs.push('[pageerror] ' + e.message));
  const paths = ['/#/','/#/project-overview','/#/tech-route','/#/demo-flow','/#/cockpit','/#/stations','/#/heatmap','/#/history'];
  let totalErrs = 0;
  for (const path of paths) {
    allLogs.length = 0;
    await p.goto('http://127.0.0.1:5173' + path, {waitUntil: 'load', timeout: 15000});
    await p.waitForTimeout(2000);
    const errs = allLogs.filter(l => l.startsWith('[error]') || l.startsWith('[pageerror]'));
    const fb = allLogs.filter(l => l.includes('[api] fallback'));
    console.log(path, '| errs:', errs.length, '| fallbacks:', fb.length);
    if (errs.length) errs.slice(0,2).forEach(e => console.log('  ', e.substring(0,180)));
    totalErrs += errs.length;
  }
  console.log('\nTOTAL ERRORS:', totalErrs);
  await b.close();
})();
