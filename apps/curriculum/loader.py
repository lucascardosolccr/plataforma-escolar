"""Carga idempotente do catálogo nacional (BNCC) e das referências normativas.

Usada pela migração de dados ``0002`` (com os modelos históricos) e pelo
comando ``manage.py loadcurriculum`` (para recarregar depois de uma correção
no arquivo). Nunca apaga item: um item que sumiu da fonte fica inativo, para
não quebrar o vínculo com planejamentos e atividades já registrados.
"""

import datetime
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
BNCC_FILE = DATA / "bncc_ensino_fundamental.json"
BNCC_SOURCE = "BNCC — Base Nacional Comum Curricular, Educação Infantil e Ensino Fundamental (MEC, versão final, 2018)"
BNCC_URL = "https://basenacionalcomum.mec.gov.br/images/BNCC_EI_EF_110518_versaofinal_site.pdf"
BNCC_CHECKED = datetime.date(2026, 10, 31)
CHECKED = datetime.date(2026, 10, 31)

PLANALTO = "https://www.planalto.gov.br/ccivil_03/"
LDB = PLANALTO + "leis/l9394.htm"
LBI = PLANALTO + "_ato2015-2018/2015/lei/l13146.htm"
LGPD = PLANALTO + "_ato2015-2018/2018/lei/l13709.htm"
D12686 = PLANALTO + "_ato2023-2026/2025/decreto/D12686.htm"
D12773 = PLANALTO + "_Ato2023-2026/2025/decreto/D12773.htm"
L14254 = PLANALTO + "_ato2019-2022/2021/lei/L14254.htm"
L12764 = PLANALTO + "_ato2011-2014/2012/lei/l12764.htm"
P421 = "https://www.ifg.edu.br/attachments/article/47027/PORTARIA%20MEC%20No%20421,%20DE%2015%20DE%20MAIO%20DE%202026.pdf"

# (nome, órgão, dispositivo, trecho, literal?, assunto, etapa, natureza, vigência, url, conferido?, uso na plataforma)
REFERENCES = [
    ("LDB — Lei nº 9.394/1996", "Presidência da República / Congresso Nacional", "Art. 12, VI e VII",
     "VI - articular-se com as famílias e a comunidade, criando processos de integração da sociedade com a escola; "
     "VII - informar pai e mãe, conviventes ou não com seus filhos, e, se for o caso, os responsáveis legais, sobre "
     "a frequência e rendimento dos alunos, bem como sobre a execução da proposta pedagógica da escola;",
     True, "Comunicação com as famílias", "Educação básica", "legal", "alterada", LDB, True,
     "Central de notificações, avisos de nota, frequência, prazos e provas; painéis da família."),
    ("LDB — Lei nº 9.394/1996", "Presidência da República / Congresso Nacional", "Art. 13, III e IV",
     "III - zelar pela aprendizagem dos alunos; IV - estabelecer estratégias de recuperação para os alunos de menor "
     "rendimento;", True, "Acompanhamento da aprendizagem", "Educação básica", "legal", "alterada", LDB, True,
     "Evidências de aprendizagem e indicação de habilidades que precisam de retomada."),
    ("LDB — Lei nº 9.394/1996", "Presidência da República / Congresso Nacional", "Art. 24, V, a",
     "a) avaliação contínua e cumulativa do desempenho do aluno, com prevalência dos aspectos qualitativos sobre os "
     "quantitativos e dos resultados ao longo do período sobre os de eventuais provas finais;",
     True, "Avaliação da aprendizagem", "Ensino fundamental e médio", "legal", "alterada", LDB, True,
     "Evidências qualitativas por habilidade; indicadores de acompanhamento, sem ranking."),
    ("LDB — Lei nº 9.394/1996", "Presidência da República / Congresso Nacional", "Art. 26, caput",
     "Os currículos da educação infantil, do ensino fundamental e do ensino médio devem ter base nacional comum, a "
     "ser complementada, em cada sistema de ensino e em cada estabelecimento escolar, por uma parte diversificada, "
     "exigida pelas características regionais e locais da sociedade, da cultura, da economia e dos educandos.",
     True, "Currículo", "Educação básica", "legal", "alterada", LDB, True,
     "Catálogo com a BNCC (base comum), objetivos do Currículo em Movimento do DF e objetivos próprios da escola."),
    ("LDB — Lei nº 9.394/1996", "Presidência da República / Congresso Nacional", "Art. 4º, III",
     "III - atendimento educacional especializado gratuito aos educandos com deficiência, transtornos globais do "
     "desenvolvimento e altas habilidades ou superdotação, transversal a todos os níveis, etapas e modalidades, "
     "preferencialmente na rede regular de ensino;", True, "Educação especial", "Educação básica", "legal",
     "alterada", LDB, True, "Módulo de necessidades específicas e plano individualizado."),
    ("LDB — Lei nº 9.394/1996", "Presidência da República / Congresso Nacional", "Art. 58, caput; art. 59, I",
     "Art. 58: Entende-se por educação especial, para os efeitos desta Lei, a modalidade de educação escolar "
     "oferecida preferencialmente na rede regular de ensino, para educandos com deficiência, transtornos globais do "
     "desenvolvimento e altas habilidades ou superdotação. Art. 59, I: currículos, métodos, técnicas, recursos "
     "educativos e organização específicos, para atender às suas necessidades;",
     True, "Educação especial", "Educação básica", "legal", "alterada", LDB, True,
     "Recursos de acessibilidade e adaptações registrados por estudante e visíveis aos professores dele."),
    ("Lei Brasileira de Inclusão — Lei nº 13.146/2015", "Presidência da República / Congresso Nacional",
     "Art. 3º, III e VI",
     "III - tecnologia assistiva ou ajuda técnica: produtos, equipamentos, dispositivos, recursos, metodologias, "
     "estratégias, práticas e serviços que objetivem promover a funcionalidade, relacionada à atividade e à "
     "participação da pessoa com deficiência ou com mobilidade reduzida, visando à sua autonomia, independência, "
     "qualidade de vida e inclusão social; VI - adaptações razoáveis: adaptações, modificações e ajustes necessários "
     "e adequados que não acarretem ônus desproporcional e indevido, quando requeridos em cada caso, a fim de "
     "assegurar que a pessoa com deficiência possa gozar ou exercer, em igualdade de condições e oportunidades com "
     "as demais pessoas, todos os direitos e liberdades fundamentais;",
     True, "Acessibilidade", "Todas", "legal", "alterada", LBI, True,
     "Campos 'tecnologia assistiva' e 'adaptações razoáveis' do plano individualizado."),
    ("Lei Brasileira de Inclusão — Lei nº 13.146/2015", "Presidência da República / Congresso Nacional",
     "Art. 28, III, V e VII",
     "III - projeto pedagógico que institucionalize o atendimento educacional especializado, assim como os demais "
     "serviços e adaptações razoáveis [...]; V - adoção de medidas individualizadas e coletivas [...]; VII - "
     "planejamento de estudo de caso, de elaboração de plano de atendimento educacional especializado, de "
     "organização de recursos e serviços de acessibilidade e de disponibilização e usabilidade pedagógica de "
     "recursos de tecnologia assistiva;", True, "Educação inclusiva", "Todas", "legal", "alterada", LBI, True,
     "Estudo de caso, plano individualizado (PAEE/PEI) e recursos de acessibilidade."),
    ("Decreto nº 12.686/2025 (Política Nacional de Educação Especial Inclusiva)", "Presidência da República",
     "Art. 11 (estudo de caso), §§ 3º e 7º",
     "O estudo de caso é a metodologia de produção, sistematização e registro de informações e estratégias, etapa "
     "inicial; o resultado fundamenta o PAEE e o PEI (§ 2º, redação do Decreto nº 12.773/2025); deve ser garantido o "
     "envolvimento do estudante e dos familiares (§ 3º); a garantia do AEE não será condicionada à exigência de "
     "diagnóstico, laudo ou relatório (§ 7º).", False, "Educação especial inclusiva", "Educação básica",
     "regulamento", "alterada", D12686, True,
     "Necessidades de apoio registráveis sem laudo; envio de laudo nunca é condição para o plano."),
    ("Decreto nº 12.686/2025 (Política Nacional de Educação Especial Inclusiva)", "Presidência da República",
     "Art. 12 (redação do Decreto nº 12.773/2025)",
     "É obrigatória a realização de documento individualizado de natureza pedagógica, com atualização contínua, como "
     "o PAEE e o PEI, que derive do estudo de caso e integre o projeto político-pedagógico.", False,
     "Plano individualizado", "Educação básica", "regulamento", "alterada", D12686, True,
     "Plano individualizado de acompanhamento com estudo de caso, PAEE e PEI e histórico de revisões."),
    ("Decreto nº 12.773/2025", "Presidência da República", "Altera o Decreto nº 12.686/2025",
     "Inclui o PEI ao lado do PAEE (arts. 11, 12 e 14) e estabelece que a oferta do profissional de apoio escolar "
     "independe de diagnóstico ou laudo (art. 14, § 2º).", False, "Educação especial inclusiva", "Educação básica",
     "regulamento", "vigente", D12773, True, "Mesma base do plano individualizado."),
    ("Portaria MEC nº 421/2026", "Ministério da Educação", "Art. 7º, §§ 2º, 3º e 4º",
     "§ 2º As redes de ensino poderão adotar documento único que contemple as finalidades do PAEE e do PEI [...]. "
     "§ 3º O PAEE e o PEI deverão ser revisados anualmente, de modo a compatibilizá-los com a avaliação contínua do "
     "estudante. § 4º A garantia da matrícula, da escolarização e da oferta do AEE, na educação básica, ao estudante "
     "público da educação especial não poderá estar condicionada à exigência de diagnóstico, laudo, relatório ou "
     "qualquer outro documento emitido por profissional de saúde.", True, "Plano individualizado",
     "Educação básica", "regulamento", "alterada", P421, True,
     "Plano em documento único (PAEE + PEI), revisão com prazo de no máximo um ano, laudo nunca obrigatório. "
     "Texto conferido na cópia do Sistema de Consulta à Legislação do MEC hospedada pelo IFG; alterada pela "
     "Portaria MEC nº 550/2026 (não conferida)."),
    ("Portaria MEC nº 421/2026", "Ministério da Educação", "Arts. 10 e 11 (conteúdo mínimo do PAEE e do PEI)",
     "PAEE: materiais e recursos para eliminar ou minimizar barreiras; necessidade de tecnologia assistiva e "
     "comunicação aumentativa e alternativa; necessidade de profissional de apoio, intérprete de Libras e "
     "guia-intérprete; demandas de formação e de acionamento da rede de proteção. PEI: atividades no AEE e "
     "articulação com o professor regente; medidas de acessibilidade curricular, didático-pedagógica e avaliativa; "
     "estratégias de acompanhamento e monitoramento; registro das devolutivas às famílias.", False,
     "Plano individualizado", "Educação básica", "regulamento", "alterada", P421, True,
     "Seções do plano individualizado e registro de devolutivas à família."),
    ("Lei nº 14.254/2021", "Presidência da República / Congresso Nacional", "Arts. 1º a 3º",
     "Programa de acompanhamento integral para educandos com dislexia, TDAH ou outro transtorno de aprendizagem: "
     "identificação precoce, encaminhamento para diagnóstico, apoio educacional na rede de ensino e apoio "
     "terapêutico na rede de saúde; acompanhamento específico pelos educadores da escola, da forma mais precoce "
     "possível.", False, "Transtornos de aprendizagem", "Educação básica", "legal", "vigente", L14254, True,
     "Necessidades de apoio pedagógico registráveis pela equipe, com ou sem laudo."),
    ("Lei nº 12.764/2012 (TEA)", "Presidência da República / Congresso Nacional", "Art. 1º, § 2º",
     "A pessoa com transtorno do espectro autista é considerada pessoa com deficiência, para todos os efeitos "
     "legais.", True, "Educação especial", "Todas", "legal", "alterada", L12764, True,
     "Categoria TEA no cadastro de necessidades específicas (lista configurável)."),
    ("LGPD — Lei nº 13.709/2018", "Presidência da República / Congresso Nacional", "Art. 5º, II",
     "Dado pessoal sensível inclui dado referente à saúde, quando vinculado a uma pessoa natural.", False,
     "Proteção de dados", "Todas", "legal", "alterada", LGPD, True,
     "Laudos e categorias tratados como dados sensíveis: acesso restrito, registro de cada consulta."),
    ("LGPD — Lei nº 13.709/2018", "Presidência da República / Congresso Nacional", "Art. 6º, I a III",
     "I - finalidade: realização do tratamento para propósitos legítimos, específicos, explícitos e informados ao "
     "titular; II - adequação: compatibilidade do tratamento com as finalidades informadas ao titular, de acordo com "
     "o contexto; III - necessidade: limitação do tratamento ao mínimo necessário para a realização de suas "
     "finalidades.", True, "Proteção de dados", "Todas", "legal", "alterada", LGPD, True,
     "Aviso de finalidade ao responsável; professor vê só orientações pedagógicas, não o laudo."),
    ("LGPD — Lei nº 13.709/2018", "Presidência da República / Congresso Nacional", "Art. 11, I e II (a, b)",
     "Dados sensíveis podem ser tratados com consentimento específico e destacado ou, sem consentimento, quando "
     "indispensável para cumprimento de obrigação legal ou regulatória ou para execução de políticas públicas "
     "previstas em leis ou regulamentos.", False, "Proteção de dados", "Todas", "legal", "alterada", LGPD, True,
     "A base legal é definida pela escola com o encarregado de dados; a plataforma não presume consentimento."),
    ("LGPD — Lei nº 13.709/2018", "Presidência da República / Congresso Nacional", "Art. 14, caput",
     "O tratamento de dados pessoais de crianças e de adolescentes deverá ser realizado em seu melhor interesse.",
     True, "Proteção de dados", "Todas", "legal", "alterada", LGPD, True,
     "Proibição de uso de laudos para ranking, publicidade ou treino de IA; acesso por necessidade de conhecimento."),
    ("LGPD — Lei nº 13.709/2018", "Presidência da República / Congresso Nacional", "Arts. 37 e 46",
     "Registro das operações de tratamento (art. 37) e medidas de segurança técnicas e administrativas aptas a "
     "proteger os dados pessoais de acessos não autorizados (art. 46).", False, "Segurança da informação",
     "Todas", "legal", "alterada", LGPD, True,
     "Auditoria de consultas, downloads e alterações; arquivos fora de URL pública."),
    ("Enunciado CD/ANPD nº 1/2023", "Autoridade Nacional de Proteção de Dados", "Enunciado",
     "Segundo as sínteses consultadas, o tratamento de dados de crianças e adolescentes pode se apoiar nas hipóteses "
     "dos arts. 7º e 11 da LGPD, observado o melhor interesse. Texto oficial não conferido nesta revisão.",
     False, "Proteção de dados", "Todas", "orientacao", "a_verificar", "https://www.gov.br/anpd/", False,
     "Fundamento para não tratar o consentimento como única base possível."),
    ("BNCC — Base Nacional Comum Curricular", "Ministério da Educação / Conselho Nacional de Educação",
     "Competências gerais e habilidades do Ensino Fundamental",
     "Documento normativo que define as aprendizagens essenciais. As 10 competências gerais e as 1.304 habilidades "
     "do Ensino Fundamental foram carregadas do PDF oficial, sem reescrita.", False, "Currículo",
     "Educação infantil e ensino fundamental", "curricular", "vigente", BNCC_URL, True,
     "Catálogo curricular, vínculo com planejamentos, atividades e avaliações, indicadores de acompanhamento."),
    ("Currículo em Movimento do Distrito Federal — Ensino Fundamental (2ª ed., 2018)",
     "Secretaria de Estado de Educação do DF", "Objetivos de aprendizagem e conteúdos por ano",
     "Documento curricular da rede pública do DF, alinhado à BNCC. O portal da SEEDF não pôde ser acessado nesta "
     "revisão (certificado inválido); os objetivos não foram transcritos. A escola importa os objetivos com a fonte.",
     False, "Currículo", "Ensino fundamental", "curricular", "a_verificar",
     "https://www.educacao.df.gov.br/curriculo-em-movimento/", False,
     "Itens 'objetivo do Currículo em Movimento' importados pela escola e relacionados às habilidades da BNCC."),
]


def load_bncc(CurriculumItem):
    data = json.loads(BNCC_FILE.read_text(encoding="utf-8"))
    seen = set()
    created = updated = 0
    for n, text in sorted(data["competencias_gerais"].items(), key=lambda kv: int(kv[0])):
        code = f"CG{int(n):02d}"
        seen.add(("competencia_geral", code))
        _, new = CurriculumItem.objects.update_or_create(
            school=None, kind="competencia_geral", code=code,
            defaults={"text": text, "stage": "Educação básica", "component": "", "years": "",
                      "source": BNCC_SOURCE, "source_url": BNCC_URL, "verified_on": BNCC_CHECKED, "active": True})
        created += new
        updated += not new
    for h in data["habilidades"]:
        seen.add(("habilidade", h["code"]))
        _, new = CurriculumItem.objects.update_or_create(
            school=None, kind="habilidade", code=h["code"],
            defaults={"text": h["text"], "stage": "Ensino Fundamental", "component": h["component"],
                      "years": h["years"], "source": BNCC_SOURCE, "source_url": BNCC_URL,
                      "verified_on": BNCC_CHECKED, "needs_review": bool(h.get("review")), "active": True})
        created += new
        updated += not new
    for item in CurriculumItem.objects.filter(school__isnull=True, kind__in=["competencia_geral", "habilidade"]):
        if (item.kind, item.code) not in seen and item.active:
            item.active = False
            item.save(update_fields=["active"])
    return created, updated


def load_references(NormativeReference):
    count = 0
    for order, row in enumerate(REFERENCES):
        (name, authority, provision, excerpt, literal, topic, stage, nature, validity, url, checked, use) = row
        NormativeReference.objects.update_or_create(
            name=name, provision=provision,
            defaults={"authority": authority, "excerpt": excerpt, "excerpt_is_literal": literal, "topic": topic,
                      "stage": stage, "nature": nature, "validity": validity, "url": url,
                      "verified_on": CHECKED if checked else None, "platform_use": use, "order": order})
        count += 1
    return count
