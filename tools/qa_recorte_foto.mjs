// Teste do recorte de foto no navegador (Prompt 14 §3.1): arrasto, zoom e envio.
//
// Não faz parte do pytest porque exigiria o Playwright como dependência do
// projeto. Roda com qualquer executor Playwright (ex.: o browser.mjs da skill
// browser-automation) numa página que tenha <input type=file data-photo-crop>,
// por exemplo "Minha foto" num servidor local com uma CÓPIA do banco:
//
//   QA_IMG=C:/caminho/teste-recorte.png
//   node browser.mjs http://127.0.0.1:8765/minha-foto/ --script tools/qa_recorte_foto.mjs
//
// QA_IMG deve ser uma imagem 640×320: metade esquerda vermelha, metade direita
// azul e uma faixa verde nas linhas 150 a 170 (o roteiro confere cores de
// pixel do canvas). Em 390 e 1280 px de largura, confere:
//   - início: recorte centralizado (x=250 azul, linha 160 verde);
//   - arrasto de 100 px internos para a direita: x=250 passa a vermelho. Antes
//     da correção de 02/11/2026 a foto andava metade, porque o canvas aparece
//     com 160 px e o deslocamento não era convertido;
//   - zoom 2×: a faixa verde sai da linha 160;
//   - envio: o arquivo vira foto.jpg, JPEG 512×512 (a navegação é cancelada).
// Qualquer item em "falhas" reprova.

const IMG = process.env.QA_IMG

export default async function run(page) {
  if (!IMG) return { falhas: ['defina QA_IMG'] }
  const out = { falhas: [] }
  const color = ([r, g, b]) => r > 200 && b < 60 ? 'vermelho' : b > 200 && r < 60 ? 'azul' : g > 150 && r < 60 ? 'verde' : `${r},${g},${b}`
  const px = (x, y) => page.evaluate(([x, y]) =>
    Array.from(document.querySelector('.photo-crop canvas').getContext('2d').getImageData(x, y, 1, 1).data.slice(0, 3)), [x, y])
  const expect = (w, what, got, want) => { if (got !== want) out.falhas.push(`${w}px ${what}: ${got} (esperado ${want})`) }
  for (const w of [390, 1280]) {
    await page.setViewportSize({ width: w, height: 900 })
    await page.reload(); await page.waitForLoadState('load')
    const input = page.locator('input[type=file][data-photo-crop]').first()
    await input.setInputFiles(IMG)
    await page.waitForFunction(() => document.querySelector('.photo-crop.is-active'))
    expect(w, 'início x=250', color(await px(250, 100)), 'azul')
    expect(w, 'início linha 160', color(await px(10, 160)), 'verde')
    const box = await page.locator('.photo-crop canvas').boundingBox()
    const k = box.width / 320
    await page.mouse.move(box.x + 100 * k, box.y + 100 * k); await page.mouse.down()
    await page.mouse.move(box.x + 200 * k, box.y + 100 * k, { steps: 8 }); await page.mouse.up()
    expect(w, 'arrasto x=250', color(await px(250, 100)), 'vermelho')
    await page.locator('.photo-crop input[type=range]').fill('2')
    expect(w, 'zoom linha 160', color(await px(10, 160)), 'vermelho')
    await page.evaluate(() => document.addEventListener('submit', e => e.preventDefault()))
    await input.evaluate(i => i.form.querySelector('[type=submit]').click())
    await page.waitForFunction(() => document.querySelector('input[data-photo-crop]').files[0].name === 'foto.jpg', null, { timeout: 5000 })
    const sent = await page.evaluate(async () => {
      const f = document.querySelector('input[data-photo-crop]').files[0]
      const b = await createImageBitmap(f)
      return `${f.type} ${b.width}x${b.height}`
    })
    expect(w, 'envio', sent, 'image/jpeg 512x512')
    out[w] = { canvasExibido: Math.round(box.width), envio: sent }
  }
  return out
}
