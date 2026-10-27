# Plataforma Escolar Integrada

Plataforma escolar multiusuário (famílias, professores, coordenação, direção, secretaria e administradores) construída para funcionar com **custo financeiro de R$ 0,00** — sem assinaturas, sem cotas, sem cartão de crédito. O software roda em um computador da escola, sob controle institucional.

> **Fase atual:** 8 — Publicação e documentação concluída (launcher `iniciar.bat`, guia de publicação, manual de utilização e revalidação das condições de custo zero). As Fases 2 (fundação), 3 (cadastro escolar), 4 (pedagógico), 5 (comunicação), 6 (painéis e relatórios) e 7 (segurança e qualidade) permanecem em vigor.

---

## 1. Requisitos

| Item | Necessário |
|---|---|
| Python 3.12+ | Sim (você já tem no seu computador) |
| Conexão com a internet | Apenas na **instalação** (baixar dependências). Depois disso, roda offline. |
| Sistema | Windows, Linux ou macOS |
| Hardware | 2 GB de RAM e 500 MB de disco (para a escola, um computador comum) |

**Custo:** R$ 0,00. Nenhum serviço externo é usado em tempo de execução.

---

## 2. Instalação

Abra o terminal na pasta do projeto (`plataforma-escolar`) e execute:

```bash
# 1. Ambiente virtual (isolamento das dependências)
python -m venv .venv

# 2. Ativar (Windows)
.venv\Scripts\activate
# Ativar (Linux/macOS):
# source .venv/bin/activate

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Criar o banco de dados e aplicar as migrações
python manage.py migrate

# 5. Criar a escola e a conta administrativa inicial
python manage.py initadmin --school-name "Nome da Escola" --school-code "minha-escola"

# 6. Iniciar o servidor
python manage.py runserver
```

O passo 5 vai pedir **usuário** e **senha** do administrador. Anote a senha em local seguro.

Agora abra no navegador: **http://127.0.0.1:8000/**

---

## 3. Configuração

Copie `.env.example` para `.env` e ajuste. Opcional — se não existir `.env`, a aplicação usa valores seguros padrão.

| Variável | Descrição | Padrão |
|---|---|---|
| `DJANGO_DEBUG` | `1` ativa a depuração (somente desenvolvimento) | `0` |
| `DJANGO_ALLOWED_HOSTS` | Hosts permitidos, separados por vírgula | `127.0.0.1,localhost` |
| `DJANGO_SECRET_KEY` | Chave secreta. Se ausente, é gerada em `.secret_key` automaticamente | gerada |
| `DJANGO_TZ` | Fuso horário | `America/Sao_Paulo` |
| `DJANGO_SSL` | `1` **somente se a plataforma for servida por HTTPS**. Liga de uma vez o redirecionamento para HTTPS, o HSTS e os cookies de sessão/CSRF restritos a conexão segura | `0` |

> **Atenção com `DJANGO_SSL`:** ativá-lo sem HTTPS faz o navegador deixar de
> enviar os cookies de sessão e de CSRF, e o login para de funcionar. Mantenha
> `0` em rede local por HTTP. Com `1` e HTTPS, `python manage.py check --deploy`
> não reporta nenhuma advertência.

> O arquivo `.secret_key` e o `.env` **nunca** devem ser compartilhados nem versionados.
>
> **Dependências:** o projeto continua com **as mesmas 4 dependências** (`Django`, `argon2-cffi`, `Pillow`, `pytest-django`). Os painéis e relatórios usam **gráficos SVG gerados no servidor** e exportação **CSV/impressão nativa do navegador** — nenhuma biblioteca de gráficos ou de PDF foi adicionada.

---

## 4. Executar os testes

```bash
python -m pytest
```

**175 testes.** Se vier de uma versão anterior, aplique as migrações antes de
subir o servidor — a atividade de casa acrescentou campos e a tabela de anexos:

```bash
python manage.py migrate
```

Faça o backup do `db.sqlite3` antes (seção 5). A migração é aditiva: as
atividades que já existirem ficam como **publicadas**, mantendo o
comportamento anterior.

Cobertura — autenticação, autorização, auditoria e RBAC (perfil,
elevação de privilégio, isolamento entre escolas), cadastro escolar (vínculos
responsável-filho, matrículas, turmas, disciplinas e atribuições), o pedagógico
(avaliações/notas, atividades/entregas, frequência, ocorrências, observações,
planos, justificativas de falta e regras configuráveis), a comunicação
(mensagens, comunicados, notificações internas e solicitações) e os painéis e
relatórios (métricas determinísticas, RBAC dos painéis, escopo dos relatórios,
exportação CSV e gráficos SVG).

Atividades de casa — publicação e rascunho, alcance por turma, aluno
matriculado depois da publicação, aluno transferido, turma sem estudantes,
par turma+disciplina cruzado, responsável sem vínculo, acesso a rascunho pelo
identificador, anexo executável recusado, anexo de rascunho bloqueado,
cancelamento preservando histórico e **orçamento de consultas** (a mesma tela
medida com 2 e com 27 estudantes/atividades, falhando se houver N+1).

---

## 5. Backup e recuperação

Tudo que precisa ser preservado cabe em **duas coisas**: o banco (`db.sqlite3`) e a pasta `media/`.

### Backup do banco — com a plataforma no ar

```bash
python manage.py backupdb
```

Grava em `backups/db-AAAAMMDD-HHMMSS.sqlite3`, **confere a integridade** do
arquivo gerado e conserva os 10 mais recentes (`--manter N` muda, `--destino`
escolhe outra pasta). Se o arquivo não passar na verificação, ele é descartado
e o comando falha — nunca deixa um backup inútil parecendo válido.

> **Por que não copiar o arquivo direto:** copiar `db.sqlite3` com o servidor
> rodando pode capturá-lo no meio de uma transação e produzir um backup
> corrompido, e a corrupção só aparece na hora de restaurar. O comando usa a
> API de backup do SQLite, que copia página por página respeitando o bloqueio,
> então não é preciso parar o servidor.

### Backup dos arquivos enviados

A pasta `media/` (fotos e anexos) é só cópia de arquivos:

```powershell
# Windows (PowerShell)
Copy-Item media -Recurse "backups\media-$(Get-Date -Format yyyyMMdd-HHmm)" -Force
```

### Restauração

```bash
# 1. Pare o servidor.
# 2. Restaure:
python manage.py backupdb --restaurar backups\db-20261026-214801.sqlite3
# 3. Restaure a pasta media/ do backup correspondente.
# 4. Inicie o servidor e confira o login.
```

A restauração **verifica o backup antes de tocar no banco atual** e guarda o
banco que havia em `db.sqlite3.antes-da-restauracao`. Se o arquivo estiver
corrompido, ela é interrompida e nada é alterado — restaurar de um arquivo ruim
sobre o único banco bom é a maneira mais fácil de transformar um incidente
recuperável em perda definitiva.

Recomendação: manter o backup em **mídia externa (HD/pendrive)** ou em outra máquina — também gratuito.

---

## 6. Operação e segurança

- **Nunca** exponha a porta do banco à internet. O banco é um arquivo local (SQLite).
- Rode em rede local (professores/secretaria acessam pelo IP do computador: `python manage.py runserver 0.0.0.0:8000` e `DJANGO_ALLOWED_HOSTS` com o IP).
- Sem HTTPS em rede local é aceitável; para acesso pela internet, configure TLS e um túnel seguro (avaliar segurança antes de adotar).
- Troque a senha do administrador após o primeiro acesso.
- **Senha esquecida:** não há recuperação por e-mail (seria custo de
  infraestrutura). A administração redefine qualquer conta da escola em
  **Usuários → abrir a conta → Redefinir senha**; a **secretaria** redefine
  apenas contas de **responsável**, em **Responsáveis → abrir o perfil →
  Redefinir senha**. A senha temporária aparece **uma única vez** na tela, deve
  ser entregue pessoalmente, e a plataforma **obriga a troca** no próximo acesso
  antes de liberar qualquer outra tela. A operação fica registrada na auditoria.
- Senhas são guardadas com hash (Argon2/PBKDF2), nunca em texto puro.
- Todas as operações relevantes são registradas em **auditoria** (`/admin/` → Registros de auditoria).

---

## 7. Publicação e disponibilização

Depois de instalado (seção 2) e configurado (seção 3), o sistema está pronto para
uso. Não há etapa de "build" nem coleta de arquivos estáticos: o Bootstrap, CSS e
JS são **locais** e servidos pelo próprio Django.

### 7.1 Iniciar (Windows)

Dê **duplo clique em `iniciar.bat`** na pasta do projeto. O arquivo:

1. aplica as migrações pendentes do banco;
2. sobe o servidor em `0.0.0.0:8000` (acessível na rede local);
3. mostra as instruções de acesso na tela.

Mantenha a janela aberta enquanto o sistema estiver em uso. Para encerrar, feche
a janela ou pressione `Ctrl+C`.

### 7.2 Acesso

| De onde | Endereço |
|---|---|
| Mesmo computador | `http://127.0.0.1:8000/` |
| Outro computador da rede local | `http://IP-DESTE-COMPUTADOR:8000/` (veja o IP com `ipconfig`) |

Para aceitar acesso pela rede, inclua o IP/IPs em `DJANGO_ALLOWED_HOSTS`
(no `.env`), por exemplo:

```env
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,192.168.0.10
```

### 7.3 Manual de utilização

O uso do dia a dia está em **`Manual de Utilização.md`** (na pasta `Escola`, ao
lado do projeto): visão geral, primeiro acesso, e o que cada perfil faz —
professor, secretaria, coordenação, direção, administração e responsável —, com
as rotinas de notas, frequência, comunicados, solicitações, painéis e relatórios.

### 7.4 Publicar para a internet (opcional)

A operação normal é **em rede local**, de custo zero. Expor à internet exige
infraestrutura própria da escola (HTTPS, proxy reverso e liberação segura) —
avalie a segurança antes. Nesse caso, ajuste `DJANGO_ALLOWED_HOSTS` e o
`.env` conforme a seção 3. **Nunca** exponha o banco (`db.sqlite3`) nem a porta
diretamente.

> Observação: o comando `manage.py runserver` é o servidor embutido do Django,
> indicado para uso interno/escolar de baixo volume. Para maior volume de
> acessos simultâneos, é possível usar um servidor WSGI gratuito — porém isso
> seria uma **dependência adicional** e foi deliberadamente evitado para manter
> o custo e a instalação em zero.

---

## 8. O que está implementado nesta fase

### Fundação (Fase 2)

- ✔ Autenticação: login, logout (POST), alteração de senha.
- ✔ Perfis (RBAC): Administrador, Direção, Coordenação, Secretaria, Professor, Responsável.
- ✔ Permissões verificadas no servidor (não apenas escondendo botões).
- ✔ Contas profissionais **somente** criadas por administrador (senha temporária).
- ✔ Isolamento por escola (uma escola não enxerga usuários de outra).
- ✔ Auditoria de login, logout, falha de login e criação de contas.
- ✔ Interface base responsiva, tema claro/escuro, mensagens de feedback.
- ✔ Gestão de usuários: listagem, busca, detalhes com auditoria.
- ✔ Banco de dados persistente com migrações versionadas.

### Cadastro escolar (Fase 3)

- ✔ Estudantes: cadastro, edição, listagem/busca e prontuário individual com auditoria.
- ✔ Fotos (estudante e responsável) validando tipo/tamanho (JPG, PNG, WEBP ≤ 2 MB), nomes aleatórios e **servidas apenas por rotas autenticadas** (nunca pela URL pública de mídia).
- ✔ Responsáveis: perfil com contatos/endereço e preferência de comunicação.
- ✔ Vínculos responsável↔estudante: responsável solicita pelo nome (sem expor dados da matrícula), secretaria/admin aprova ou rejeita; vínculos criados pela secretaria já nascem validados.
- ✔ Matrículas por ano letivo com unicidade (ativa/concluída) por estudante/ano.
- ✔ Turmas, disciplinas e anos letivos com validação de duplicidade por escola.
- ✔ Atribuições professor→turma/disciplina/ano com unicidade e isolamento por escola.
- ✔ Cadastro público de responsável (`/cadastro/`) — perfil sempre fixado em *responsável* no servidor, sem elevação possível por meio de dados enviados.
- ✔ Área do professor: "Minhas turmas" lista apenas as turmas atribuídas; professor só visualiza estudantes das próprias turmas.
- ✔ Área do responsável: "Meus filhos" com acesso só após vínculo aprovado.

### Pedagógico (Fase 4)

- ✔ **Avaliações e notas**: professor cria avaliações apenas nas turmas/disciplinas que leciona, lança notas em lote e publica (só a publicação torna as notas visíveis à família); edição/exclusão bloqueada após publicar.
- ✔ **Atividades de casa e entregas**: publicação por turma/disciplina com rascunho, anexos de apoio, cancelamento com motivo e área própria da família (detalhes na seção 9).
- ✔ **Frequência**: visualização por turma e registro em lote (presente/atraso/falta), com mapa de presença por turma.
- ✔ **Ocorrências**: registro objetivo com providências/encaminhamento, histórico de alterações em auditoria e fila de acompanhamento.
- ✔ **Observações pedagógicas**: dificuldades, habilidades e estratégias por estudante — **invisíveis a administração e secretaria**.
- ✔ **Planos de acompanhamento**: criados pela **coordenação**, com registros de evolução; visíveis à família e ao professor.
- ✔ **Justificativas de falta**: enviadas pelo responsável, analisadas pela **secretaria** (com parecer); a frequência oficial não muda automaticamente.
- ✔ **Regras e limites configuráveis**: limite de faltas e média de aprovação/fórmula por disciplina (a fórmula nunca é presumida pelo sistema).
- ✔ RBAC no servidor em todos os fluxos; responsável enxerga apenas dados dos filhos com vínculo aprovado e apenas notas **publicadas**.
- ✔ Auditoria das operações relevantes (criar/editar/excluir/publicar/decidir).

### Comunicação (Fase 5)

- ✔ **Mensagens**: conversas responsável↔profissional (par válido da mesma escola), com histórico, resposta e confirmação de leitura; professor só conversa com responsáveis de estudantes das próprias turmas.
- ✔ **Comunicados**: institucionais (direção/coordenação/admin), por turma e individuais (também secretaria/professor, restrito às próprias turmas/estudantes), com público família/equipe/todos e **confirmação de leitura** visível à equipe.
- ✔ **Central de notificações**: avisos internos persistentes (novas notas, prazos, comunicados, mensagens, solicitações, limite de faltas), com badge de não lidas no topo — **100% dentro da plataforma, sem serviços pagos**.- ✔ **Solicitações de atendimento**: a família abre pedidos (matrícula, documentos, declarações, etc.); a secretaria/coordenação/direção atende com **status** (recebida → em análise → aprovada/recusada/respondida/concluída), resposta e **histórico de atendimento** em auditoria.
- ✔ Notificações automáticas disparadas por eventos: publicação de avaliação, criação de atividade, parecer de justificativa, registro de frequência que atinge o limite de faltas, novas mensagens/comunicados e solicitações criadas/respondidas.
- ✔ RBAC no servidor em todos os fluxos; aba **Comunicação** no prontuário do estudante consolidando mensagens, comunicados e solicitações relacionadas.

### Painéis e Relatórios (Fase 6)
- ✔ **Painel individual do estudante** (`/paineis/estudante/<id>/`): média por disciplina (conforme a fórmula configurada, só notas **publicadas**), evolução das notas, distribuição por faixa, frequência com **marcação do limite de faltas**, entregas/pendências/atrasos, justificativas, ocorrências, planos de acompanhamento, dificuldades/habilidades/reforço e **linha do tempo** — com drill-down "ver os dados que fundamentam" cada gráfico.
- ✔ **Painel por turma** (`/paineis/turma/<id>/`): média da turma por disciplina, frequência da turma e lista de **estudantes que merecem atenção** (sinal objetivo, não diagnóstico).
- ✔ **Painel institucional** (`/paineis/`, coordenação/direção/admin): indicadores consolidados (estudantes, frequência global, ocorrências, planos) e frequência por turma.
- ✔ **Painel da secretaria** (`/paineis/secretaria/`): vínculos pendentes, estudantes sem matrícula ativa, justificativas em análise e solicitações abertas.
- ✔ **Hub de relatórios** (`/relatorios/`) com 12 relatórios por categoria e perfil: boletim, evolução acadêmica, frequência por período, dificuldades, atividades pendentes, histórico de acompanhamento, justificativas, ocorrências, pendências documentais, solicitações, indicadores por turma e institucional.
- ✔ **Filtros** (estudante/turma/disciplina/período) e, em todo relatório, **data de geração, período analisado e critérios** (origem e regra de cálculo declarados).
- ✔ **Exportação CSV** (UTF-8 com BOM, separador `;` — abre direto no Excel) e **impressão/"Salvar como PDF"** pelo próprio navegador; a mesma função gera tela, CSV e impressão, então a **permissão vale igualmente no conteúdo exportado**.
- ✔ **Gráficos SVG gerados no servidor** (linha, barras, distribuição e indicador de frequência) — acessíveis, com rótulos escapados e valor em cada ponto; **nenhuma biblioteca de gráficos adicionada**.
- ✔ Escopo por perfil: professor vê apenas suas turmas/estudantes; responsável apenas os filhos com vínculo aprovado; observações pedagógicas permanecem **invisíveis à administração e à secretaria** também nos painéis.

### Segurança e qualidade (Fase 7)

- ✔ Auditoria de autorização em todas as views que recebem identificador (`student_id`, `class_group_id`, `link_id`, ids de avaliação/atividade/ocorrência/plano/justificativa/solicitação etc.), confirmando que cada rota filtra por `request.user.school` e valida o **papel no objeto** (não apenas o login).
- ✔ **Frequência por turma** (`/frequencia/turma/<id>/`): professor passa a ver **apenas turmas que leciona** (antes lia qualquer turma da mesma escola); direção/coordenação/secretaria/admin continuam com acesso amplo; responsável continua restrito aos filhos.
- ✔ **Foto de responsável**: `can_manage_registry` agora só acessa responsáveis **da própria escola** (antes um gestor podia ler o arquivo de outra escola pelo id).
- ✔ **Solicitações de atendimento**: professor passa a listar apenas pedidos ligados aos **próprios estudantes** (ou feitos por ele) — antes via todas as solicitações da escola.
- ✔ **Aprovar/rejeitar vínculo** (`/vinculos/<id>/aprovar|rejeitar/`): passaram a exigir **POST** (`405` em GET), evitando alteração de estado por navegação/prefetch ou link.
- ✔ Relatórios: os filtros de estudante/turma são resolvidos com escopo de escola, evitando "oráculo" de existência de ids de outras escolas (404).
- ✔ Novos **6 testes** de autorização/integração/persistência cobrindo exatamente essas correções.

### Publicação e documentação (Fase 8)

- ✔ **Launcher `iniciar.bat`** (Windows): aplica migrações e sobe o servidor com um duplo clique, mostrando as instruções de acesso.
- ✔ **Guia de publicação** (seção 7): como disponibilizar em rede local, como configurar `DJANGO_ALLOWED_HOSTS` e como publicar externamente (opcional).
- ✔ **Manual de utilização** por perfil (`Manual de Utilização.md`).
- ✔ **Instruções de instalação** (seção 2), **backup e recuperação** (seção 5) e **operação/segurança** (seção 6) mantidas e conferidas.
- ✔ **Custo zero revalidado**: nenhuma biblioteca nova (as mesmas 4 dependências), **nenhuma chamada a serviço externo** em runtime (Bootstrap, CSS e JS locais; gráficos SVG no servidor; PDF pela impressão do navegador).

## 9. Atividades de casa por turma

A atividade pertence à **turma**, não a cada estudante: existe um único
registro e o alcance é derivado das matrículas. Isso faz com que quem entra na
turma depois passe a ver as atividades vigentes e com que editar a atividade
atualize todos de uma vez, sem cópias divergentes.

**Professor** (`/atividades/`, menu Pedagógico → Atividades de casa)

1. Escolhe turma e disciplina — apenas combinações da **sua atribuição**: um
   professor de Matemática na turma A e de Português na turma B não publica
   Português para a turma A.
2. Preenche título e instruções (ambos obrigatórios — é o texto que a família
   lê), e, se fizer sentido, materiais necessários, critérios, data da aula de
   referência, data de publicação e data de entrega.
3. Anexa arquivos de apoio (PDF, imagem, documento, planilha, apresentação —
   até 10 MB cada; executáveis e compactados são recusados).
4. **Salva como rascunho** ou **publica para a turma**. Rascunho é visível só
   para o professor.
5. Acompanha as entregas por estudante, filtra por turma, disciplina, situação
   e período, e vê a prévia exata do que a família recebe.

**Família** (`/atividades/`, menu Atividades de casa)

Um cartão por atividade **e por filho**, de modo que quem tem mais de um
estudante sabe de quem é a tarefa. A situação vem do prazo: *a vencer*,
*pendente*, *prazo encerrado*, *cancelada*. A atividade também aparece na aba
Pedagógico da ficha de cada estudante.

**O que a família nunca vê**: rascunho, atividade com data de publicação
futura, e qualquer atividade de turma em que não tenha filho matriculado —
inclusive tentando o identificador direto na URL. Os anexos não têm URL
pública: o download passa por uma view que confere o vínculo de quem pede.

**Cancelar em vez de excluir**: cancelar exige motivo e preserva a atividade,
os anexos e as entregas já lançadas. O histórico escolar não é apagado, e a
família vê a atividade marcada como cancelada com o motivo.

**Conclusão não é visualização**: a família só vê "entrega registrada" quando o
**professor** registrou a entrega. Abrir a atividade não conclui nada.

**Aluno transferido**: a visibilidade considera qualquer matrícula do estudante,
não apenas a ativa, para que a mudança de turma não apague o histórico de
atividades já atribuídas.

## 10. Escola de demonstração

Para conhecer a plataforma, treinar a equipe ou avaliar o comportamento com
volume antes de cadastrar dados reais:

```bash
python manage.py seeddemo          # cria
python manage.py seeddemo --limpar # remove tudo
```

Cria uma **escola separada** (código `demo`) com 72 estudantes sintéticos, 4
turmas, 7 disciplinas, 36 atividades em situações variadas (rascunho,
publicada, cancelada, prazo vencido), entregas, notas, 30 dias de frequência e
70 contas — direção, coordenação, secretaria, 4 professores e responsáveis
(um deles com dois filhos, para exercitar a troca entre eles). Todas as contas
usam a mesma senha, impressa no fim do comando.

> **Separação dos dados:** a demonstração é uma escola distinta, e a plataforma
> isola tudo por escola. Nenhuma conta da demonstração alcança dados da escola
> real, e os estudantes fictícios não aparecem nas listagens dela. Os nomes são
> inventados — nunca use dados de estudantes reais para demonstrar ou testar.

## 11. Acesso do próprio estudante

Opcional, e desligado por padrão: um estudante só tem login se a escola criar.

**Como criar:** a **secretaria** (ou a administração) abre a ficha do estudante
e usa **Acesso do estudante → Criar acesso**. O login e a senha temporária
aparecem **uma única vez**; a troca é exigida no primeiro acesso. O mesmo botão
depois serve para redefinir a senha.

A conta nasce obrigatoriamente a partir da ficha — não pelo cadastro público nem
pela tela de contas profissionais. Assim não existe conta de estudante sem
vínculo com uma matrícula real.

**O que o estudante vê:** as atividades de casa publicadas para a turma dele
(com prazo e situação), as **avaliações já publicadas**, a **própria**
frequência e um painel com médias por disciplina e evolução das notas.

**O que o estudante não vê**, mesmo na própria ficha e no próprio painel:

- ocorrências e o registro disciplinar;
- observações pedagógicas feitas sobre ele (dificuldades, habilidades, reforço);
- planos de acompanhamento;
- a linha do tempo de eventos;
- anotações da secretaria;
- relatórios e painéis institucionais;
- **qualquer dado de colega** — na frequência da turma ele vê apenas a própria
  linha, e a lista de atividades não mostra nome de outro estudante.

Isso segue a seção 7.5 do prompt de design e o melhor interesse do menor: o
estudante acompanha o próprio aprendizado, não o próprio dossiê.

### Limitações conhecidas

- Acesso externo pela internet depende de infraestrutura própria da escola (limitação documentada na Fase 1).
- Os relatórios exportam em **CSV** (abre no Excel/LibreOffice) e **PDF via impressão do navegador**; a geração de PDF no servidor foi deliberadamente evitada para manter o custo e as dependências em zero.
- Os indicadores de desempenho são **sinais objetivos para a equipe** (médias, faltas, ocorrências) e não substituem a avaliação pedagógica.
