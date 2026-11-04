# Publicar a plataforma na internet sem custo (PythonAnywhere)

Resultado: a plataforma fica num endereço como **https://suaescola.eu.pythonanywhere.com**, com HTTPS,
acessível de qualquer celular ou computador, sem o computador da escola ligado.

## Por que o PythonAnywhere

Foi escolhido entre as opções gratuitas conferidas em 04/11/2026:

| Opção | Custo e cartão | Guarda os dados? | Situação |
|---|---|---|---|
| **PythonAnywhere, conta Beginner** | grátis, sem cartão | sim: disco permanente de 512 MB | **escolhida** |
| Render, Koyeb e similares | grátis, alguns pedem cartão | **não**: o disco apaga a cada reinício, e o banco SQLite junto | descartada |
| Oracle Cloud "Always Free", Google Cloud, AWS | pedem cartão | sim | descartada (regra: nada que peça cartão) |
| Tailscale Funnel (alternativa B, abaixo) | grátis, sem cartão | sim: no computador da escola | só com o computador ligado |

**Limites da conta gratuita** (anote, são reais):

- **Renovação todo mês:** o site é desligado se ninguém clicar no botão de renovar ("Run until ... from
  today") na aba **Web**. O PythonAnywhere manda e-mail antes. Ponha um lembrete no calendário.
- **512 MB de disco**, somando o código, o ambiente Python, o banco, as fotos e os backups. Uma escola
  pequena ou média cabe com folga se as fotos forem leves.
- **Um processo atendendo:** aguenta o uso de uma escola (secretaria, professores e famílias em horários
  diferentes), mas não centenas de pessoas no mesmo segundo.
- **Sem tarefas agendadas:** a rotina diária (lembretes, alertas do EIA, resumo semanal) roda na primeira
  visita do dia, que demora uns segundos a mais. Backup e limpeza da LGPD viram rotina mensal (passo 8).
- **Internet de saída restrita:** o aviso por e-mail provavelmente não funciona. Deixe desligado: as
  notificações continuam dentro da plataforma.
- O endereço é do PythonAnywhere (`.pythonanywhere.com`). Domínio próprio (`.com`, `.com.br`) não existe de graça:
  o registro é pago todo ano, e o PythonAnywhere só aceita domínio próprio no plano pago. Consulta de
  04/11/2026: `gestaoescolar.com` tem dono desde 2005; `gestaoescolar.com.br` (o Registro.br trata
  `gestãoescolar.com.br` como o mesmo nome) tem dono desde 2018.

## Antes de começar: LGPD (leia com a direção)

- **Transferência internacional:** na conta da região Europa, os dados dos estudantes ficam em servidores
  na União Europeia. A LGPD permite (art. 33), mas a escola precisa registrar a base legal e avisar as
  famílias. As páginas *Privacidade* e *Dados guardados* já dizem onde a plataforma está hospedada.
- **A hospedagem é operadora** (art. 5º, VII, e art. 39): guarda os dados em nome da escola. A escola
  continua controladora e responsável.
- **Escola pública:** confirme com a Secretaria de Educação se é permitido guardar dados de estudantes
  fora do Brasil. Se não for, use a **alternativa B**, em que nada sai da escola.
- **Encarregado de dados:** publique o nome e o contato em *Privacidade → Editar* logo no primeiro acesso.

## Passo 1: gerar o pacote (no computador da escola)

Na pasta `plataforma-escolar`, rode:

    .venv\Scripts\python.exe tools\empacotar_hospedagem.py

Sai o arquivo `Escola\hospedagem\plataforma-escolar.zip`, com cerca de 2 MB. Ele leva **só o código**.
O banco, as fotos, os backups, a chave secreta e o `.env` ficam de fora: o programa recusa o pacote se
algum deles entrar.

## Passo 2: criar a conta (5 minutos)

1. Abra **https://eu.pythonanywhere.com** (região Europa, dados na União Europeia). Para servidores nos
   EUA, use www.pythonanywhere.com.
2. Clique em **Pricing & signup** e depois em **Create a Beginner account**. É o plano gratuito; não pede
   cartão.
3. Escolha o **nome de usuário com cuidado**: ele vira o endereço. Por exemplo, `gestaoescolar` vira
   `gestaoescolar.eu.pythonanywhere.com`. Se o nome já estiver em uso, tente uma variação (`gestaoescolarbr`,
   o nome da escola).
4. Use um e-mail institucional da escola, não o pessoal, e confirme o e-mail.

## Passo 3: enviar e descompactar o código

1. Aba **Files** → **Upload a file** → escolha o `plataforma-escolar.zip`.
2. Aba **Consoles** → **Bash**. Na tela preta, digite:

       unzip -q plataforma-escolar.zip && rm plataforma-escolar.zip

## Passo 4: instalar (um comando, cerca de 2 minutos)

No mesmo console:

    bash ~/plataforma-escolar/deploy/pythonanywhere/instalar.sh

O script:

- cria o ambiente Python e instala Django, argon2 e Pillow;
- cria o `.env` com DEBUG desligado, HTTPS e o seu endereço;
- cria o banco novo, já com a BNCC;
- confere a configuração de segurança. O aviso `W008` é esperado: quem força o HTTPS é o PythonAnywhere
  (passo 5).

Depois, crie a escola e a conta de administração (troque os textos entre aspas):

    cd ~/plataforma-escolar
    ~/.virtualenvs/escola/bin/python manage.py initadmin --school-code SIGLA --school-name "Nome da Escola"

O comando pergunta o usuário e a senha (a senha não aparece enquanto é digitada). Use uma senha forte e única: o site fica aberto na internet.

## Passo 5: ligar o site (aba Web)

1. **Add a new web app** → **Next** → **Manual configuration** (não escolha "Django") → **Python 3.12**
   → **Next**.
2. Em **Virtualenv**, informe: `/home/SEUUSUARIO/.virtualenvs/escola`
3. Clique no link do **WSGI configuration file**, apague tudo e cole o conteúdo de
   `deploy/pythonanywhere/wsgi_pythonanywhere.py`, trocando `USUARIO` pelo seu usuário. Clique em **Save**.
4. Em **Static files**, adicione **URL** `/static/` e **Directory**
   `/home/SEUUSUARIO/plataforma-escolar/static`. Opcional, mas deixa o site mais rápido.
5. Em **Security**, ligue **Force HTTPS**.
6. Clique no botão verde **Reload** e abra o endereço que aparece no alto da página.

Fotos e documentos **não** entram em "Static files": a plataforma só os entrega a quem tem permissão.

## Passo 6: primeiro acesso

1. Entre com a conta criada no passo 4.
2. Publique o encarregado de dados em *Privacidade*.
3. Cadastre a escola, o ano letivo, as turmas e as contas da equipe, como no computador da escola.

**Nunca rode `seeddemo` na hospedagem:** ele cria contas de demonstração com senhas conhecidas, e o site
fica aberto na internet.

## Passo 7 (opcional): levar os dados que já estão no computador da escola

Só se a direção decidir; são dados reais de estudantes.

1. No computador da escola, feche a plataforma e rode `.venv\Scripts\python.exe manage.py backupdb`. O
   arquivo sai em `backups\`.
2. No PythonAnywhere, aba **Files**, envie esse arquivo para `plataforma-escolar/`. Depois, no console:

       cd ~/plataforma-escolar
       ~/.virtualenvs/escola/bin/python manage.py backupdb --restaurar NOME-DO-ARQUIVO.sqlite3
       ~/.virtualenvs/escola/bin/python manage.py migrate --noinput

3. **Carteirinhas já impressas:** o QR Code delas é assinado com a chave secreta do computador da escola.
   Envie também o arquivo `.secret_key` da pasta `plataforma-escolar` do computador da escola, substituindo
   o que o passo 4 criou. Sem ele, o QR das carteirinhas antigas é recusado; o código de barras e o código
   digitado continuam valendo. A chave é sigilosa: não a mande por e-mail nem por mensagem.
4. **Fotos:** compacte a pasta `media` do computador da escola, envie o zip e descompacte dentro de
   `plataforma-escolar/`. Confira o espaço (passo 8).
5. Clique em **Reload** na aba Web. Confira os dados e apague o arquivo `.sqlite3` enviado e o
   `db.sqlite3.antes-da-restauracao`: são cópias de dados pessoais.

## Passo 8: rotina mensal (10 minutos, no dia de renovar)

1. Aba **Web** → botão **Run until ... from today**.
2. Console Bash:

       bash ~/plataforma-escolar/deploy/pythonanywhere/manutencao.sh

   O script faz o backup, limpa pré-cadastros antigos (LGPD), relata dados operacionais antigos e mostra
   o espaço usado.
3. Aba **Files** → `plataforma-escolar/backups` → baixe o backup mais novo e guarde fora da hospedagem
   (pendrive ou drive da escola). Se a conta for perdida, é ele que recupera a escola.

## Atualizar para uma versão nova

1. Gere o pacote de novo (passo 1) e envie o zip para a pasta inicial pela aba **Files**.
2. No console:

       bash ~/plataforma-escolar/deploy/pythonanywhere/atualizar.sh

O script faz backup, troca só o código, aplica as migrações e recarrega o site. O banco, o `.env`, a
chave e as fotos ficam.

## Se algo der errado

- **"Something went wrong" ou erro 500:** aba **Web** → **Error log**. As últimas linhas dizem o motivo.
- **"Bad Request (400)":** o endereço não está em `DJANGO_ALLOWED_HOSTS` no arquivo
  `plataforma-escolar/.env`. Corrija e clique em **Reload**.
- **O login volta para a tela de entrada:** o endereço foi aberto com `http://`. Ligue o **Force HTTPS**
  (passo 5).
- **Disco cheio:** apague backups antigos em `plataforma-escolar/backups`, depois de baixá-los.

## Alternativa B: o computador da escola na internet (Tailscale Funnel)

Os dados não saem da escola. Em troca, o computador precisa ficar ligado e conectado para o site
funcionar.

1. Crie a conta gratuita em https://tailscale.com (entra com Google ou Microsoft, sem cartão). Instale o
   Tailscale no computador da plataforma.
2. No painel do Tailscale, ative **HTTPS** e **Funnel** (Access controls). O computador ganha um nome como
   `escola.tail1234.ts.net`.
3. No `.env` da plataforma, ponha:

       DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,escola.tail1234.ts.net
       DJANGO_SSL=1
       DJANGO_SSL_REDIRECT=0
       DJANGO_PROXY_SSL=1

4. Abra a plataforma com `iniciar.bat` e, num segundo terminal, rode `tailscale funnel 8000`.
5. Todos acessam por **https://escola.tail1234.ts.net**, inclusive dentro da escola. Com `DJANGO_SSL=1`, o
   endereço `http://IP:8000` da rede local deixa de aceitar login.

O Funnel está em fase beta e tem limite de banda não divulgado. Esta alternativa **não foi testada** aqui:
os scripts e a configuração do PythonAnywhere foram ensaiados numa simulação; o Funnel não.
