const fs = require('fs');
const p = 'src/pages/Stations.vue';
let lines = fs.readFileSync(p, 'utf8').split(/\r?\n/);
// 重复：lines[210] = "function setPoint(id) {"  // 我们刚写的
// lines[211] = "const riskClassFromLevel ..."  // 我们刚写的
// lines[212] = ""
// lines[213] = "function setPoint(id) {"  // 原来的
// ...
// 删 213..endFunction 中重复的，最干净：找出第二个 "function setPoint" 之后的重复段
// 简单做法：删掉 lines[213..215]（"function setPoint(id) {" + riskClassFromLevel + ""），它们是原版重复
// 但保留 setPoint 正文

// 先打印看
console.log('current snapshot lines 208..225:');
for (let i = 207; i < 230 && i < lines.length; i++) console.log((i+1)+': '+lines[i]);
