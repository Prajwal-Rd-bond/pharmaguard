const fs = require('fs');
const path = require('path');
const puppeteer = require('../client/node_modules/puppeteer');
const jwt = require('../server/node_modules/jsonwebtoken');

const JWT_SECRET = 'pharmaguard-sec-key-9f8e7d6c5b4a3928170e9f8a7b6c5d4e-2026';

const pharmaToken = jwt.sign(
  { sub: '6ad0674152bd81270f3c3f03', role: 'pharmacist' },
  JWT_SECRET,
  { expiresIn: '8h' }
);

const doctorToken = jwt.sign(
  { sub: '6ad0674152bd81270f3c3f06', role: 'doctor' },
  JWT_SECRET,
  { expiresIn: '8h' }
);

const adminToken = jwt.sign(
  { sub: '6ad0674152bd81270f3c3f00', role: 'admin' },
  JWT_SECRET,
  { expiresIn: '8h' }
);

async function setAuth(page, token) {
  await page.evaluate((t) => {
    localStorage.setItem('pharmaguard_token', t);
    sessionStorage.setItem('pg_intro_seen', '1');
  }, token);
}

async function main() {
  const screenshotsDir = path.join(__dirname, '..', 'docs', 'screenshots');
  if (!fs.existsSync(screenshotsDir)) {
    fs.mkdirSync(screenshotsDir, { recursive: true });
  }

  const sampleReportId = '6a691d337ac8072e5453265a';

  const browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: 'new',
    defaultViewport: { width: 1440, height: 900, deviceScaleFactor: 2 },
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu']
  });

  const page = await browser.newPage();

  // 1. Capture Login Screen
  console.log('1. Capturing login screen...');
  await page.goto('http://localhost:5173/login?intro=1', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 800));
  await page.screenshot({ path: path.join(screenshotsDir, '01-login-screen.png') });

  // 2. Capture Dashboard (Pharmacist)
  console.log('2. Capturing dashboard...');
  await setAuth(page, pharmaToken);
  await page.goto('http://localhost:5173/dashboard', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 1200));
  await page.screenshot({ path: path.join(screenshotsDir, '02-action-center-dashboard.png') });

  // 3. Capture Case Triage Table
  console.log('3. Capturing cases triage...');
  await page.goto('http://localhost:5173/cases', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 1200));
  await page.screenshot({ path: path.join(screenshotsDir, '03-case-triage.png') });

  // 4. Capture Report Detail Reviewer Cockpit (Extraction Tab)
  console.log('4. Capturing report detail (Extraction tab)...');
  await page.goto(`http://localhost:5173/reports/${sampleReportId}`, { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: path.join(screenshotsDir, '04-report-reviewer-cockpit.png') });

  // 5. Capture Report Detail (Causality Tab with Naranjo Questionnaire)
  console.log('5. Capturing report detail (Causality tab)...');
  await page.evaluate(() => {
    const buttons = Array.from(document.querySelectorAll('button'));
    const btn = buttons.find(b => b.textContent.includes('Causality'));
    if (btn) btn.click();
  });
  await new Promise(r => setTimeout(r, 1200));
  await page.screenshot({ path: path.join(screenshotsDir, '05-report-causality-naranjo.png') });

  // 6. Capture Multi-Modal Intake (Doctor View)
  console.log('6. Capturing multimodal intake (Doctor)...');
  await setAuth(page, doctorToken);
  await page.goto('http://localhost:5173/intake', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 1200));
  await page.screenshot({ path: path.join(screenshotsDir, '06-multimodal-intake.png') });

  // 7. Capture Disproportionality & Signal Analytics (Pharmacist)
  console.log('7. Capturing signal analytics...');
  await setAuth(page, pharmaToken);
  await page.goto('http://localhost:5173/analytics', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 1200));
  await page.screenshot({ path: path.join(screenshotsDir, '07-signal-analytics.png') });

  // 8. Capture MedDRA Knowledge Graph
  console.log('8. Capturing MedDRA knowledge graph...');
  await page.evaluate(() => {
    const buttons = Array.from(document.querySelectorAll('button'));
    const btn = buttons.find(b => b.textContent.includes('MedDRA Knowledge Graph'));
    if (btn) btn.click();
  });
  await new Promise(r => setTimeout(r, 1500));
  await page.screenshot({ path: path.join(screenshotsDir, '08-meddra-knowledge-graph.png') });

  // 9. Capture Cryptographic Audit Log (Admin)
  console.log('9. Capturing cryptographic audit log...');
  await setAuth(page, adminToken);
  await page.goto('http://localhost:5173/audit-logs', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 1200));
  await page.screenshot({ path: path.join(screenshotsDir, '09-cryptographic-audit-log.png') });

  await browser.close();
  console.log('Successfully captured all 9 UI screenshots in docs/screenshots!');
}

main().catch(err => {
  console.error('Capture error:', err);
  process.exit(1);
});
