# Roteiro da demonstração

Guia para um tour completo pela plataforma usando a escola de demonstração
criada pelo comando `seeddemo`. A escola "demo" é isolada da escola real: são
dados fictícios, numa escola à parte.

## 1. Preparação

1. Criar/recriar a escola de demonstração:
   ```
   python manage.py seeddemo            # cria (ou use --estudantes N)
   python manage.py seeddemo --limpar   # remove tudo depois
   ```
2. **No site hospedado (repositório público):** logo após o `seeddemo`,
   redefina as senhas das contas demo para a senha forte combinada. A senha
   padrão do seed está no código, que é público — nunca a use no site no ar.
   Faça o login do tour com a senha redefinida.
3. Localmente, a senha de todas as contas demo é a senha padrão do seed (veja
   o resumo impresso ao final do `seeddemo`).

A escola tem **4 turmas** (1º Ano A/B de manhã, 2º e 3º Ano à tarde), todas as
disciplinas, ~70 contas, notas, frequência, atividades e todos os módulos
preenchidos (comunicados, biblioteca, saúde, portaria, oficinas, reuniões,
inclusão, planejamento, EIA, trajetória etc.).

## 2. Contas (personas do tour)

| Papel | Usuário | Para mostrar |
|---|---|---|
| Direção | `demo.direcao` (Marta) | visão da escola toda, metas, calendário |
| Coordenação | `demo.coordenacao` (Paulo) | acompanhamento pedagógico, EIA, inclusão |
| Secretaria | `demo.secretaria` (Rita) | matrículas, vínculos, biblioteca, saúde, portaria |
| Professores | `demo.prof1` … `demo.prof4` | notas, frequência, diário, planejamento |
| Famílias | `demo.resp1` … | boletim, comunicados, autorizações (resp1 tem 2 filhos) |

> Estudantes não têm login na demo — a visão do aluno aparece pela conta da
> família.

Sugestão: percorra as personas na ordem abaixo. Cada troca de login mostra como
a mesma plataforma muda conforme o papel.

## 3. Direção — a escola em números

Login: `demo.direcao`.

1. **Painel institucional** (`/paineis/`): frequência média, média geral,
   turmas abaixo do mínimo, disciplinas, série/turno, evolução mensal,
   frequência × desempenho, movimento (entradas/transferências), ocorrências
   abertas. Clique numa barra de turma para descer ao painel da turma.
   - Botão **Exportar CSV/Excel** gera o mesmo conteúdo para quem preferir
     planilha.
2. **Metas da escola** (`/paineis/metas/`): metas com prazo e progresso.
3. **Calendário oficial**: eventos letivos, feriados e avaliações.
4. **Comunicados**: avisos publicados pela escola.
5. **Qualidade dos dados** (`/paineis/qualidade-dos-dados/`): notas faltando,
   chamadas incompletas, matrículas sem responsável — a lista de pendências que
   a gestão usa para cobrar o preenchimento.

## 4. Coordenação — acompanhamento pedagógico

Login: `demo.coordenacao` (tem designação "escola toda" na demo).

1. **Painel da coordenação**: turmas acompanhadas, alertas e registros.
2. **EIA / Cognitio** (acompanhamento de habilidades): evidências por
   estudante, observações dos professores e **alertas de aprendizagem**
   gerados automaticamente a partir das notas e da frequência.
3. **Inclusão**: fichas de apoio (casos de acompanhamento especializado).
4. **Ocorrências e planos de intervenção** (pedagógico): registro de
   ocorrências e planos ativos.
5. **Painel da turma** (`/paineis/turma/<id>/`): média, frequência, entregas e
   a matriz estudante × disciplina; clique num estudante para o painel
   individual.

## 5. Professor — o dia a dia da sala

Login: `demo.prof1` (cada professor cobre algumas disciplinas em todas as turmas).

1. **Minhas turmas / atividades de casa**: atividades publicadas, uma em
   rascunho e uma cancelada (mostra os três estados), com entregas registradas.
2. **Trabalhos em grupo**: grupos formados e participações.
3. **Lançamento de notas** e **chamada (frequência)** por turma.
4. **Diário de classe / planejamento de aula**: planos e registros de aula.
5. **Conteúdos de prova (study)**: o que cai na prova e as dúvidas enviadas
   pelas famílias.
6. **Painel do professor** (`/paineis/professor/`): visão das turmas e
   disciplinas do próprio professor, com exportação CSV/Excel.
7. **Simulador de notas** (a partir do painel do estudante): "quanto preciso
   tirar para passar" — nada é gravado.

## 6. Secretaria — a administração da escola

Login: `demo.secretaria`.

1. **Painel da secretaria** (`/paineis/secretaria/`): estudantes, vínculos
   pendentes, estudantes sem matrícula, justificativas e solicitações abertas.
   Botão **Exportar CSV/Excel** traz as listas completas.
2. **Vínculos de responsáveis**: fila com alguns vínculos pendentes de
   validação (de propósito, para mostrar o fluxo de aprovação).
3. **Biblioteca**: acervo, empréstimos ativos, um atrasado e um a vencer.
4. **Saúde (care)**: fichas de saúde, atendimentos e pedidos de medicação.
5. **Portaria (gate)**: carteirinhas e eventos de entrada/saída do dia.
6. **Oficinas (workshops)**: oferta com inscrições abertas.
7. **Reuniões (meetings)**: reuniões agendadas e atas.
8. **Achados e perdidos (lostfound)**, **materiais (supplies)**, **reserva de
   espaços (booking)**, **papelada/documentos (paperwork)**: cada um já tem
   registros para navegar.
9. **Rematrícula (reenroll)**: processo de rematrícula do próximo ano.

## 7. Família — a visão de quem acompanha

Login: `demo.resp1` (tem dois filhos — mostra a troca entre eles).

1. **Boletim do filho**: notas por disciplina, média e frequência.
2. **Comunicados e conversas**: avisos da escola e mensagens.
3. **Autorizações e consultas (enquetes)**: pedidos de autorização e votações.
4. **Solicitações (secretaria)**: abrir e acompanhar pedidos.
5. **Reuniões**: convites e confirmação de presença.
6. **Simulador de notas**: a mesma ferramenta, na visão da família.

## 8. Encerramento

- Reforce que **cada papel vê só o que lhe compete** (a família não vê a
  comparação da turma nem a qualidade dos dados; a coordenação restrita veria
  só as turmas designadas).
- Tudo é **custo zero** e roda em SQLite; nenhum dado sai para serviços
  externos; mídia (fotos/documentos) só abre por view autenticada.
- Ao terminar, limpe a demonstração:
  ```
  python manage.py seeddemo --limpar
  ```

## 9. Checklist rápido (para não esquecer nenhuma aba)

Institucional · Metas · Calendário · Comunicados · Qualidade dos dados ·
Coordenação · EIA/Cognitio · Inclusão · Ocorrências/Planos · Painel da turma ·
Atividades · Trabalhos em grupo · Notas · Frequência · Diário/Planejamento ·
Conteúdos de prova · Painel do professor · Simulador · Painel da secretaria ·
Vínculos · Biblioteca · Saúde · Portaria · Oficinas · Reuniões · Achados e
perdidos · Materiais · Reserva de espaços · Papelada · Rematrícula · Boletim ·
Autorizações/Enquetes · Solicitações · Trajetória (anos anteriores/resultados).
