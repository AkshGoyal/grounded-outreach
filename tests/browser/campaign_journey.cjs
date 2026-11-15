// Run against tests.fakes.workspace_server only. All providers are simulated.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  assert(process.env.QA_BASE_URL, 'Set QA_BASE_URL to a fresh tests.fakes.workspace_server --no-auth instance.');
  const url = new URL(process.env.QA_BASE_URL);
  assert.equal(url.protocol, 'http:');
  assert.equal(url.hostname, '127.0.0.1');
  assert(url.port && !url.username && !url.password && !url.search && !url.hash && url.pathname === '/',
    'QA_BASE_URL must be an explicit loopback origin with a port.');
  const base = url.origin;
  // A read-only fixture probe must succeed before browser launch or workflow writes.
  const response = await fetch(base + '/qa/state', { redirect: 'error', signal: AbortSignal.timeout(5000) });
  assert(response.ok && response.headers.get('content-type')?.includes('application/json'),
    'Expected a disposable QA server; never use the owner application.');
  assert.deepEqual(await response.json(), { calls: 0, runs: [], sent: 0 },
    'Restart the fictional QA server before each journey.');
  const { chromium } = require('playwright');
  const output = path.resolve('data/campaign-acceptance');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({
    ...(process.env.QA_CHROMIUM_PATH ? { executablePath: process.env.QA_CHROMIUM_PATH } : {}),
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  const errors = [], external = [], overflow = [], unlabeled = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  await page.route('**/*', route => {
    if (new URL(route.request().url()).origin !== base) {
      external.push(route.request().url());
      return route.abort();
    }
    return route.continue();
  });
  const openDetails = async () => page.locator('details').evaluateAll(items => items.forEach(item => item.open = true));
  const audit = async (name) => {
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) overflow.push(name);
    const missing = await page.locator('input:not([type=hidden]),textarea,select').evaluateAll(items => items
      .filter(item => !item.labels?.length && !item.getAttribute('aria-label') && !item.getAttribute('aria-labelledby'))
      .map(item => item.name || item.type));
    missing.forEach(field => unlabeled.push({ page: name, field }));
    await page.screenshot({ path: path.join(output, name + '.png'), fullPage: true });
  };
  const until = async (url, selector) => {
    for (let i = 0; i < 20; i++) {
      await page.goto(base + url);
      if (await page.locator(selector).count()) return;
      await page.waitForTimeout(150);
    }
    throw new Error('Workflow never reached ' + selector + ' at ' + url);
  };

  await page.goto(base + '/');
  await audit('first-use-home');
  await page.locator('[name=brief]').fill('Find AI product startups for job outreach.');
  await page.locator('.goal-start [value=save_prompt]').click();
  const run = new URL(page.url()).pathname;
  assert(await page.getByText('We need a little more detail', { exact: false }).count());
  await page.locator('.audience-form [name=brief]').fill('Find AI product startups in Bangalore for job outreach, accepting founder, HR or senior management emails.');
  await openDetails();
  await page.locator('.audience-form [name=target]').fill('2');
  await page.locator('.audience-form [name=budget]').fill('.20');
  await page.locator('.audience-form [value=save_prompt]').click();
  assert(await page.getByText('Plan prepared for free', { exact: false }).count());
  await until(run, '[name=summary]');
  await audit('plan-review');
  await page.locator('[name=confirm]').check();
  await page.getByRole('button', { name: 'Approve plan & find leads', exact: false }).click();
  await until(run, '[aria-label="Select Atlas AI"]');
  await audit('lead-review');
  await openDetails();
  await page.locator('[aria-label="Select Beacon AI"]').check();
  await page.getByRole('button', { name: 'Remove selected', exact: true }).click();
  await openDetails();
  await page.locator('[aria-label="Select Atlas AI"]').check();
  await page.locator('[name=confirmed]').check();
  await page.getByRole('button', { name: 'Approve selected', exact: true }).click();
  await page.locator('[aria-label="Select Atlas AI"]').check();
  await openDetails();
  await page.getByRole('button', { name: 'Create campaign with selected contacts', exact: true }).click();
  assert.equal(await page.locator('[name=message_prompt]').count(), 1);
  assert.equal(await page.locator('[name=topic],[name=closing]').count(), 0);
  await page.locator('[name=message_prompt]').fill('Introduce Candidate, who is interested in product engineering and built a document search project. Ask the recipient to reply if this background could be useful. Use a concise professional tone.\n\n[KEEP]\nReply if my background could be useful.\nRegards, Candidate\n[/KEEP]');
  await openDetails();
  await page.locator('[name=name]').fill('Desktop AI Career');
  await audit('campaign-create');
  await page.getByRole('button', { name: 'Create campaign', exact: false }).click();
  const campaign = new URL(page.url()).pathname;
  await page.locator('.campaign-tabs').getByRole('link', { name: 'Drafts', exact: true }).click();
  await page.getByRole('button', { name: 'Write all remaining emails', exact: true }).click();
  await until(campaign + '/drafts', 'tr[data-draft-id]');
  await page.getByRole('link', { name: 'Review', exact: true }).click();
  assert(await page.getByText('Atlas AI builds an AI document assistant in Bengaluru.', { exact: false }).count());
  await audit('draft-review');
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await page.locator('.campaign-tabs').getByRole('link', { name: 'Launch', exact: true }).click();
  assert(await page.getByText('Launch is blocked:', { exact: false }).count());
  assert.equal(await page.getByRole('button', { name: /Send .* now/ }).count(), 0);

  const accountIds = {};
  for (const [email, provider] of [['career@gmail.com', 'gmail'], ['sales@example.com', 'zoho']]) {
    await page.goto(base + '/accounts');
    await page.locator('[name=provider]').selectOption(provider);
    await page.locator('[name=label]').fill(provider === 'gmail' ? 'Career Gmail' : 'Sales Zoho');
    await page.locator('[name=email]').fill(email);
    await page.locator('[name=password]').fill('fake-app-password');
    await page.locator('[name=sender_name]').fill('Candidate');
    await page.locator('[name=company]').fill('Personal outreach');
    await page.locator('[name=address]').fill('Test postal address');
    await page.getByRole('button', { name: 'Save & verify connection', exact: true }).click();
    const card = page.locator('article.work-card').filter({ hasText: email });
    assert(await card.getByText('Verified', { exact: true }).count());
    accountIds[email] = (await card.getByRole('link', { name: 'Edit account', exact: true }).getAttribute('href')).split('=')[1];
  }
  await audit('accounts');
  await page.goto(base + campaign + '/settings');
  await page.locator('[name=account_id]').selectOption(accountIds['career@gmail.com']);
  await page.getByRole('button', { name: 'Save settings', exact: true }).click();
  await page.goto(base + campaign + '/drafts');
  await page.locator('[data-select-drafts]').check();
  await page.locator('[name=confirm_selection]').check();
  await page.getByRole('button', { name: 'Approve selected that pass checks', exact: true }).click();
  await page.locator('.campaign-tabs').getByRole('link', { name: 'Launch', exact: true }).click();
  await audit('launch-review');
  await page.locator('[name=confirm_send]').check();
  await page.getByRole('button', { name: 'Send 1 email now', exact: true }).click();
  await until('/sending', 'a[href="' + campaign + '"]');
  await page.goto(base + campaign + '/history');
  assert(await page.getByText('Accepted by provider', { exact: false }).count());
  await openDetails();
  await audit('message-history');
  await page.request.post(base + '/qa/reply', { form: { body: 'Happy to talk.' } });
  await page.goto(base + '/inbox?account_id=' + accountIds['career@gmail.com']);
  await page.getByRole('button', { name: 'Check for replies', exact: true }).click();
  await page.locator('a[href^="/replies/"]').first().click();
  await audit('conversation');
  await page.locator('[name=body]').fill('Thank you. I would be happy to talk.');
  await page.getByRole('button', { name: 'Send answer', exact: true }).click();
  await page.goto(base + campaign + '/history');
  assert(await page.getByText('Reply answer', { exact: false }).count());

  await page.goto(base + '/campaigns/new');
  await openDetails();
  await page.locator('[name=name]').fill('Desktop Partnerships');
  await page.locator('[name=purpose]').selectOption('partnerships');
  await page.locator('[name=message_prompt]').fill('Write a concise product partnership outreach email. We build document search tools. Ask the recipient to reply if a product partnership would be useful. Use only supplied sender facts and reviewed recipient evidence.');
  await page.locator('[name=account_id]').selectOption(accountIds['sales@example.com']);
  await page.getByRole('button', { name: 'Create campaign', exact: false }).click();
  const second = new URL(page.url()).pathname;
  await page.locator('.campaign-tabs').getByRole('link', { name: 'Contacts', exact: true }).click();
  await page.getByRole('link', { name: 'Import a spreadsheet', exact: true }).click();
  assert.equal(await page.locator('[name=campaign]').inputValue(), second.split('/').pop());
  await page.locator('[name=file]').setInputFiles({ name: 'audience.csv', mimeType: 'text/csv', buffer: Buffer.from('Company,Email,Product\nPartner,hello@partner.example,Document tools\n') });
  await page.getByRole('button', { name: 'Preview', exact: true }).click();
  assert(await page.getByText('Nothing was written.', { exact: false }).count());
  // File inputs intentionally reset on navigation; choose the same file to commit.
  await page.locator('[name=file]').setInputFiles({ name: 'audience.csv', mimeType: 'text/csv', buffer: Buffer.from('Company,Email,Product\nPartner,hello@partner.example,Document tools\n') });
  await page.getByRole('button', { name: 'Preview and import', exact: true }).click();
  await page.goto(base + second + '/drafts');
  await page.getByRole('button', { name: 'Write all remaining emails', exact: true }).click();
  await until(second + '/drafts', 'tr[data-draft-id]');
  await page.locator('[data-select-drafts]').check();
  await page.locator('[name=confirm_selection]').check();
  await page.getByRole('button', { name: 'Approve selected that pass checks', exact: true }).click();
  await page.locator('.campaign-tabs').getByRole('link', { name: 'Launch', exact: true }).click();
  assert(await page.getByText('Candidate <sales@example.com>', { exact: false }).count());
  await page.locator('[name=confirm_send]').check();
  await page.getByRole('button', { name: 'Send 1 email now', exact: true }).click();
  await until('/sending', 'a[href="' + second + '"]');
  await page.goto(base + '/');
  await audit('returning-home');
  await openDetails();
  await page.locator('.sidebar').getByRole('button', { name: 'Back up workspace', exact: true }).click();
  const downloaded = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Download workspace backup', exact: true }).click();
  const backup = await downloaded;
  await backup.saveAs(path.join(output, 'fictional-workspace.zip'));
  await audit('backup');
  for (const route of ['/research', '/lists', '/campaigns', '/inbox', '/setup', '/accounts/oauth', '/suppressions']) {
    await page.goto(base + route);
    await audit(route.replaceAll('/', '-') + '-desktop');
  }
  assert.deepEqual(errors, []);
  assert.deepEqual(external, []);
  assert.deepEqual(overflow, []);
  assert.deepEqual(unlabeled, []);
  const report = { providers: 'simulated only', desktopWidth: 1440, researchApproval: true,
    leadRemovalAndApproval: true, personalizedDraftReview: true, launchBlockedWithoutSender: true,
    twoCampaignAccounts: true, controlledSending: true, replyAnswer: true, importPreviewAndCommit: true,
    persistentHistory: true, downloadableBackup: true, browserErrors: errors,
    externalBrowserRequests: external, horizontalOverflow: overflow, unlabelledControls: unlabeled };
  fs.writeFileSync(path.join(output, 'browser-report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
