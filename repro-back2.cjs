const {chromium} = require('playwright');
(async () => {
  const b = await chromium.launch({headless:true, args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage']});
  const c = await b.newContext();
  const p = await c.newPage();
  const logs = [];
  p.on('console', m => logs.push('[' + m.type() + '] ' + m.text()));
  p.on('pageerror', e => logs.push('[pageerror] ' + e.message));

  // scenario 4: from outside (browser open blank) -> stations -> back
  await p.goto('http://127.0.0.1:5173/#/stations', {waitUntil: 'load', timeout: 15000});
  await p.waitForTimeout(2500);
  console.log('url:', p.url());
  console.log('at stations, articles:', await p.locator('article').count());
  await p.goBack({waitUntil: 'load'});
  await p.waitForTimeout(1500);
  console.log('after back, url:', p.url());
  console.log('articles:', await p.locator('article').count());
  console.log('main count:', await p.locator('main').count());
  const html = await p.content();
  console.log('html length:', html.length);
  console.log('app div content:');
  const appHtml = await p.locator('#app').innerHTML();
  console.log(appHtml.substring(0, 200));
  console.log('---');
  console.log('logs:');
  logs.forEach(l => console.log('  ', l.substring(0, 200)));

  // scenario 5: forward after back
  await p.goForward({waitUntil: 'load'});
  await p.waitForTimeout(2000);
  console.log('\n--- after goForward ---');
  console.log('url:', p.url());
  console.log('articles:', await p.locator('article').count());

  await b.close();
})();
