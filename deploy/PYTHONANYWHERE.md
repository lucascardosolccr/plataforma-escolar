# Hospedagem gratuita no PythonAnywhere

Guia passo-a-passo para publicar a Plataforma Escolar **de graça** no
[PythonAnywhere](https://www.pythonanywhere.com) (plano **Beginner**, grátis,
sem cartão de crédito).

**Por que PythonAnywhere:** é o único host realmente gratuito em que o
**SQLite sobrevive** — tem disco persistente. Nos gratuitos "modernos"
(Render, Railway, Fly) o disco é efêmero e o `db.sqlite3` é apagado a cada
reinício. Além disso, ele roda Django nativamente e serve os arquivos
estáticos pelo próprio painel, sem precisar de nenhuma dependência nova
(custo zero mantido).

**Limites do plano grátis (aceitáveis para esta escola):**
- Endereço fixo: `SEU_USUARIO.pythonanywhere.com` (sem domínio próprio).
- 1 app web; precisa clicar em **Reload** após mudar o código.
- Internet de saída restrita a uma lista branca — **não afeta** esta
  plataforma, que não chama serviços externos.

> ⚠️ **LGPD:** suba o site com **banco novo e vazio**. Não envie o
> `db.sqlite3` real (tem dados de menores). Você cadastra os dados reais
> depois, direto no site no ar — ou, melhor, mantém os dados reais só na
> instância da escola. O `.gitignore` já impede o banco de ir ao repositório.

---

## Passo 0 — Levar o código para o PythonAnywhere

Escolha **um** caminho.

### Caminho A (recomendado): GitHub + git clone
Permite atualizar depois com um simples `git pull`.

1. Crie um repositório **privado** no GitHub (ex.: `plataforma-escolar`).
2. Na sua máquina, dentro do projeto:
   ```bash
   git remote add origin https://github.com/SEU_LOGIN/plataforma-escolar.git
   git push -u origin main
   ```
   O `.gitignore` garante que banco, `.env`, `media/` e `backups/` **não** sobem.
3. No PythonAnywhere, na aba **Consoles → Bash**:
   ```bash
   git clone https://github.com/SEU_LOGIN/plataforma-escolar.git ~/plataforma-escolar
   ```
   (repositório privado pede login; use um
   [token de acesso pessoal](https://github.com/settings/tokens) como senha.)

### Caminho B: upload do bundle .zip
Se preferir não usar GitHub. O arquivo `plataforma-escolar-deploy.zip`
(que foi gerado para você, só com arquivos versionados — sem banco/segredos)
pode ser enviado em **Files → Upload a file**. Depois, no Bash console
(o zip já contém a pasta `plataforma-escolar/`, então descompacte em `~`):
```bash
cd ~
unzip ~/plataforma-escolar-deploy.zip   # cria ~/plataforma-escolar/
```

---

## Passo 1 — Virtualenv e dependências

Na aba **Consoles → Bash** do PythonAnywhere:

```bash
cd ~/plataforma-escolar
python3.11 -m venv .venv          # use a versão de Python 3.11+ que o PA oferecer
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Passo 2 — Criar o `.env` de produção

Ainda no Bash console, crie o arquivo `.env` na raiz do projeto. Use o modelo
em `deploy/env.pythonanywhere.example`. Gere a chave secreta assim:

```bash
python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```

E escreva o `.env` (troque `SEU_USUARIO` e cole a chave):

```bash
cat > ~/plataforma-escolar/.env <<'EOF'
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=SEU_USUARIO.pythonanywhere.com
DJANGO_SSL=1
DJANGO_SSL_REDIRECT=0
DJANGO_PROXY_SSL=1
DJANGO_SECRET_KEY=COLE_A_CHAVE_AQUI
EOF
```

---

## Passo 3 — Banco, estáticos e usuário administrador

```bash
cd ~/plataforma-escolar
source .venv/bin/activate
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser   # crie o administrador (login, nome, senha forte)
```

---

## Passo 4 — Criar o app web

1. Aba **Web → Add a new web app**.
2. Escolha **Manual configuration** (⚠️ NÃO escolha "Django"), mesma versão de
   Python do virtualenv (3.11+).
3. Em **Virtualenv**, informe: `/home/SEU_USUARIO/plataforma-escolar/.venv`
4. Em **Code → WSGI configuration file**, clique no link, **apague tudo** e cole
   o conteúdo de `deploy/wsgi_pythonanywhere.py` (trocando `SEU_USUARIO`).
5. Em **Static files**, adicione dois mapeamentos:

   | URL        | Directory                                              |
   |------------|--------------------------------------------------------|
   | `/static/` | `/home/SEU_USUARIO/plataforma-escolar/staticfiles`     |
   | `/media/`  | `/home/SEU_USUARIO/plataforma-escolar/media`           |

6. Clique no botão verde **Reload**.

Pronto: acesse **https://SEU_USUARIO.pythonanywhere.com**

---

## Atualizar o site depois (caminho A / GitHub)

```bash
cd ~/plataforma-escolar
source .venv/bin/activate
git pull
pip install -r requirements.txt          # só se requirements mudou
python manage.py migrate                  # só se houver migração nova
python manage.py collectstatic --noinput  # só se estáticos mudaram
```
Depois clique em **Reload** na aba Web.

---

## Verificação de segurança antes de publicar

Com o `.env` criado, rode:
```bash
python manage.py check --deploy
```
Deve sair sem avisos de segurança (DEBUG off, HSTS, cookies seguros e CSRF já
estão configurados no `config/settings.py` e ligam sozinhos com `DJANGO_SSL=1`).

## Problemas comuns
- **DisallowedHost / 400:** confira `DJANGO_ALLOWED_HOSTS` no `.env` (exatamente
  `SEU_USUARIO.pythonanywhere.com`) e dê **Reload**.
- **CSS/JS sem estilo:** faltou `collectstatic` ou o mapeamento de `/static/`
  na aba Web.
- **500 ao enviar formulário (CSRF):** confirme `DJANGO_SSL=1` e
  `DJANGO_PROXY_SSL=1` no `.env`.
- **Erro ao abrir o site:** veja a aba **Web → Error log**.
