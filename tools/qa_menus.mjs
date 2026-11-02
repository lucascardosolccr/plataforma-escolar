// Teste de menus no navegador (P9 §9.2 e §16, cenário 8): mouse, teclado e celular.
//
// Não faz parte do pytest porque exigiria o Playwright como dependência do
// projeto. Roda com qualquer executor Playwright (ex.: o browser.mjs da
// skill browser-automation), contra um servidor local com uma CÓPIA do banco:
//
//   QA_BASE=http://127.0.0.1:8765 QA_SENHA=... QA_USUARIOS=demo.direcao,demo.prof2
//   node browser.mjs http://127.0.0.1:8765/ --script tools/qa_menus.mjs
//
// Para cada usuário: entra, abre e fecha o menu da conta com mouse e com
// teclado (Enter, seta, Esc), abre o menu lateral a 390 px e fecha com Esc, e
// visita todo item do menu anotando a situação HTTP e os erros de console.
// Devolve um relatório; qualquer item em "falhas" reprova.

const BASE = process.env.QA_BASE || 'http://127.0.0.1:8765'
const SENHA = process.env.QA_SENHA
const USERS = (process.env.QA_USUARIOS || 'demo.direcao,demo.coordenacao,demo.secretaria,demo.prof2,demo.resp57')
  .split(',').map(s => s.trim()).filter(Boolean)

async function login(page, user) {
  await page.context().clearCookies()
  await page.goto(BASE + '/')
  await page.fill('#id_username', user)
  await page.fill('input[name=password]', SENHA)
  await Promise.all([page.waitForNavigation(), page.locator('form button[type=submit]').first().click()])
}

export default async function run(page) {
  if (!SENHA) return { erro: 'Defina QA_SENHA (senha das contas de demonstração na cópia do banco).' }
  const report = { usuarios: {}, falhas: [] }
  let errors = []
  page.on('pageerror', e => errors.push(String(e)))
  page.on('console', m => { if (m.type() === 'error' && !/kaspersky|inline style/i.test(m.text())) errors.push(m.text()) })
  const fail = (u, msg) => report.falhas.push(`${u}: ${msg}`)

  for (const user of USERS) {
    const r = { itens: 0, http: {}, erros_console: 0 }
    await page.setViewportSize({ width: 1280, height: 900 })
    await login(page, user)
    const btn = page.locator('.profile-btn')
    const menu = page.locator('.dropdown-menu').first()
    // Mouse
    await btn.click()
    if (!(await menu.isVisible()) || (await btn.getAttribute('aria-expanded')) !== 'true') fail(user, 'menu da conta não abriu com clique')
    await page.keyboard.press('Escape')
    if (await menu.isVisible()) fail(user, 'Esc não fechou o menu da conta')
    // Teclado
    await btn.focus()
    await page.keyboard.press('Enter')
    if (!(await menu.isVisible())) fail(user, 'menu da conta não abriu com Enter')
    await page.keyboard.press('ArrowDown')
    const focusedInMenu = await page.evaluate(() => !!document.activeElement.closest('.dropdown-menu'))
    if (!focusedInMenu) fail(user, 'seta para baixo não levou o foco para dentro do menu')
    await page.keyboard.press('Escape')
    const backToButton = await page.evaluate(() => document.activeElement.classList.contains('profile-btn'))
    if (!backToButton) fail(user, 'ao fechar com Esc o foco não voltou ao botão')
    // Itens do menu lateral
    const links = await page.locator('#sidebar a.nav-item').evaluateAll(as => [...new Set(as.map(a => a.getAttribute('href')))])
    r.itens = links.length
    for (const href of links) {
      errors = []
      const resp = await page.goto(BASE + href)
      const status = resp ? resp.status() : 0
      r.http[status] = (r.http[status] || 0) + 1
      if (status >= 400) fail(user, `${href} respondeu ${status}`)
      if (errors.length) { r.erros_console += errors.length; fail(user, `${href}: ${errors[0]}`) }
    }
    // Celular: menu lateral por toque e Esc
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(BASE + '/')
    const sidebar = page.locator('#sidebar')
    await page.locator('button[aria-controls=sidebar]').click()
    await page.waitForTimeout(400)
    if (!(await sidebar.evaluate(el => el.classList.contains('show')))) fail(user, 'menu lateral não abriu no celular')
    await page.keyboard.press('Escape')
    await page.waitForTimeout(400)
    if (await sidebar.evaluate(el => el.classList.contains('show'))) fail(user, 'Esc não fechou o menu lateral no celular')
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    if (overflow > 0) fail(user, `rolagem lateral de ${overflow}px no celular`)
    report.usuarios[user] = r
  }
  report.aprovado = report.falhas.length === 0
  return report
}
