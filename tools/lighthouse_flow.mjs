// Auditoria Lighthouse por perfil, entrando pelo formulário de login.
//
// Não é dependência do projeto: instale as duas ferramentas numa pasta
// temporária, fora do repositório, e rode de lá apontando para este arquivo.
//
//   cd <pasta temporária>
//   npm init -y && npm pkg set type=module
//   npm install lighthouse@13.5.0 puppeteer-core@25.13.0
//   set CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe
//   set QA_SENHA=<senha das contas demo, só numa CÓPIA do banco>
//   node <projeto>\tools\lighthouse_flow.mjs
//
// Por que fluxo e não `npx lighthouse --extra-headers "Cookie: ..."`: com o
// cabeçalho de sessão fixo, as páginas autenticadas falham com NO_NAVSTART
// (Chrome 156, Lighthouse 12.8.2 e 13.5.0, 02/11/2026). Entrando pelo
// formulário, o cookie é o do próprio navegador e a medição funciona.
//
// Variáveis: QA_BASE (padrão http://127.0.0.1:8765), QA_SENHA, CHROME_PATH,
// QA_SAIDA (pasta para os JSON completos; padrão: a pasta atual).
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'

const require = createRequire(path.join(process.cwd(), 'noop.js'))
// Resolve as ferramentas a partir da pasta onde foram instaladas (a atual).
const load = name => import(pathToFileURL(require.resolve(name)).href)
const puppeteer = (await load('puppeteer-core')).default
const { startFlow, desktopConfig } = await load('lighthouse')

const B = process.env.QA_BASE || 'http://127.0.0.1:8765'
const SENHA = process.env.QA_SENHA
const SAIDA = process.env.QA_SAIDA || '.'
if (!SENHA) throw new Error('Defina QA_SENHA (senha das contas demo na cópia do banco).')

const PLANO = [
  ['demo.aluna145', 'mobile', ['/conteudos-da-prova/1/', '/']],
  ['demo.resp57', 'mobile', ['/', '/trabalhos/26/', '/conteudos-da-prova/1/']],
  ['demo.prof2', 'desktop', ['/', '/atividades/', '/conteudos-da-prova/1/', '/trabalhos/26/']],
  ['demo.direcao', 'desktop', ['/paineis/', '/estudantes/', '/calendario/']],
]
const out = []
for (const [user, form, pages] of PLANO) {
  const browser = await puppeteer.launch({ executablePath: process.env.CHROME_PATH, headless: true })
  const page = await browser.newPage()
  await page.goto(B + '/login/')
  await page.type('#id_username', user)
  await page.type('input[name=password]', SENHA)
  await Promise.all([page.waitForNavigation(), page.click('form button[type=submit]')])
  const config = form === 'desktop' ? desktopConfig : undefined
  const flow = await startFlow(page, {
    config, flags: { onlyCategories: ['performance', 'accessibility', 'best-practices', 'seo'] },
  })
  for (const p of pages) await flow.navigate(B + p, { name: `${user} ${p}` })
  const res = await flow.createFlowResult()
  for (const step of res.steps) {
    const r = step.lhr
    const s = k => (r.categories[k] && r.categories[k].score != null ? Math.round(r.categories[k].score * 100) : '—')
    const v = id => (r.audits[id] && r.audits[id].displayValue) || '—'
    out.push({
      pagina: step.name, form, perf: s('performance'), a11y: s('accessibility'), bp: s('best-practices'), seo: s('seo'),
      FCP: v('first-contentful-paint'), LCP: v('largest-contentful-paint'), CLS: v('cumulative-layout-shift'),
      erro: r.runtimeError ? r.runtimeError.code : '',
    })
    const nome = step.name.replace(/[^\w.]+/g, '_')
    fs.writeFileSync(path.join(SAIDA, `lighthouse_${nome}.json`), JSON.stringify(r))
  }
  await browser.close()
}
console.table(out)
