const {chromium} = require('playwright');
(async () => {
  const b = await chromium.launch({headless:true, args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage']});
  const c = await b.newContext();
  const p = await c.newPage();
  const logs = [];
  p.on('console', m => logs.push('[' + m.type() + '] ' + m.text()));
  p.on('pageerror', e => logs.push('[pageerror] ' + e.message));

  // 复现：访问 stations 后用浏览器后退
  await p.goto('http://127.0.0.1:5173/#/stations', {waitUntil: 'load', timeout: 15000});
  await p.waitForTimeout(2500);
  console.log('--- after goto stations ---');
  console.log('articles:', await p.locator('article').count(), '| h1:', await p.locator('h1').first().textContent().catch(()=>'(none)'));

  await p.goBack({waitUntil: 'load'});
  await p.waitForTimeout(1500);
  console.log('--- after goBack (should be home or empty) ---');
  console.log('articles:', await p.locator('article').count(), '| h1:', await p.locator('h1').first().textContent().catch(()=>'(none)'));
  console.log('main:', await p.locator('main').count(), '| length:', (await p.content()).length);

  // 试一下：home -> stations -> back
  console.log('\n=== scenario 2: home -> stations -> back ===');
  logs.length = 0;
  await p.goto('http://127.0.0.1:5173/#/', {waitUntil: 'load', timeout: 15000});
  await p.waitForTimeout(1500);
  await p.goto('http://127.0.0.1:5173/#/stations', {waitUntil: 'load', timeout: 15000});
  await p.waitForTimeout(2500);
  console.log('at stations, articles:', await p.locator('article').count());
  await p.goBack({waitUntil: 'load'});
  await p.waitForTimeout(1500);
  console.log('after back, articles:', await p.locator('article').count(), '| main exists:', await p.locator('main').count());
  if (logs.filter(l => l.includes('error') || l.includes('pageerror')).length) {
    console.log('errors during back:');
    logs.filter(l => l.includes('error') || l.includes('pageerror')).slice(0, 5).forEach(l => console.log('  ', l.substring(0, 250)));
  }

  // scenario 3: stations -> heatmap -> back
  console.log('\n=== scenario 3: stations -> heatmap -> back ===');
  logs.length = 0;
  await p.goto('http://127.0.0.1:5173/#/stations', {waitUntil: 'load', timeout: 15000});
  await p.waitForTimeout(2500);
  await p.goto('http://127.0.0.1:5173/#/heatmap', {waitUntil: 'load', timeout: 15000});
  await p.waitForTimeout(2500);
  console.log('at heatmap, articles:', await p.locator('article').count());
  await p.goBack({waitUntil: 'load'});
  await p.waitForTimeout(1500);
  console.log('after back to stations, articles:', await p.locator('article').count());

  await b.close();
})();
